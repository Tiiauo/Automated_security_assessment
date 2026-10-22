import asyncio
import json
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.agents.contracts import ENV_CHECKS, STAGES
from app.agents.engine import RoleEngine
from app.agents.mock import mock_output
from app.core.config import get_settings
from app.core.paths import data_root
from app.main import app
from app.models.analysis import AttackPathItem
from app.models.collab import ChatMessage, ResourceUsage, RuntimeLog
from app.models.project import Project
from app.models.report import Report
from app.models.runtime import RuntimeStage, WorkerTask
from app.services import config_service, sandbox_service
from tests.conftest import login
from tests.test_projects_api import create_project, setup_admin


async def start(client, tmp_path, manager, *, engine=RoleEngine):
    manager.engine_factory = engine
    source = await setup_admin(client, tmp_path)
    created = await create_project(client, source)
    project_id = created["project_id"]
    response = await client.post(f"/api/projects/{project_id}/start")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["sandbox_id"]
    return project_id, source


async def settled(manager, project_id):
    handle = manager.handles.get(project_id)
    if handle:
        await asyncio.wait_for(asyncio.shield(handle.task), 15)


async def test_ac06_mock_all_stages_and_done_destroy_order(client, tmp_path, manager, db_session_factory, monkeypatch):
    destroyed = []

    async def destroy(reference):
        async with db_session_factory() as db:
            stages = (await db.scalars(select(RuntimeStage).order_by(RuntimeStage.id))).all()
            workers = (await db.scalars(select(WorkerTask).order_by(WorkerTask.id))).all()
            assert stages[-1].stage_name == "done" and stages[-1].stage_status == "running"
            assert len(workers) == 10 and all(w.task_status == "success" for w in workers)
            assert (await db.get(Project, stages[-1].project_id)).project_status == "running"
        destroyed.append(reference)

    monkeypatch.setattr(sandbox_service, "destroy_run", destroy)
    project_id, source = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "completed" and detail["sandbox_id"] is None
    assert detail["last_finished_at"] and len(destroyed) == 1
    assert detail["counts"] == {"vulnerabilities": 2, "attack_paths": 1, "reports": 1}
    assert detail["runs"][0]["source_fingerprint"] == detail["runs"][0]["source_fingerprint_after"]
    assert (source / "main.py").read_text("utf-8") == "print('ok')\n"

    stages = (await client.get(f"/api/projects/{project_id}/stages")).json()["data"]
    assert [s["stage_name"] for s in stages["items"]] == list(STAGES)
    assert all(s["stage_status"] == "success" for s in stages["items"])
    workers = (await client.get(f"/api/projects/{project_id}/workers")).json()["data"]
    assert [w["worker_role"] for w in workers["items"]] == [role for roles in STAGES.values() for role in roles]
    assert all(
        w["task_status"] == "success"
        and w["task_content"]
        and w["result_summary"]
        and w["started_at"]
        and w["finished_at"]
        and w["error_message"] is None
        for w in workers["items"]
    )
    assert all(
        a["finished_at"] <= b["started_at"] for a, b in zip(workers["items"], workers["items"][1:], strict=False)
    )
    async with db_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(AttackPathItem)) == 2
        assert await db.scalar(select(func.max(ResourceUsage.token_count))) == 100
        report = await db.scalar(select(Report))
        assert "LLM_MOCK" in report.report_markdown
        assert await asyncio.to_thread(Path(report.report_file_path + ".md").is_file)
        assert await asyncio.to_thread(Path(report.report_file_path + ".html").is_file)
    assert (data_root() / "runtime_logs" / str(project_id) / "run-1.jsonl").is_file()


