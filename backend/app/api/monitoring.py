import asyncio
from datetime import UTC, datetime
from time import monotonic
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import AuthContext, get_auth_context, require_admin
from app.core.errors import AppError
from app.models.collab import ChatMessage, ResourceUsage, RuntimeLog
from app.schemas.common import ok
from app.services import monitoring, project_service, runtime_query
from app.services.events import subscribers

router = APIRouter(prefix="/api", tags=["monitoring"])
Run = Annotated[int | None, Query(ge=1)]
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=200)]
Level = Literal["debug", "info", "warning", "error"]
Role = Literal["orchestrator", "env_inspector", "code_analyst", "vuln_verifier", "report_writer", "ops_assistant"]
Db = Annotated[AsyncSession, Depends(get_db)]
Auth = Annotated[AuthContext, Depends(get_auth_context)]
Admin = Annotated[AuthContext, Depends(require_admin)]
HEARTBEAT_SECONDS = 30
PONG_SECONDS = 10


@router.get("/projects/{project_id}/messages")
async def messages(
    project_id: int,
    db: Db,
    ctx: Auth,
    run_id: Run = None,
    worker_role: Role | None = None,
    message_type: Literal["info", "tool_call", "result", "warning", "error"] | None = None,
    page: Page = 1,
    page_size: Size = 20,
):
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    value = await runtime_query.selected_run(db, project, run_id)
    conditions = [ChatMessage.project_id == project_id, ChatMessage.run_id == value]
    if worker_role:
        conditions.append(ChatMessage.worker_role == worker_role)
    if message_type:
        conditions.append(ChatMessage.message_type == message_type)
    return ok(await monitoring.page_rows(db, ChatMessage, conditions, page, page_size, newest=True))


@router.get("/projects/{project_id}/logs")
async def logs(
    project_id: int,
    db: Db,
    ctx: Auth,
    run_id: Run = None,
    level: Level | None = None,
    stage_id: int | None = Query(None, ge=1),
    worker_task_id: int | None = Query(None, ge=1),
    page: Page = 1,
    page_size: Size = 20,
):
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    value = await runtime_query.selected_run(db, project, run_id)
    conditions = [RuntimeLog.project_id == project_id, RuntimeLog.run_id == value]
    for column, argument in (
        (RuntimeLog.log_level, level),
        (RuntimeLog.stage_id, stage_id),
        (RuntimeLog.worker_task_id, worker_task_id),
    ):
        if argument is not None:
            conditions.append(column == argument)
    return ok(await monitoring.page_rows(db, RuntimeLog, conditions, page, page_size, newest=True))


@router.get("/projects/{project_id}/resources")
async def resources(
    project_id: int,
    db: Db,
    ctx: Auth,
    run_id: Run = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: Page = 1,
    page_size: Size = 20,
):
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    value = await runtime_query.selected_run(db, project, run_id)
    conditions = [
        ResourceUsage.project_id == project_id,
        ResourceUsage.run_id == value,
        *monitoring.time_filters(ResourceUsage, start_time, end_time),
    ]
    return ok(await monitoring.page_rows(db, ResourceUsage, conditions, page, page_size, newest=True))


@router.get("/system/resources")
async def system_resources(db: Db, ctx: Admin, start_time: datetime | None = None, end_time: datetime | None = None):
    return ok(await monitoring.system_resources(db, start_time, end_time))


@router.get("/system/logs")
async def system_logs(
    db: Db,
    ctx: Admin,
    level: Level | None = None,
    keyword: str | None = Query(None, max_length=100),
    page: Page = 1,
    page_size: Size = 20,
):
    conditions = [RuntimeLog.project_id.is_(None)]
    if level:
        conditions.append(RuntimeLog.log_level == level)
    if keyword:
        conditions.append(RuntimeLog.log_content.ilike(f"%{keyword}%"))
    return ok(await monitoring.page_rows(db, RuntimeLog, conditions, page, page_size, newest=True))


