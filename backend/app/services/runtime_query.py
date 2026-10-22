from sqlalchemy import func, select

from app.core.errors import NotFound
from app.models.project import ProjectRun
from app.models.runtime import RuntimeStage, WorkerTask


async def selected_run(db, project, run_id: int | None) -> int:
    value = project.current_run_id if run_id is None else run_id
    if value == 0 and run_id is None:
        return 0
    if await db.get(ProjectRun, (project.id, value)) is None:
        raise NotFound("指定的执行轮次不存在")
    return value


async def stages(db, project, run_id, page, page_size):
    from app.services.project_service import _stage_payload

    value = await selected_run(db, project, run_id)
    conditions = (RuntimeStage.project_id == project.id, RuntimeStage.run_id == value)
    total = await db.scalar(select(func.count()).select_from(RuntimeStage).where(*conditions))
    rows = (
        await db.scalars(
            select(RuntimeStage)
            .where(*conditions)
            .order_by(RuntimeStage.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {"items": [_stage_payload(row) for row in rows], "total": total, "page": page, "page_size": page_size}


async def workers(db, project, run_id, stage_id, status, page, page_size):
    value = await selected_run(db, project, run_id)
    conditions = [WorkerTask.project_id == project.id, WorkerTask.run_id == value]
    if stage_id is not None:
        stage = await db.get(RuntimeStage, stage_id)
        if stage is None or stage.project_id != project.id or stage.run_id != value:
            raise NotFound("指定的执行阶段不存在")
        conditions.append(WorkerTask.stage_id == stage_id)
    if status:
        conditions.append(WorkerTask.task_status == status)
    total = await db.scalar(select(func.count()).select_from(WorkerTask).where(*conditions))
    rows = (
        await db.scalars(
            select(WorkerTask)
            .where(*conditions)
            .order_by(WorkerTask.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "project_id": row.project_id,
                "run_id": row.run_id,
                "stage_id": row.stage_id,
                "worker_role": row.worker_role,
                "task_content": row.task_content,
                "task_status": row.task_status,
                "result_summary": row.result_summary,
                "error_message": row.error_message,
                "retry_count": row.retry_count,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
