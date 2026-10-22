"""Only committed database changes are delivered to project subscribers."""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models.analysis import Vulnerability
from app.models.collab import ChatMessage, ResourceUsage, RuntimeLog
from app.models.project import Project
from app.models.report import Report
from app.models.runtime import RuntimeStage, WorkerTask

subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)


def payload(row) -> dict:
    data = {}
    for column in inspect(type(row)).columns:
        value = getattr(row, column.key)
        data[column.key] = (
            value.isoformat() if isinstance(value, datetime) else (str(value) if isinstance(value, Decimal) else value)
        )
    return data


def publish(kind: str, project_id: int, run_id: int, data: dict) -> None:
    message = {
        "type": kind,
        "project_id": project_id,
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }
    for queue in tuple(subscribers.get(project_id, ())):
        if queue.full():
            # A slow client reconnects for a complete snapshot instead of losing events silently.
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(None)
            subscribers[project_id].discard(queue)
        else:
            queue.put_nowait(message)


@event.listens_for(Session, "after_flush")
def collect_events(session, context):
    for row in session.new | session.dirty:
        if row in session.dirty and not session.is_modified(row, include_collections=False):
            continue
        if isinstance(row, Project):
            if row not in session.new and not inspect(row).attrs.project_status.history.has_changes():
                continue
            kind, project_id, run_id = "project_status", row.id, row.current_run_id
            data = {"project_id": row.id, "project_status": row.project_status, "run_id": run_id}
        elif isinstance(row, (RuntimeStage, WorkerTask, ChatMessage, RuntimeLog, ResourceUsage, Vulnerability, Report)):
            project_id, run_id = row.project_id, row.run_id
            if project_id is None:
                continue
            data = payload(row)
            if isinstance(row, RuntimeStage):
                kind = "stage_status"
                data["stage_id"] = row.id
            elif isinstance(row, WorkerTask):
                kind = "worker_status"
                data["worker_task_id"] = row.id
            elif isinstance(row, ChatMessage):
                kind = "chat_message"
            elif isinstance(row, RuntimeLog):
                kind = "runtime_log"
            elif isinstance(row, ResourceUsage):
                kind = "resource_usage"
            elif isinstance(row, Vulnerability):
                kind = "vulnerability_found"
                data["vuln_id"] = row.id
            else:
                kind = "report_ready"
                data = {"project_id": project_id, "run_id": run_id, "report_id": row.id}
        else:
            continue
        session.info.setdefault("project_events", []).append((kind, project_id, run_id, data))


@event.listens_for(Session, "after_commit")
def committed(session):
    for args in session.info.pop("project_events", []):
        publish(*args)


@event.listens_for(Session, "after_rollback")
def rolled_back(session):
    session.info.pop("project_events", None)
