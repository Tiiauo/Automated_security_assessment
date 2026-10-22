import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.agents.engine import RoleEngine
from app.api import monitoring as api
from app.main import app
from app.models.collab import ChatMessage, ResourceUsage, RuntimeLog
from app.services import monitoring
from app.services.events import publish, subscribers
from tests.test_projects_api import create_project, setup_admin
from tests.test_run_manager import settled, start


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()

    async def receive(self):
        return await asyncio.wait_for(self.outgoing.get(), 4)

    async def json(self):
        message = await self.receive()
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])


@asynccontextmanager
async def connect(client, project_id, *, query="", authenticated=True, origin=None):
    socket = Socket()
    cookie = "; ".join(f"{key}={value}" for key, value in client.cookies.items()) if authenticated else ""
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": f"/api/projects/{project_id}/stream",
        "raw_path": b"/",
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(b"cookie", cookie.encode())],
        "client": ("test", 1234),
        "server": ("test", 80),
        "subprotocols": [],
        "state": {},
    }
    if origin:
        scope["headers"].extend([(b"origin", origin.encode()), (b"host", b"test")])
    await socket.incoming.put({"type": "websocket.connect"})
    task = asyncio.create_task(app(scope, socket.incoming.get, socket.outgoing.put))
    assert (await socket.receive())["type"] == "websocket.accept"
    try:
        yield socket
    finally:
        await socket.incoming.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(task, 4)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_monitor_http_filters_and_stats(client, tmp_path, manager):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    for name in ("messages", "logs", "resources"):
        result = await client.get(f"/api/projects/{project_id}/{name}?page_size=2")
        assert result.status_code == 200, result.text
        body = result.json()["data"]
        assert len(body["items"]) == 2 and body["total"] >= 2
        assert all(row["run_id"] == 1 for row in body["items"])
        assert (await client.get(f"/api/projects/{project_id}/{name}?run_id=99")).status_code == 404
    result = await client.get(f"/api/projects/{project_id}/messages?worker_role=env_inspector&message_type=result")
    assert all(row["worker_role"] == "env_inspector" for row in result.json()["data"]["items"])
    assert (await client.get(f"/api/projects/{project_id}/resources?start_time=2026-10-22T00:00:00")).status_code == 400
    assert (await client.get(f"/api/projects/{project_id}/logs?level=invalid")).status_code == 400
    assert (await client.get("/api/system/resources")).json()["data"]["token_count"] == 100
    assert (await client.get("/api/system/logs?keyword=模型实际版本")).json()["data"]["total"] == 10


async def test_events_only_publish_committed_rows(client, tmp_path, manager, db_session_factory):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    queue = asyncio.Queue(maxsize=20)
    subscribers[project_id].add(queue)
    try:
        async with db_session_factory() as db:
            row = ChatMessage(
                project_id=project_id,
                run_id=1,
                worker_role="orchestrator",
                message_type="info",
                message_text="committed",
            )
            db.add(row)
            await db.flush()
            assert queue.empty()
            await db.commit()
            event = queue.get_nowait()
            assert event["type"] == "chat_message" and event["data"]["id"] == row.id
            db.add(
                ChatMessage(
                    project_id=project_id,
                    run_id=1,
                    worker_role="orchestrator",
                    message_type="info",
                    message_text="rolled back",
                )
            )
            await db.flush()
            await db.rollback()
            assert queue.empty()
    finally:
        subscribers.pop(project_id, None)


async def test_socket_snapshot_increment_and_reconnect(client, tmp_path, manager, db_session_factory):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    async with connect(client, project_id) as socket:
        first = await socket.json()
        assert first["type"] == "snapshot" and len(first["data"]["workers"]) == 10
        assert sum(first["data"]["vuln_counts"].values()) == 2
        async with db_session_factory() as db:
            row = ChatMessage(
                project_id=project_id,
                run_id=1,
                worker_role="orchestrator",
                message_type="info",
                message_text="after snapshot",
            )
            db.add(row)
            await db.commit()
            message_id = row.id
        event = await socket.json()
        assert event["type"] == "chat_message" and event["data"]["id"] == message_id
    async with connect(client, project_id) as socket:
        frame = await socket.json()
        assert [row["id"] for row in frame["data"]["recent_messages"]].count(message_id) == 1
    assert project_id not in subscribers


