import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.core.paths import data_root
from app.models.analysis import AttackPath, AttackPathItem, Vulnerability
from app.models.collab import ChatMessage, RuntimeLog
from app.models.project import Project, ProjectRun
from app.models.runtime import RuntimeStage, WorkerTask
from app.services import report_service
from app.services.analysis_query import path_steps
from app.services.events import payload
from app.services.monitoring import record_usage


def _append_log(project_id: int, run_id: int, content: str) -> None:
    directory = data_root() / "runtime_logs" / str(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"run-{run_id}.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps({"at": datetime.now(UTC).isoformat(), "content": content}, ensure_ascii=False) + "\n")


class RunStore:
    def __init__(self, sessions, project_id: int, run_id: int):
        self.sessions = sessions
        self.project_id = project_id
        self.run_id = run_id

    async def context(self) -> dict:
        async with self.sessions() as db:
            project = await db.get(Project, self.project_id)
            source = await db.get(ProjectRun, (self.project_id, self.run_id))
            stages = (
                await db.scalars(
                    select(RuntimeStage)
                    .where(RuntimeStage.project_id == self.project_id, RuntimeStage.run_id == self.run_id)
                    .order_by(RuntimeStage.id)
                )
            ).all()
            paths = (
                await db.scalars(
                    select(AttackPath)
                    .where(AttackPath.project_id == self.project_id, AttackPath.run_id == self.run_id)
                    .order_by(AttackPath.id)
                )
            ).all()
            steps = await path_steps(db, [path.id for path in paths])
            vulnerabilities = (
                await db.scalars(
                    select(Vulnerability)
                    .where(
                        Vulnerability.project_id == self.project_id,
                        Vulnerability.run_id == self.run_id,
                    )
                    .order_by(Vulnerability.id)
                )
            ).all()
            workers = (
                await db.scalars(
                    select(WorkerTask)
                    .where(
                        WorkerTask.project_id == self.project_id,
                        WorkerTask.run_id == self.run_id,
                    )
                    .order_by(WorkerTask.id)
                )
            ).all()
            return {
                "project_id": self.project_id,
                "run_id": self.run_id,
                "project_name": project.project_name,
                "project": {
                    key: payload(project)[key]
                    for key in ("project_name", "source_type", "source_path", "task_content", "last_started_at")
                },
                "source": payload(source),
                "stages": [payload(stage) for stage in stages],
                "workers": [payload(worker) for worker in workers],
                "paths": [{**payload(path), "steps": steps.get(path.id, [])} for path in paths],
                "prior_results": [
                    {"role": w.worker_role, "result": w.result_summary} for w in workers if w.task_status == "success"
                ],
                "environment_limitations": [
                    item
                    for worker in workers
                    if worker.worker_role == "env_inspector" and worker.task_status == "success"
                    for item in json.loads(worker.result_summary or "{}").get("limitations", [])
                ],
                "vulnerabilities": [{**payload(v), "title": v.vuln_title} for v in vulnerabilities],
            }

    def observer(self, stage_id: int, worker_id: int, role: str):
        async def observe(event: str, **data):
            text = json.dumps({"event": event, **data}, ensure_ascii=False)
            async with self.sessions() as db:
                if event == "retry":
                    worker = await db.get(WorkerTask, worker_id)
                    worker.retry_count = data["retry_count"]
                message_type = (
                    "tool_call" if event in {"tool", "tool_result"} else "error" if event == "error" else "info"
                )
                if event == "response":
                    message_type = "result"
                    await record_usage(db, self.project_id, self.run_id, tokens=data["tokens"])
                    db.add(RuntimeLog(log_level="info", log_content=f"模型实际版本：{data['model']}"))
                db.add(
                    ChatMessage(
                        project_id=self.project_id,
                        run_id=self.run_id,
                        worker_role=role,
                        message_type=message_type,
                        message_text=text,
                    )
                )
                db.add(
                    RuntimeLog(
                        project_id=self.project_id,
                        run_id=self.run_id,
                        stage_id=stage_id,
                        worker_task_id=worker_id,
                        log_level="error" if event == "error" else "debug",
                        log_content=text,
                    )
                )
                await db.commit()
            await asyncio.to_thread(_append_log, self.project_id, self.run_id, text)

        return observe

    async def persist(self, db, stage: str, role: str, stage_id: int, result, *, mock: bool) -> None:
        if role == "env_inspector":
            for item in result["limitations"]:
                text = f"动态验证受限：{item['name']}：{item['detail']}"
                db.add(
                    ChatMessage(
                        project_id=self.project_id,
                        run_id=self.run_id,
                        worker_role=role,
                        message_type="warning",
                        message_text=text,
                    )
                )
                db.add(
                    RuntimeLog(
                        project_id=self.project_id,
                        run_id=self.run_id,
                        stage_id=stage_id,
                        log_level="warning",
                        log_content=text,
                    )
                )
        if stage == "code_analysis" and role == "code_analyst":
            rows = (
                await db.scalars(
                    select(Vulnerability).where(
                        Vulnerability.project_id == self.project_id, Vulnerability.run_id == self.run_id
                    )
                )
            ).all()
            by_key = {(v.file_path, v.vuln_type): v for v in rows}
            number = max((int(v.vuln_code.split("-")[1]) for v in rows), default=0)
            for candidate in result["candidates"]:
                key = (candidate["file_path"], candidate["vuln_type"])
                existing = by_key.get(key)
                if existing:
                    evidence = existing.evidence_text or ""
                    archive = (
                        data_root()
                        / "workspace"
                        / str(self.project_id)
                        / str(self.run_id)
                        / f"{existing.vuln_code}-evidence.txt"
                    )
                    if await asyncio.to_thread(archive.is_file):
                        evidence = await asyncio.to_thread(archive.read_text, encoding="utf-8")
                    if candidate["evidence_text"] not in evidence:
                        evidence += "\n" + candidate["evidence_text"]
                    existing.evidence_text = await self.evidence(existing.vuln_code, evidence)
                    continue
                number += 1
                values = dict(candidate)
                if not mock:
                    normalize_risk(values)
                row = Vulnerability(
                    project_id=self.project_id,
                    run_id=self.run_id,
                    stage_id=stage_id,
                    vuln_code=f"VULN-{number:03d}",
                    vuln_type=candidate["vuln_type"],
                    vuln_title=candidate["title"],
                    risk_level=values["risk_level"],
                    cvss_score=candidate.get("cvss_score"),
                    file_path=candidate["file_path"],
                    condition_text=candidate["condition_text"],
                    evidence_text=await self.evidence(f"VULN-{number:03d}", values["evidence_text"]),
                    impact_text=candidate.get("impact_text"),
                    verify_status="pending",
                )
                db.add(row)
                by_key[key] = row
        if stage == "vulnerability_verify":
            rows = (
                await db.scalars(
                    select(Vulnerability).where(
                        Vulnerability.project_id == self.project_id,
                        Vulnerability.run_id == self.run_id,
                    )
                )
            ).all()
            by_code = {v.vuln_code: v for v in rows}
            if role == "vuln_verifier":
                for verdict in result["verdicts"]:
                    row = by_code[verdict["vuln_code"]]
                    values = dict(verdict)
                    if not mock:
                        normalize_risk(values)
                    values["evidence_text"] = await self.evidence(row.vuln_code, values["evidence_text"])
                    for key, value in values.items():
                        if key != "vuln_code":
                            setattr(
                                row, key, Decimal(str(value)) if key == "cvss_score" and value is not None else value
                            )
                    row.stage_id = stage_id
            else:
                for number, path in enumerate(result["paths"], 1):
                    row = AttackPath(
                        project_id=self.project_id,
                        run_id=self.run_id,
                        path_code=f"PATH-{number:03d}",
                        path_title=path["path_title"],
                        path_summary=path["path_summary"],
                        final_impact_text=path["final_impact_text"],
                    )
                    db.add(row)
                    await db.flush()
                    for order, step in enumerate(path["steps"], 1):
                        db.add(
                            AttackPathItem(
                                path_id=row.id,
                                vuln_id=by_code[step["vuln_code"]].id,
                                step_order=order,
                                step_text=step["step_text"],
                            )
                        )
        elif stage == "report_generate" and role == "report_writer":
            await report_service.save(db, self.project_id, self.run_id, result, await self.context(), mock=mock)

    async def evidence(self, code: str, text: str) -> str:
        raw = text.encode("utf-8")
        if len(raw) <= 65536:
            return text
        directory = data_root() / "workspace" / str(self.project_id) / str(self.run_id)
        path = directory / f"{code}-evidence.txt"
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, text, encoding="utf-8")
        return raw[:64000].decode("utf-8", errors="ignore") + f"\n[已截断；完整证据：{path}]"


def normalize_risk(value: dict) -> None:
    score = value.get("cvss_score")
    if score is None:
        value["risk_level"] = "medium"
        value["evidence_text"] += "\n评分为推断值，待人工复核"
    else:
        value["risk_level"] = next(
            level
            for threshold, level in ((9, "critical"), (7, "high"), (4, "medium"), (0.1, "low"), (0, "info"))
            if score >= threshold
        )
