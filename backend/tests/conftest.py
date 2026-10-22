# ruff: noqa: E402 - 环境变量必须在导入应用模块前设置
import asyncio
import atexit
import base64
import os
import shutil
import tempfile
from pathlib import Path

_TEST_DATA_ROOT = tempfile.mkdtemp(prefix="sec-eval-test-data-")
atexit.register(shutil.rmtree, _TEST_DATA_ROOT, ignore_errors=True)

os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("JWT_SECRET", "test-" + "x" * 60)
os.environ.setdefault("DATA_ENCRYPTION_KEY", base64.b64encode(b"0" * 32).decode())
os.environ["DATA_ROOT"] = _TEST_DATA_ROOT

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import Base, get_db
from app.main import app
from app.models.project import ProjectRun
from app.services import auth_service, monitoring, project_service, sandbox_service, source_service
from app.services.run_manager import RunManager

TEST_DB = f"sec_eval_test_{os.getpid()}"
_url = make_url(get_settings().database_url)
TEST_URL = _url.set(database=TEST_DB).render_as_string(hide_password=False)
_ADMIN_URL = _url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)

_TRUNCATE = """
TRUNCATE TABLE
    attack_path_items, attack_paths, vulnerabilities, worker_tasks,
    runtime_logs, chat_messages, resource_usages, reports,
    runtime_stages, project_runs, projects, user_sessions, users,
    system_configs
RESTART IDENTITY CASCADE
"""


async def _prepare_database() -> None:
    conn = await asyncpg.connect(_ADMIN_URL)
    try:
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    except asyncpg.DuplicateDatabaseError:
        pass
    finally:
        await conn.close()

    engine = create_async_engine(TEST_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def _drop_test_database() -> None:
    async def drop():
        conn = await asyncpg.connect(_ADMIN_URL)
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        finally:
            await conn.close()

    asyncio.run(drop())


atexit.register(_drop_test_database)


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


class HoldingEngine:
    def __init__(self, *args, **kwargs):
        pass

    async def execute(self, **kwargs):
        await asyncio.Event().wait()


@pytest_asyncio.fixture
async def manager(db_session_factory, monkeypatch):
    manager = RunManager(db_session_factory, engine_factory=HoldingEngine)
    monkeypatch.setattr(project_service, "run_manager", manager)
    monkeypatch.setattr(get_settings(), "llm_mock", True)
    try:
        yield manager
    finally:
        await manager.shutdown()


@pytest_asyncio.fixture
async def client(db_engine, db_session_factory, manager) -> AsyncClient:
    async with db_engine.begin() as connection:
        await connection.execute(text(_TRUNCATE))
    auth_service._failures.clear()

    async def override_get_db():
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fake_sandbox(monkeypatch):
    """测试默认不接触真实 Docker；需要验证失败路径的用例可再次覆盖。"""

    async def fake_start(db, project, run_id: int, *, raw=None) -> None:
        await db.refresh(project)
        project.sandbox_id = f"fake-{project.id}-{run_id}"
        run = await db.get(ProjectRun, (project.id, run_id))
        if run is not None:
            run.source_fingerprint = source_service.compute_fingerprint(Path(project.source_path))
        await db.commit()

    async def fake_stop(db, project) -> None:
        return None

    async def fake_cleanup(project) -> None:
        return None

    async def fake_reference(reference) -> None:
        return None

    monkeypatch.setattr(sandbox_service, "start_run", fake_start)
    monkeypatch.setattr(sandbox_service, "interrupt_run", fake_reference)
    monkeypatch.setattr(sandbox_service, "destroy_run", fake_reference)
    monkeypatch.setattr(sandbox_service, "stop_run", fake_stop)
    monkeypatch.setattr(sandbox_service, "cleanup_project", fake_cleanup)
    monkeypatch.setattr(monitoring, "read_stats", lambda reference: {"cpu_usage": 12.5, "memory_usage": 64})


async def init_admin(http: AsyncClient, username: str = "admin", password: str = "Admin@12345") -> dict:
    response = await http.post(
        "/api/system/init",
        json={"username": username, "password": password, "create_demo_user": False},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def login(http: AsyncClient, username: str, password: str) -> dict:
    response = await http.post("/api/system/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["data"]


# 在收集阶段准备测试库，避免与 pytest-asyncio 的事件循环冲突
asyncio.run(_prepare_database())
