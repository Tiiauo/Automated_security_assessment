from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import AuthContext, get_auth_context
from app.core.errors import Conflict
from app.schemas.common import ok
from app.schemas.project import ProjectCreateRequest
from app.services import project_service, runtime_query

router = APIRouter(prefix="/api/projects", tags=["projects"])

ProjectStatus = Literal["created", "running", "completed", "failed", "stopped"]


@router.get("")
async def list_projects(
    status: ProjectStatus | None = Query(None),
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    projects, total = await project_service.list_projects(
        db,
        user=ctx.user,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [project_service.project_payload(project) for project in projects],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("")
async def create_project(
    payload: ProjectCreateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await project_service.create_project(db, user=ctx.user, payload=payload)
    return ok(
        {
            "project_id": project.id,
            "project_status": project.project_status,
        }
    )


@router.get("/{project_id}")
async def get_project(
    project_id: int,
    run_id: int | None = Query(None, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    return ok(await project_service.get_project_detail(db, project, run_id=run_id))


@router.post("/{project_id}/start")
async def start_project(
    project_id: int,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    run_id = await project_service.start_project(db, project, actor=ctx.user)
    return ok({"project_status": "running", "run_id": run_id, "sandbox_id": project.sandbox_id})


@router.post("/{project_id}/stop")
async def stop_project(
    project_id: int,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    status = await project_service.stop_project(db, project, actor=ctx.user)
    return ok({"project_status": status})


@router.get("/{project_id}/stages")
async def list_stages(
    project_id: int,
    run_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    return ok(await runtime_query.stages(db, project, run_id, page, page_size))


@router.get("/{project_id}/workers")
async def list_workers(
    project_id: int,
    run_id: int | None = Query(None, ge=1),
    stage_id: int | None = Query(None, ge=1),
    status: Literal["idle", "running", "success", "failed"] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    return ok(await runtime_query.workers(db, project, run_id, stage_id, status, page, page_size))


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    if project.project_status == "running":
        raise Conflict("任务执行中，请先停止任务")

    deleted, dirs_cleaned, error = await project_service.delete_project(db, project, actor=ctx.user)
    if not deleted:
        return JSONResponse(
            status_code=500,
            content={
                "code": 50001,
                "message": error or "项目删除失败",
                "data": {"deleted": False, "dirs_cleaned": dirs_cleaned},
            },
        )
    return JSONResponse(
        status_code=200,
        content=ok({"deleted": True, "dirs_cleaned": True}),
    )
