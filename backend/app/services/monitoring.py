import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.models.analysis import Vulnerability
from app.models.collab import ChatMessage, ResourceUsage, RuntimeLog
from app.models.project import Project
from app.sandbox import containers
from app.sandbox.client import get_client
from app.services import config_service, runtime_query
from app.services.events import payload

logger = logging.getLogger(__name__)


async def page_rows(db, model, conditions, page, page_size, *, newest=False):
    total = await db.scalar(select(func.count()).select_from(model).where(*conditions))
    rows = (
        await db.scalars(
            select(model)
            .where(*conditions)
            .order_by(model.id.desc() if newest else model.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {"items": [payload(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def time_filters(model, start_time, end_time):
    from app.core.errors import BadRequest

    if any(value is not None and value.utcoffset() is None for value in (start_time, end_time)):
        raise BadRequest("时间参数必须包含时区")
    if start_time and end_time and start_time > end_time:
        raise BadRequest("开始时间不得晚于结束时间")
    return ([model.recorded_at >= start_time] if start_time else []) + (
        [model.recorded_at <= end_time] if end_time else []
    )


async def counts(db, project_id, run_id):
    rows = (
        await db.execute(
            select(Vulnerability.risk_level, Vulnerability.verify_status, func.count())
            .where(Vulnerability.project_id == project_id, Vulnerability.run_id == run_id)
            .group_by(Vulnerability.risk_level, Vulnerability.verify_status)
        )
    ).all()
    risks = dict.fromkeys(("critical", "high", "medium", "low", "info"), 0)
    statuses = dict.fromkeys(("pending", "verified", "unverified", "false_positive"), 0)
    for risk, status, count in rows:
        risks[risk] += count
        statuses[status] += count
    return {"risk_levels": risks, "verify_statuses": statuses}


async def snapshot(db, project, run_id):
    value = await runtime_query.selected_run(db, project, run_id)
    stages = await runtime_query.stages(db, project, run_id, 1, 100)
    workers = await runtime_query.workers(db, project, run_id, None, None, 1, 100)
    messages = await page_rows(
        db, ChatMessage, [ChatMessage.project_id == project.id, ChatMessage.run_id == value], 1, 50, newest=True
    )
    logs = await page_rows(
        db, RuntimeLog, [RuntimeLog.project_id == project.id, RuntimeLog.run_id == value], 1, 100, newest=True
    )
    latest = await db.scalar(
        select(ResourceUsage)
        .where(ResourceUsage.project_id == project.id, ResourceUsage.run_id == value)
        .order_by(ResourceUsage.id.desc())
        .limit(1)
    )
    return {
        "project_status": project.project_status,
        "current_run_id": project.current_run_id,
        "selected_run_id": value,
        "stages": stages["items"],
        "workers": workers["items"],
        "recent_messages": list(reversed(messages["items"])),
        "recent_logs": list(reversed(logs["items"])),
        "latest_resource": payload(latest) if latest else None,
        "vuln_counts": (await counts(db, project.id, value))["risk_levels"],
    }


def read_stats(reference):
    client = get_client()
    try:
        return containers.container_stats(containers.get_container(client, reference))
    finally:
        client.close()


async def record_usage(db, project_id, run_id, *, tokens=0, stats=None):
    # Serialize token increments and periodic samples on the same project row.
    project = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None or project.current_run_id != run_id:
        return
    last = await db.scalar(
        select(ResourceUsage)
        .where(ResourceUsage.project_id == project_id, ResourceUsage.run_id == run_id)
        .order_by(ResourceUsage.id.desc())
        .limit(1)
    )
    values = stats or {"cpu_usage": last.cpu_usage if last else 0, "memory_usage": last.memory_usage if last else 0}
    db.add(
        ResourceUsage(
            project_id=project_id,
            run_id=run_id,
            cpu_usage=values["cpu_usage"],
            memory_usage=values["memory_usage"],
            token_count=(last.token_count if last else 0) + tokens,
        )
    )


async def sample_project(sessions, project_id, run_id, interval):
    while True:
        try:
            async with sessions() as db:
                project = await db.get(Project, project_id)
                if project is None or project.project_status != "running" or project.current_run_id != run_id:
                    return
                reference = project.sandbox_id
            if reference:
                stats = await asyncio.to_thread(read_stats, reference)
                async with sessions() as db:
                    await record_usage(db, project_id, run_id, stats=stats)
                    await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("resource sampling failed: project=%s run=%s", project_id, run_id, exc_info=True)
        await asyncio.sleep(interval)


async def prune(sessions):
    while True:
        try:
            async with sessions() as db:
                raw = await config_service.get_config_raw(db)
                now = datetime.now(UTC)
                await db.execute(
                    delete(RuntimeLog).where(
                        RuntimeLog.created_at < now - timedelta(days=int(raw["retention.log_days"]))
                    )
                )
                await db.execute(
                    delete(ResourceUsage).where(
                        ResourceUsage.recorded_at < now - timedelta(days=int(raw["retention.resource_days"]))
                    )
                )
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("monitor retention cleanup failed")
        await asyncio.sleep(3600)


async def system_resources(db, start_time, end_time):
    conditions = time_filters(ResourceUsage, start_time, end_time)
    latest = select(func.max(ResourceUsage.id)).where(*conditions).group_by(ResourceUsage.project_id)
    rows = (
        await db.execute(
            select(Project, ResourceUsage)
            .join(ResourceUsage, ResourceUsage.project_id == Project.id)
            .where(ResourceUsage.id.in_(latest), ResourceUsage.run_id == Project.current_run_id)
        )
    ).all()
    return {
        "running_projects": await db.scalar(
            select(func.count()).select_from(Project).where(Project.project_status == "running")
        ),
        "cpu_usage": sum(float(row.cpu_usage) for project, row in rows if project.project_status == "running"),
        "memory_usage": sum(row.memory_usage for project, row in rows if project.project_status == "running"),
        "token_count": sum(row.token_count for _, row in rows),
        "projects": [
            {
                "project_id": project.id,
                "project_name": project.project_name,
                "cpu_usage": float(row.cpu_usage) if project.project_status == "running" else 0,
                "memory_usage": row.memory_usage if project.project_status == "running" else 0,
                "token_count": row.token_count,
            }
            for project, row in rows
        ],
    }
