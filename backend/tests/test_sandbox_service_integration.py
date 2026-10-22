import asyncio
import os
import uuid

import pytest
from docker.errors import NotFound
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.security import hash_password
from app.models.project import Project, ProjectRun
from app.models.user import User
from app.sandbox.client import get_client
from app.services import config_service, sandbox_service

pytestmark = pytest.mark.skipif(
    os.environ.get("SANDBOX_INTEGRATION") != "1",
    reason="设置 SANDBOX_INTEGRATION=1 以在真实 Docker 虚拟机上运行",
)

_REAL_START = sandbox_service.start_run
_REAL_CLEANUP = sandbox_service.cleanup_project

_TRUNCATE = """
TRUNCATE TABLE
    attack_path_items, attack_paths, vulnerabilities, worker_tasks,
    runtime_logs, chat_messages, resource_usages, reports,
    runtime_stages, project_runs, projects, user_sessions, users,
    system_configs
RESTART IDENTITY CASCADE
"""


async def test_start_run_creates_ready_sandbox(db_engine, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox_service, "start_run", _REAL_START)
    monkeypatch.setattr(sandbox_service, "cleanup_project", _REAL_CLEANUP)

    source = tmp_path / "src"
    source.mkdir()
    (source / "app.py").write_text("print('hi')\n", encoding="utf-8")

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text(_TRUNCATE))
        user = User(
            username=f"it-{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("Integration@123"),
            role="user",
            status="active",
        )
        session.add(user)
        await session.flush()

        await config_service.update_config(
            session,
            {
                "sandbox.allowed_source_root": str(tmp_path),
                "sandbox.image": "sec-eval-sandbox:latest",
            },
            actor_id=user.id,
        )

        project = Project(
            id=9_000_000_000 + int(uuid.uuid4().hex[:7], 16),
            project_name="integration-project",
            source_type="local_path",
            source_path=str(source),
            task_content="integration test",
            project_status="running",
            sandbox_type="docker",
            current_run_id=1,
            created_by=user.id,
        )
        session.add(project)
        await session.flush()
        session.add(ProjectRun(project_id=project.id, run_id=1))
        await session.commit()
        await session.refresh(project)

        await _REAL_START(session, project, 1)

        assert project.sandbox_id
        run = await session.get(ProjectRun, (project.id, 1))
        assert run is not None and run.source_fingerprint

        client = await asyncio.to_thread(get_client)
        try:
            container = await asyncio.to_thread(client.containers.get, project.sandbox_id)
            read = await asyncio.to_thread(
                container.exec_run, ["sh", "-lc", "cat /src/app.py"]
            )
            assert read.exit_code == 0
            assert b"print('hi')" in read.output

            first_id = project.sandbox_id
            session.add(ProjectRun(project_id=project.id, run_id=2))
            project.current_run_id = 2
            await session.commit()
            await session.refresh(project)
            await _REAL_START(session, project, 2)
            assert project.sandbox_id and project.sandbox_id != first_id

            with pytest.raises(NotFound):
                await asyncio.to_thread(client.containers.get, first_id)
        finally:
            await asyncio.to_thread(client.close)
            await _REAL_CLEANUP(project)