async def test_schema_exhaustion_blocks_and_preserves_prior_data(client, tmp_path, manager, db_session_factory):
    class InvalidModel:
        async def complete(self, messages, tools, *, stage, role, context):
            content = (
                "broken-json"
                if stage == "code_analysis" and role == "code_analyst"
                else mock_output(stage, role, context)
            )
            return {"message": {"role": "assistant", "content": content}, "tokens": 3, "model": "invalid-model"}

    manager.engine_factory = lambda raw, mock: RoleEngine(raw, mock=mock, model=InvalidModel())
    project_id, _ = await start(client, tmp_path, manager, engine=manager.engine_factory)
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "failed" and detail["sandbox_id"]
    assert [s["stage_status"] for s in detail["stages"]] == ["success", "failed"]
    workers = (await client.get(f"/api/projects/{project_id}/workers")).json()["data"]["items"]
    assert workers[-1]["task_status"] == "failed" and workers[-1]["retry_count"] == 2
    assert "schema_invalid" in workers[-1]["error_message"]
    async with db_session_factory() as db:
        messages = (await db.scalars(select(ChatMessage).where(ChatMessage.message_text.contains("broken-json")))).all()
        assert len(messages) == 3
        assert await db.scalar(select(func.count()).select_from(Report)) == 0
        assert await db.scalar(select(func.count()).select_from(RuntimeLog)) > 3


async def test_ac12_stop_cancels_current_role_and_is_idempotent(
    client, tmp_path, manager, db_session_factory, monkeypatch
):
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    interrupts = []

    class WaitingEngine:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    async def interrupt(reference):
        interrupts.append(reference)

    monkeypatch.setattr(sandbox_service, "interrupt_run", interrupt)
    project_id, _ = await start(client, tmp_path, manager, engine=WaitingEngine)
    await asyncio.wait_for(entered.wait(), 5)
    before = time.monotonic()
    response = await client.post(f"/api/projects/{project_id}/stop")
    assert response.status_code == 200 and time.monotonic() - before < 5
    assert cancelled.is_set() and len(interrupts) == 1
    assert (await client.post(f"/api/projects/{project_id}/stop")).status_code == 200
    assert len(interrupts) == 1
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "stopped" and detail["sandbox_id"]
    assert len(detail["stages"]) == 1 and detail["stages"][0]["stage_status"] == "stopped"
    async with db_session_factory() as db:
        worker = await db.scalar(select(WorkerTask))
        assert worker.task_status == "failed" and worker.error_message == "任务被手动停止"
        assert worker.finished_at


@pytest.mark.parametrize(
    "timeout_key,expected", [("timeout.worker_seconds", "worker_timeout"), ("timeout.stage_seconds", "stage_timeout")]
)
async def test_dual_timeouts_block(client, tmp_path, manager, monkeypatch, timeout_key, expected):
    get_raw = config_service.get_config_raw

    async def fast_config(db):
        raw = await get_raw(db)
        raw[timeout_key] = "0.05" if timeout_key == "timeout.worker_seconds" else "1"
        return raw

    monkeypatch.setattr(config_service, "get_config_raw", fast_config)
    project_id, _ = await start(client, tmp_path, manager, engine=manager.engine_factory)
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "failed" and len(detail["stages"]) == 1
    assert expected in detail["stages"][0]["error_message"]
    worker = (await client.get(f"/api/projects/{project_id}/workers")).json()["data"]["items"][0]
    assert worker["task_status"] == "failed" and expected in worker["error_message"]


@pytest.mark.parametrize("check_name", ENV_CHECKS)
async def test_environment_failed_check_is_gate(client, tmp_path, manager, check_name):
    class FailedEnvironment:
        async def complete(self, messages, tools, **kwargs):
            result = json.loads(mock_output("environment_scan", "env_inspector", {}))
            next(item for item in result["checks"] if item["name"] == check_name).update(passed=False, detail="denied")
            return {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(result),
                },
                "tokens": 2,
                "model": "gate",
            }

    def factory(raw, mock):
        return RoleEngine(raw, mock=mock, model=FailedEnvironment())

    project_id, _ = await start(client, tmp_path, manager, engine=factory)
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "failed" and len(detail["stages"]) == 1
    workers = (await client.get(f"/api/projects/{project_id}/workers")).json()["data"]
    assert workers["total"] == 1
    assert f"{check_name}: denied" in workers["items"][0]["error_message"]