@router.websocket("/projects/{project_id}/stream")
async def stream(websocket: WebSocket, project_id: int, db: Db, run_id: Run = None):
    await websocket.accept()
    origin = websocket.headers.get("origin")
    allowed = [value.strip() for value in get_settings().cors_allow_origins.split(",") if value.strip()]
    if origin and origin.rstrip("/") not in {
        f"http://{websocket.headers.get('host')}",
        f"https://{websocket.headers.get('host')}",
        *allowed,
    }:
        await websocket.close(code=4403)
        return
    queue = asyncio.Queue(maxsize=512)
    subscribers[project_id].add(queue)
    receiver = None
    try:
        ctx = await get_auth_context(websocket, db)
        project = await project_service.get_visible_project(db, project_id, ctx.user)
        selected = await runtime_query.selected_run(db, project, run_id)
        await send_snapshot(websocket, db, project, run_id)
        await db.rollback()
        pong = asyncio.Event()

        async def receive():
            while True:
                message = await websocket.receive_json()
                if isinstance(message, dict) and message.get("type") == "pong":
                    pong.set()

        receiver = asyncio.create_task(receive())
        next_ping, deadline, missed, checked = monotonic() + HEARTBEAT_SECONDS, None, 0, monotonic()
        while True:
            if receiver.done():
                await receiver
            now = monotonic()
            if now - checked >= 1:
                db.expire_all()
                ctx = await get_auth_context(websocket, db)
                await project_service.get_visible_project(db, project_id, ctx.user)
                await db.rollback()
                checked = now
            if deadline is not None:
                if pong.is_set():
                    missed, deadline = 0, None
                elif now >= deadline:
                    missed, deadline = missed + 1, None
                    if missed >= 2:
                        await websocket.close(code=4408)
                        return
            if now >= next_ping:
                pong.clear()
                await websocket.send_json({"type": "ping", "timestamp": datetime.now(UTC).isoformat()})
                deadline, next_ping = now + PONG_SECONDS, now + HEARTBEAT_SECONDS
            try:
                message = await asyncio.wait_for(queue.get(), timeout=0.1)
            except TimeoutError:
                continue
            if message is None:
                await websocket.close(code=1013, reason="请重连以同步快照")
                return
            batch = [message]
            if message["type"] == "runtime_log":
                await asyncio.sleep(0.1)
                while not queue.empty():
                    queued = queue.get_nowait()
                    if queued is None:
                        await websocket.close(code=1013)
                        return
                    batch.append(queued)
            for message in batch:
                if run_id is None and message["type"] == "project_status" and message["run_id"] != selected:
                    ctx = await get_auth_context(websocket, db)
                    project = await project_service.get_visible_project(db, project_id, ctx.user)
                    selected = project.current_run_id
                    await send_snapshot(websocket, db, project, None)
                    await db.rollback()
                if message["run_id"] == selected:
                    if message["type"] == "vulnerability_found":
                        message = {
                            **message,
                            "data": {
                                **message["data"],
                                "vuln_counts": (await monitoring.counts(db, project_id, selected))["risk_levels"],
                            },
                        }
                        await db.rollback()
                    await websocket.send_json(message)
    except AppError as exc:
        await websocket.close(code={401: 4401, 403: 4403, 404: 4404}.get(exc.http_status, 4400))
    except WebSocketDisconnect:
        pass
    except (ValueError, TypeError):
        await websocket.close(code=4400)
    finally:
        subscribers[project_id].discard(queue)
        if not subscribers[project_id]:
            subscribers.pop(project_id, None)
        if receiver:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)


async def send_snapshot(websocket, db, project, run_id):
    data = await monitoring.snapshot(db, project, run_id)
    await websocket.send_json(
        {
            "type": "snapshot",
            "project_id": project.id,
            "run_id": data["selected_run_id"],
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }
    )