async def test_socket_close_codes_and_revocation(client, tmp_path, manager):
    source = await setup_admin(client, tmp_path)
    project_id = (await create_project(client, source))["project_id"]
    async with connect(client, project_id, authenticated=False) as socket:
        assert (await socket.receive())["code"] == 4401
    async with connect(client, project_id, origin="https://untrusted.invalid") as socket:
        assert (await socket.receive())["code"] == 4403
    async with connect(client, 999999) as socket:
        assert (await socket.receive())["code"] == 4404
    async with connect(client, project_id, query="run_id=99") as socket:
        assert (await socket.receive())["code"] == 4404
    async with connect(client, project_id) as socket:
        assert (await socket.json())["type"] == "snapshot"
        assert (await client.post("/api/system/logout")).status_code == 200
        assert (await socket.receive())["code"] == 4401


async def test_socket_heartbeat_timeout(client, tmp_path, monkeypatch):
    source = await setup_admin(client, tmp_path)
    project_id = (await create_project(client, source))["project_id"]
    monkeypatch.setattr(api, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(api, "PONG_SECONDS", 0.01)
    async with connect(client, project_id) as socket:
        await socket.json()
        assert (await socket.json())["type"] == "ping"
        assert (await socket.json())["type"] == "ping"
        assert (await socket.receive())["code"] == 4408


async def test_samples_do_not_lose_tokens(client, tmp_path, manager, db_session_factory):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)

    async def write(tokens=0, stats=None):
        async with db_session_factory() as db:
            await monitoring.record_usage(db, project_id, 1, tokens=tokens, stats=stats)
            await db.commit()

    await asyncio.gather(write(tokens=7), write(stats={"cpu_usage": 23.5, "memory_usage": 128}), write(tokens=11))
    async with db_session_factory() as db:
        last = await db.scalar(
            select(ResourceUsage)
            .where(ResourceUsage.project_id == project_id)
            .order_by(ResourceUsage.id.desc())
            .limit(1)
        )
        assert last.token_count == 118 and last.memory_usage == 128


async def test_retention_cleanup(client, tmp_path, manager, db_session_factory):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    async with db_session_factory() as db:
        db.add(RuntimeLog(log_level="info", log_content="expired", created_at=datetime.now(UTC) - timedelta(days=31)))
        await db.commit()
    task = asyncio.create_task(monitoring.prune(db_session_factory))
    try:
        for _ in range(40):
            async with db_session_factory() as db:
                row = await db.scalar(select(RuntimeLog).where(RuntimeLog.log_content == "expired"))
            if row is None:
                break
            await asyncio.sleep(0.05)
        assert row is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_live_start_delivers_all_eight_event_types(client, tmp_path, manager):
    source = await setup_admin(client, tmp_path)
    project_id = (await create_project(client, source))["project_id"]
    manager.engine_factory = RoleEngine
    expected = {
        "project_status",
        "stage_status",
        "worker_status",
        "chat_message",
        "runtime_log",
        "resource_usage",
        "vulnerability_found",
        "report_ready",
    }
    async with connect(client, project_id) as socket:
        assert (await socket.json())["run_id"] == 0
        assert (await client.post(f"/api/projects/{project_id}/start")).status_code == 200
        await settled(manager, project_id)
        seen = set()
        for _ in range(150):
            frame = await socket.json()
            assert frame["run_id"] == 1
            seen.add(frame["type"])
            if expected <= seen:
                break
        assert expected <= seen


def test_slow_subscriber_requires_snapshot():
    queue = asyncio.Queue(maxsize=1)
    subscribers[999999].add(queue)
    try:
        publish("runtime_log", 999999, 1, {})
        publish("runtime_log", 999999, 1, {})
        assert queue.get_nowait() is None
    finally:
        subscribers.pop(999999, None)
