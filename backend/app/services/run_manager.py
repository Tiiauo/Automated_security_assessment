import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from app.agents.contracts import STAGES
from app.agents.engine import RoleEngine, RoleFailed
from app.core.db import SessionLocal
from app.models.collab import RuntimeLog
from app.models.project import Project, ProjectRun
from app.models.runtime import RuntimeStage, WorkerTask
from app.sandbox.tools import SandboxTools
from app.services import monitoring, sandbox_service, source_service
from app.services.run_store import RunStore

logger = logging.getLogger(__name__)


@dataclass
class RunHandle:
    run_id: int
    cancel: asyncio.Event
    task: asyncio.Task


class RunManager:
    """内存仅保存句柄与取消信号；所有业务状态都从数据库读取。"""

    def __init__(self, sessions=SessionLocal, *, engine_factory=RoleEngine, tools_factory=SandboxTools):
        self.sessions = sessions
        self.engine_factory = engine_factory
        self.tools_factory = tools_factory
        self.handles: dict[int, RunHandle] = {}
        self.preparing: set[int] = set()
        self.admission_lock = asyncio.Lock()

    def launch(self, project_id: int, run_id: int, raw: dict[str, str], *, mock: bool) -> None:
        if project_id in self.handles:
            raise RuntimeError("项目已有执行句柄")
        cancel = asyncio.Event()
        task = asyncio.create_task(
            self._run(project_id, run_id, dict(raw), mock, cancel), name=f"project-{project_id}-run-{run_id}"
        )
        self.handles[project_id] = RunHandle(run_id, cancel, task)

    async def cancel(self, project_id: int) -> None:
        handle = self.handles.get(project_id)
        if handle:
            if not handle.cancel.is_set():
                handle.cancel.set()
                handle.task.cancel()
            try:
                await handle.task
            except asyncio.CancelledError:
                pass
            finally:
                if self.handles.get(project_id) is handle:
                    self.handles.pop(project_id, None)

    async def _running_project(self, db, project_id: int, run_id: int, *, lock=False) -> Project:
        project = await db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
            if lock
            else select(Project).where(Project.id == project_id)
        )
        if project is None or project.project_status != "running" or project.current_run_id != run_id:
            raise asyncio.CancelledError
        return project

    async def _run(self, project_id, run_id, raw, mock, cancel):
        store = RunStore(self.sessions, project_id, run_id)
        sampler = asyncio.create_task(
            monitoring.sample_project(
                self.sessions, project_id, run_id, float(raw["monitor.resource_interval_seconds"])
            )
        )
        try:
            engine = self.engine_factory(raw, mock=mock)
            for stage_name, roles in STAGES.items():
                async with self.sessions() as db:
                    await self._running_project(db, project_id, run_id, lock=True)
                    previous = (
                        await db.scalars(
                            select(RuntimeStage).where(
                                RuntimeStage.project_id == project_id,
                                RuntimeStage.run_id == run_id,
                            )
                        )
                    ).all()
                    if any(stage.stage_status != "success" for stage in previous):
                        raise RoleFailed("前置阶段未成功，禁止推进")
                    stage = RuntimeStage(
                        project_id=project_id,
                        run_id=run_id,
                        stage_name=stage_name,
                        stage_status="running",
                        started_at=datetime.now(UTC),
                    )
                    db.add(stage)
                    await db.commit()
                    stage_id = stage.id
                active_role = "阶段准备"
                try:
                    async with asyncio.timeout(float(raw["timeout.stage_seconds"])):
                        if stage_name == "report_generate":
                            await self._check_fingerprint(project_id, run_id, raw)
                        for role in roles:
                            active_role = role
                            await self._worker(store, engine, stage_name, stage_id, role, raw, mock, cancel)
                        if stage_name == "done":
                            active_role = "调度器销毁容器"
                            sampler.cancel()
                            await asyncio.gather(sampler, return_exceptions=True)
                            async with self.sessions() as db:
                                project = await self._running_project(db, project_id, run_id)
                                sandbox_id = project.sandbox_id
                            if sandbox_id:
                                await sandbox_service.destroy_run(sandbox_id)
                except TimeoutError as exc:
                    raise RoleFailed(
                        f"stage_timeout: {stage_name}/{active_role} 第 {run_id} 轮"
                        f"超过 {raw['timeout.stage_seconds']} 秒"
                    ) from exc
                async with self.sessions() as db:
                    project = await self._running_project(db, project_id, run_id, lock=True)
                    stage = await db.get(RuntimeStage, stage_id)
                    stage.stage_status = "success"
                    stage.finished_at = datetime.now(UTC)
                    if stage_name == "done":
                        project.sandbox_id = None
                        project.project_status = "completed"
                        project.last_finished_at = datetime.now(UTC)
                        project.updated_at = datetime.now(UTC)
                    await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("run failed: project=%s run=%s", project_id, run_id)
            await self.finish(project_id, run_id, "failed", str(exc) or type(exc).__name__)
        finally:
            sampler.cancel()
            await asyncio.gather(sampler, return_exceptions=True)
            current = self.handles.get(project_id)
            if current and current.task is asyncio.current_task():
                self.handles.pop(project_id, None)

    async def _worker(self, store, engine, stage_name, stage_id, role, raw, mock, cancel):
        async with self.sessions() as db:
            project = await self._running_project(db, store.project_id, store.run_id, lock=True)
            task_content = f"阶段 {stage_name}，角色 {role}。项目任务：{project.task_content}"
            worker = WorkerTask(
                project_id=project.id,
                run_id=store.run_id,
                stage_id=stage_id,
                worker_role=role,
                task_content=task_content,
                task_status="running",
                started_at=datetime.now(UTC),
                retry_count=0,
            )
            db.add(worker)
            await db.commit()
            worker_id, sandbox_id = worker.id, project.sandbox_id
        context = await store.context()
        try:
            async with asyncio.timeout(float(raw["timeout.worker_seconds"])):
                result = await engine.execute(
                    stage=stage_name,
                    role=role,
                    task=task_content,
                    context=context,
                    tools=self.tools_factory(sandbox_id, int(raw["timeout.command_seconds"])),
                    observe=store.observer(stage_id, worker_id, role),
                    cancel=cancel,
                )
        except TimeoutError as exc:
            raise RoleFailed(
                f"worker_timeout: {stage_name}/{role} 第 {store.run_id} 轮超过 {raw['timeout.worker_seconds']} 秒"
            ) from exc
        except RoleFailed as exc:
            raise RoleFailed(f"{stage_name}/{role} 第 {store.run_id} 轮: {exc}") from exc
        if role == "env_inspector":
            failed = [f"{check['name']}: {check['detail']}" for check in result["checks"] if not check["passed"]]
            if failed:
                raise RoleFailed("environment_scan/env_inspector: 基础环境检查失败：" + "; ".join(failed))
        if role == "ops_assistant" and any(action["status"] == "failed" for action in result["actions"]):
            raise RoleFailed(f"{stage_name}/ops_assistant: 运维操作失败")
        if cancel.is_set():
            raise asyncio.CancelledError
        if role == "report_writer":
            await self._check_fingerprint(store.project_id, store.run_id, raw)
        async with self.sessions() as db, db.begin():
            await self._running_project(db, store.project_id, store.run_id, lock=True)
            await store.persist(db, stage_name, role, stage_id, result, mock=mock)
            worker = await db.get(WorkerTask, worker_id)
            worker.task_status = "success"
            worker.result_summary = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            worker.finished_at = datetime.now(UTC)

    async def _check_fingerprint(self, project_id: int, run_id: int, raw: dict[str, str]):
        async with self.sessions() as db:
            project = await self._running_project(db, project_id, run_id)
            if project.source_type != "local_path":
                return
            await source_service.validate_source(db, "local_path", project.source_path, raw=raw)
            directory = await asyncio.to_thread(Path(project.source_path).resolve)
            after = await asyncio.to_thread(source_service.compute_fingerprint, directory)
            run = await db.get(ProjectRun, (project_id, run_id))
            run.source_fingerprint_after = after
            await db.commit()
            if after != run.source_fingerprint:
                raise RoleFailed("源码指纹已变化，禁止生成报告；请固定源码后重新启动")

    async def finish(self, project_id: int, run_id: int, status: str, reason: str) -> bool:
        async with self.sessions() as db:
            project = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            if project is None or project.current_run_id != run_id or project.project_status != "running":
                return False
            now = datetime.now(UTC)
            project.project_status = status
            project.updated_at = now
            workers = (
                await db.scalars(
                    select(WorkerTask).where(
                        WorkerTask.project_id == project_id,
                        WorkerTask.run_id == run_id,
                        WorkerTask.task_status == "running",
                    )
                )
            ).all()
            for worker in workers:
                worker.task_status, worker.error_message, worker.finished_at = "failed", reason, now
            stages = (
                await db.scalars(
                    select(RuntimeStage).where(
                        RuntimeStage.project_id == project_id,
                        RuntimeStage.run_id == run_id,
                        RuntimeStage.stage_status == "running",
                    )
                )
            ).all()
            for stage in stages:
                stage.stage_status = "stopped" if status == "stopped" else "failed"
                stage.error_message, stage.finished_at = reason, now
            db.add(
                RuntimeLog(
                    project_id=project_id,
                    run_id=run_id,
                    log_level="warning" if status == "stopped" else "error",
                    log_content=reason,
                )
            )
            sandbox_id = project.sandbox_id
            await db.commit()
        if sandbox_id:
            await sandbox_service.interrupt_run(sandbox_id)
        return True

    async def recover(self):
        async with self.sessions() as db:
            projects = (await db.scalars(select(Project).where(Project.project_status == "running"))).all()
            references = [(p.id, p.current_run_id, p.sandbox_id) for p in projects]
            now = datetime.now(UTC)
            await db.execute(
                update(Project)
                .where(Project.project_status == "running")
                .values(
                    project_status="failed",
                    updated_at=now,
                )
            )
            await db.execute(
                update(RuntimeStage)
                .where(RuntimeStage.stage_status == "running")
                .values(
                    stage_status="failed",
                    error_message="服务重启中断",
                    finished_at=now,
                )
            )
            await db.execute(
                update(WorkerTask)
                .where(WorkerTask.task_status == "running")
                .values(
                    task_status="failed",
                    error_message="服务重启中断",
                    finished_at=now,
                )
            )
            for project_id, run_id, _ in references:
                db.add(RuntimeLog(project_id=project_id, run_id=run_id, log_level="error", log_content="服务重启中断"))
            await db.commit()
        for _, _, sandbox_id in references:
            if sandbox_id:
                await sandbox_service.interrupt_run(sandbox_id)

    async def shutdown(self):
        handles = [(project_id, handle.run_id) for project_id, handle in self.handles.items()]
        await asyncio.gather(*(self.cancel(project_id) for project_id, _ in handles))
        await asyncio.gather(
            *(self.finish(project_id, run_id, "failed", "服务重启中断") for project_id, run_id in handles)
        )


run_manager = RunManager()
