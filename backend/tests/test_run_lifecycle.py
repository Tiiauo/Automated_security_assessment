import asyncio

from app.agents.engine import RoleEngine
from app.agents.mock import mock_output
from app.core.errors import SandboxError
from app.services import sandbox_service
from app.services.run_manager import RunManager
from tests.test_projects_api import create_project, setup_admin
from tests.test_run_manager import settled, start


async def test_cancel_before_task_first_turn_releases_handle():
    manager = RunManager()
    manager.launch(999999, 1, {}, mock=True)
    await manager.cancel(999999)
    assert not manager.handles


async def test_stop_during_preparation_prevents_late_launch(client, tmp_path, manager, monkeypatch):
    source = await setup_admin(client, tmp_path)
    project_id = (await create_project(client, source))["project_id"]
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_start(db, project, run_id, *, raw=None):
        entered.set()
        await release.wait()

    monkeypatch.setattr(sandbox_service, "start_run", delayed_start)
    starting = asyncio.create_task(client.post(f"/api/projects/{project_id}/start"))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert (await client.post(f"/api/projects/{project_id}/stop")).status_code == 200
        assert (await client.post(f"/api/projects/{project_id}/start")).status_code == 409
        assert (await client.delete(f"/api/projects/{project_id}")).status_code == 409
    finally:
        release.set()
    assert (await starting).status_code == 409
    assert project_id not in manager.handles
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "stopped" and detail["stages"] == []


async def test_done_ops_failure_keeps_container(client, tmp_path, manager, monkeypatch):
    destroyed = []

    async def destroy(reference):
        destroyed.append(reference)

    class FailedArchiveModel:
        async def complete(self, messages, tools, *, stage, role, context):
            output = mock_output(stage, role, context)
            if stage == "done" and role == "ops_assistant":
                output = (
                    '{"summary":"归档失败","actions":[{"action":"archive","status":"failed","detail":"disk full"}]}'
                )
            return {"message": {"role": "assistant", "content": output}, "tokens": 1, "model": "ops-fail"}

    monkeypatch.setattr(sandbox_service, "destroy_run", destroy)
    project_id, _ = await start(
        client, tmp_path, manager, engine=lambda raw, mock: RoleEngine(raw, mock=mock, model=FailedArchiveModel())
    )
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "failed" and detail["sandbox_id"]
    assert detail["stages"][-1]["stage_name"] == "done" and detail["stages"][-1]["stage_status"] == "failed"
    assert destroyed == []


async def test_destroy_failure_never_completes_project(client, tmp_path, manager, monkeypatch):
    async def destroy(reference):
        raise SandboxError("destroy exhausted retries")

    monkeypatch.setattr(sandbox_service, "destroy_run", destroy)
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "failed" and detail["sandbox_id"]
    assert "destroy exhausted" in detail["stages"][-1]["error_message"]
    workers = (await client.get(f"/api/projects/{project_id}/workers")).json()["data"]
    assert workers["total"] == 10 and all(w["task_status"] == "success" for w in workers["items"])