async def test_project_limits_continue_static_analysis_and_report(client, tmp_path, manager, db_session_factory):
    limitations = [
        {"name": "依赖未安装", "detail": "FastAPI 不可导入，离线不能安装"},
        {"name": "运行配置缺失", "detail": "仅有 .env.example，没有测试配置"},
        {"name": "外部服务缺失", "detail": "未提供 MySQL、Milvus 和外部 API"},
    ]
    contexts = {}

    class LimitedModel:
        async def complete(self, messages, tools, *, stage, role, context):
            contexts[(stage, role)] = context
            result = json.loads(mock_output(stage, role, context)) if role != "orchestrator" else None
            if role == "env_inspector":
                result["limitations"] = limitations
            if role == "vuln_verifier":
                for verdict in result["verdicts"]:
                    verdict.update(verify_status="verified", verify_code_text="未实际执行的代码")
            content = json.dumps(result) if result else mock_output(stage, role, context)
            return {"message": {"role": "assistant", "content": content}, "tokens": 1, "model": "controlled-limited"}

    def factory(raw, mock):
        return RoleEngine(raw, mock=False, model=LimitedModel())

    project_id, _ = await start(client, tmp_path, manager, engine=factory)
    await settled(manager, project_id)
    path = f"/api/projects/{project_id}"
    detail = (await client.get(path)).json()["data"]
    assert detail["project_status"] == "completed" and all(s["stage_status"] == "success" for s in detail["stages"])
    for stage, role in (
        ("environment_scan", "ops_assistant"),
        ("code_analysis", "code_analyst"),
        ("vulnerability_verify", "vuln_verifier"),
        ("report_generate", "report_writer"),
    ):
        assert contexts[(stage, role)]["environment_limitations"] == limitations
    messages = (await client.get(path + "/messages?message_type=warning")).json()["data"]
    logs = (await client.get(path + "/logs?level=warning")).json()["data"]
    assert messages["total"] == logs["total"] == 3
    vulnerabilities = (await client.get(path + "/vulnerabilities")).json()["data"]["items"]
    assert all(v["verify_status"] == "unverified" for v in vulnerabilities)
    report = (await client.get(path + "/report")).json()["data"]
    assert "动态验证限制" in report["report_markdown"] and "不能视为完整动态测试" in report["report_markdown"]
    assert all(item["detail"] in report["report_html"] for item in limitations)
    workers = (await client.get(path + "/workers")).json()["data"]["items"]
    stored = json.loads(next(w["result_summary"] for w in workers if w["worker_role"] == "env_inspector"))
    assert stored["limitations"] == limitations


async def test_fingerprint_change_blocks_report(client, tmp_path, manager):
    class ChangingEngine(RoleEngine):
        async def execute(self, **kwargs):
            result = await super().execute(**kwargs)
            if kwargs["stage"] == "vulnerability_verify" and kwargs["role"] == "code_analyst":
                source.write_text("print('changed')\n", "utf-8")
            return result

    source = tmp_path / "app" / "main.py"
    project_id, _ = await start(client, tmp_path, manager, engine=ChangingEngine)
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "failed" and detail["counts"]["reports"] == 0
    assert "指纹" in detail["stages"][-1]["error_message"]
    assert detail["runs"][0]["source_fingerprint"] != detail["runs"][0]["source_fingerprint_after"]


