from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import SandboxError
from app.main import app
from app.models.project import ProjectRun
from app.services import project_service
from tests.conftest import init_admin, login


async def setup_admin(client: AsyncClient, tmp_path: Path) -> Path:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")
    response = await client.put(
        "/api/system/config",
        json={"sandbox.allowed_source_root": str(tmp_path)},
    )
    assert response.status_code == 200, response.text
    source = tmp_path / "app"
    source.mkdir()
    (source / "main.py").write_text("print('ok')\n", encoding="utf-8")
    return source


async def create_project(
    client: AsyncClient, source: Path, name: str = "demo"
) -> dict:
    response = await client.post(
        "/api/projects",
        json={
            "project_name": name,
            "source_type": "local_path",
            "source_path": str(source),
            "task_content": "检查示例应用的注入类漏洞",
            "sandbox_type": "docker",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_create_list_and_detail(client: AsyncClient, tmp_path: Path) -> None:
    source = await setup_admin(client, tmp_path)
    created = await create_project(client, source)
    project_id = created["project_id"]
    assert created["project_status"] == "created"

    listing = await client.get("/api/projects")
    assert listing.status_code == 200
    data = listing.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["project_name"] == "demo"

    filtered = await client.get("/api/projects?status=created&keyword=demo")
    assert filtered.json()["data"]["total"] == 1
    empty = await client.get("/api/projects?status=running")
    assert empty.json()["data"]["total"] == 0

    detail = await client.get(f"/api/projects/{project_id}")
    assert detail.status_code == 200
    body = detail.json()["data"]
    assert body["current_run_id"] == 0
    assert body["runs"] == []
    assert body["stages"] == []
    assert body["counts"] == {"vulnerabilities": 0, "attack_paths": 0, "reports": 0}
    assert body["report_status"] == "none"

    missing_run = await client.get(f"/api/projects/{project_id}?run_id=99")
    assert missing_run.status_code == 404


async def test_duplicate_name(client: AsyncClient, tmp_path: Path) -> None:
    source = await setup_admin(client, tmp_path)
    await create_project(client, source, name="same")
    response = await client.post(
        "/api/projects",
        json={
            "project_name": "same",
            "source_type": "local_path",
            "source_path": str(source),
            "task_content": "duplicate",
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40901


async def test_path_outside_whitelist(client: AsyncClient, tmp_path: Path) -> None:
    await setup_admin(client, tmp_path)
    outside = tmp_path.parent
    response = await client.post(
        "/api/projects",
        json={
            "project_name": "outside",
            "source_type": "local_path",
            "source_path": str(outside),
            "task_content": "should fail",
        },
    )
    assert response.status_code == 400
    assert "白名单" in response.json()["message"]


async def test_multi_root_whitelist(client: AsyncClient, tmp_path: Path) -> None:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")

    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_c = tmp_path / "root_c"
    sources = {}
    for name, root in (("a", root_a), ("b", root_b), ("c", root_c)):
        source = root / "app"
        source.mkdir(parents=True)
        (source / "main.py").write_text("print('ok')\n", encoding="utf-8")
        sources[name] = source

    updated = await client.put(
        "/api/system/config",
        json={"sandbox.allowed_source_root": f"{root_a},{root_b}"},
    )
    assert updated.status_code == 200

    allowed_a = await create_project(client, sources["a"], name="from-a")
    allowed_b = await create_project(client, sources["b"], name="from-b")
    assert allowed_a["project_id"] and allowed_b["project_id"]

    blocked = await client.post(
        "/api/projects",
        json={
            "project_name": "from-c",
            "source_type": "local_path",
            "source_path": str(sources["c"]),
            "task_content": "should fail",
        },
    )
    assert blocked.status_code == 400


async def test_git_repo_validation(client: AsyncClient, tmp_path: Path) -> None:
    await setup_admin(client, tmp_path)

    no_hosts = await client.post(
        "/api/projects",
        json={
            "project_name": "git",
            "source_type": "git_repo",
            "source_path": "https://github.com/acme/repo.git",
            "task_content": "git repo",
        },
    )
    assert no_hosts.status_code == 400

    await client.put("/api/system/config", json={"git.allowed_hosts": "github.com"})

    allowed = await client.post(
        "/api/projects",
        json={
            "project_name": "git",
            "source_type": "git_repo",
            "source_path": "https://github.com/acme/repo.git",
            "task_content": "git repo",
        },
    )
    assert allowed.status_code == 200, allowed.text

    blocked = await client.post(
        "/api/projects",
        json={
            "project_name": "evil",
            "source_type": "git_repo",
            "source_path": "https://evil.example.com/acme/repo.git",
            "task_content": "blocked",
        },
    )
    assert blocked.status_code == 400

    local_scheme = await client.post(
        "/api/projects",
        json={
            "project_name": "file",
            "source_type": "git_repo",
            "source_path": "file:///tmp/repo",
            "task_content": "blocked",
        },
    )
    assert local_scheme.status_code == 400


async def test_permissions(client: AsyncClient, tmp_path: Path) -> None:
    source = await setup_admin(client, tmp_path)
    project = await create_project(client, source)
    project_id = project["project_id"]

    created = await client.post(
        "/api/system/users", json={"username": "viewer", "password": "Viewer@12345"}
    )
    assert created.status_code == 200

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as viewer:
        await login(viewer, "viewer", "Viewer@12345")
        listing = await viewer.get("/api/projects")
        assert listing.json()["data"]["total"] == 0

        detail = await viewer.get(f"/api/projects/{project_id}")
        assert detail.status_code == 403

        start = await viewer.post(f"/api/projects/{project_id}/start")
        assert start.status_code == 403

        delete = await viewer.delete(f"/api/projects/{project_id}")
        assert delete.status_code == 403

    admin_listing = await client.get("/api/projects")
    assert admin_listing.json()["data"]["total"] == 1


async def test_start_stop_and_run_id(client: AsyncClient, tmp_path: Path) -> None:
    source = await setup_admin(client, tmp_path)
    project = await create_project(client, source)
    project_id = project["project_id"]

    stop_created = await client.post(f"/api/projects/{project_id}/stop")
    assert stop_created.status_code == 409

    first = await client.post(f"/api/projects/{project_id}/start")
    assert first.status_code == 200, first.text
    assert first.json()["data"]["run_id"] == 1

    duplicate = await client.post(f"/api/projects/{project_id}/start")
    assert duplicate.status_code == 409
    assert duplicate.json()["message"] == "任务执行中，不能重复启动"

    detail = await client.get(f"/api/projects/{project_id}")
    body = detail.json()["data"]
    assert body["project_status"] == "running"
    assert body["current_run_id"] == 1
    assert len(body["runs"]) == 1

    stopped = await client.post(f"/api/projects/{project_id}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["data"]["project_status"] == "stopped"

    stopped_again = await client.post(f"/api/projects/{project_id}/stop")
    assert stopped_again.status_code == 200

    second = await client.post(f"/api/projects/{project_id}/start")
    assert second.status_code == 200
    assert second.json()["data"]["run_id"] == 2

    detail = await client.get(f"/api/projects/{project_id}")
    assert len(detail.json()["data"]["runs"]) == 2


async def test_delete_running_blocked(client: AsyncClient, tmp_path: Path) -> None:
    source = await setup_admin(client, tmp_path)
    project = await create_project(client, source)
    project_id = project["project_id"]
    await client.post(f"/api/projects/{project_id}/start")

    response = await client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 409


async def test_delete_removes_dirs_and_rows(
    client: AsyncClient,
    tmp_path: Path,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await setup_admin(client, tmp_path)
    project = await create_project(client, source)
    project_id = project["project_id"]
    await client.post(f"/api/projects/{project_id}/start")
    await client.post(f"/api/projects/{project_id}/stop")

    workspace = project_service.data_root() / "workspace" / str(project_id) / "1"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "note.txt").write_text("evidence", encoding="utf-8")

    response = await client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 200
    assert response.json()["data"] == {"deleted": True, "dirs_cleaned": True}

    assert not workspace.exists()
    assert (await client.get(f"/api/projects/{project_id}")).status_code == 404

    async with db_session_factory() as session:
        runs = await session.scalar(
            select(func.count()).select_from(ProjectRun).where(ProjectRun.project_id == project_id)
        )
    assert runs == 0


async def test_cleanup_failure_marks_pending_and_retry(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await setup_admin(client, tmp_path)
    project = await create_project(client, source)
    project_id = project["project_id"]

    original_remove = project_service._remove_dir
    state = {"fail": True}

    def conditional_remove(path: Path) -> None:
        if state["fail"]:
            raise OSError("simulated cleanup failure")
        original_remove(path)

    monkeypatch.setattr(project_service, "_remove_dir", conditional_remove)
    response = await client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 500
    body = response.json()
    assert body["data"] == {"deleted": False, "dirs_cleaned": False}

    detail = await client.get(f"/api/projects/{project_id}")
    assert detail.json()["data"]["cleanup_pending"] is True

    state["fail"] = False
    retry = await client.delete(f"/api/projects/{project_id}")
    assert retry.status_code == 200
    assert retry.json()["data"]["deleted"] is True


async def test_start_failure_marks_project_failed(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await setup_admin(client, tmp_path)
    project = await create_project(client, source)
    project_id = project["project_id"]

    async def failing_start(db, target, run_id: int, *, raw=None) -> None:
        raise SandboxError("simulated docker failure")

    monkeypatch.setattr(project_service.sandbox_service, "start_run", failing_start)

    response = await client.post(f"/api/projects/{project_id}/start")
    assert response.status_code == 500
    assert response.json()["code"] == 50002

    detail = await client.get(f"/api/projects/{project_id}")
    body = detail.json()["data"]
    assert body["project_status"] == "failed"
    assert body["current_run_id"] == 1


async def test_delete_user_with_projects_conflicts(
    client: AsyncClient, tmp_path: Path
) -> None:
    source = await setup_admin(client, tmp_path)
    created = await client.post(
        "/api/system/users", json={"username": "owner", "password": "Owner@12345"}
    )
    owner_id = created.json()["data"]["user_id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as owner:
        await login(owner, "owner", "Owner@12345")
        project = await create_project(owner, source, name="owner-project")

    blocked = await client.delete(f"/api/system/users/{owner_id}")
    assert blocked.status_code == 409
    assert "项目" in blocked.json()["message"]

    await client.delete(f"/api/projects/{project['project_id']}")
    allowed = await client.delete(f"/api/system/users/{owner_id}")
    assert allowed.status_code == 200