async def test_history_filters_and_restart(client, tmp_path, manager):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    response = await client.post(f"/api/projects/{project_id}/start")
    assert response.json()["data"]["run_id"] == 2
    await settled(manager, project_id)
    first = (await client.get(f"/api/projects/{project_id}/workers?run_id=1")).json()["data"]["items"]
    latest = (await client.get(f"/api/projects/{project_id}/workers")).json()["data"]["items"]
    assert len(first) == len(latest) == 10
    assert {w["run_id"] for w in first} == {1} and {w["run_id"] for w in latest} == {2}
    assert {w["id"] for w in first}.isdisjoint(w["id"] for w in latest)
    stage_id = latest[0]["stage_id"]
    assert (await client.get(f"/api/projects/{project_id}/workers?stage_id={stage_id}")).json()["data"]["total"] == 2
    assert (await client.get(f"/api/projects/{project_id}/workers?run_id=1&stage_id={stage_id}")).status_code == 404
    assert (await client.get(f"/api/projects/{project_id}/stages?run_id=99")).status_code == 404
    assert (await client.get(f"/api/projects/{project_id}/workers?status=bad")).status_code == 400
    assert (await client.get(f"/api/projects/{project_id}/workers?page_size=3")).json()["data"]["total"] == 10
    assert (await client.post(f"/api/projects/{project_id}/stop")).status_code == 409


async def test_concurrency_cap_and_same_project_mutex(client, tmp_path, manager):
    source = await setup_admin(client, tmp_path)
    first = (await create_project(client, source, "one"))["project_id"]
    second = (await create_project(client, source, "two"))["project_id"]
    await client.put("/api/system/config", json={"limit.max_concurrent_projects": 1})
    responses = await asyncio.gather(*(client.post(f"/api/projects/{first}/start") for _ in range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    blocked = await client.post(f"/api/projects/{second}/start")
    assert blocked.status_code == 429 and blocked.json()["code"] == 42901
    assert (await client.get(f"/api/projects/{second}")).json()["data"]["current_run_id"] == 0
    await client.post(f"/api/projects/{first}/stop")
    assert (await client.post(f"/api/projects/{second}/start")).status_code == 200


async def test_restart_recovery_marks_all_running_records(client, tmp_path, manager):
    project_id, _ = await start(client, tmp_path, manager, engine=manager.engine_factory)
    for _ in range(100):
        workers = (await client.get(f"/api/projects/{project_id}/workers")).json()["data"]["items"]
        if workers:
            break
        await asyncio.sleep(0.01)
    await manager.cancel(project_id)
    await manager.recover()
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "failed" and detail["sandbox_id"]
    assert detail["stages"][0]["error_message"] == "服务重启中断"
    workers = (await client.get(f"/api/projects/{project_id}/workers")).json()["data"]["items"]
    assert workers[0]["task_status"] == "failed" and workers[0]["error_message"] == "服务重启中断"


async def test_runtime_endpoints_ownership_and_auth(client, tmp_path, manager):
    source = await setup_admin(client, tmp_path)
    project_id = (await create_project(client, source))["project_id"]
    await client.post("/api/system/users", json={"username": "outsider", "password": "Outsider@12345"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        for endpoint in ("stages", "workers"):
            assert (await other.get(f"/api/projects/{project_id}/{endpoint}")).status_code == 401
        await login(other, "outsider", "Outsider@12345")
        for endpoint in ("stages", "workers"):
            assert (await other.get(f"/api/projects/{project_id}/{endpoint}")).status_code == 403
    for endpoint in ("stages", "workers"):
        response = await client.get(f"/api/projects/{project_id}/{endpoint}")
        assert response.json()["data"]["items"] == []


async def test_real_start_requires_model_configuration(client, tmp_path, manager, monkeypatch):
    source = await setup_admin(client, tmp_path)
    project_id = (await create_project(client, source))["project_id"]
    monkeypatch.setattr(get_settings(), "llm_mock", False)
    response = await client.post(f"/api/projects/{project_id}/start")
    assert response.status_code == 400 and "模型配置" in response.json()["message"]
    assert (await client.get(f"/api/projects/{project_id}")).json()["data"]["current_run_id"] == 0
