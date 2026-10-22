from typing import Literal

from fastapi import APIRouter, Query

from app.api.monitoring import Auth, Db, Page, Run, Size
from app.schemas.common import ok
from app.services import analysis_query, project_service

router = APIRouter(prefix="/api/projects", tags=["analysis"])


@router.get("/{project_id}/vulnerabilities")
async def vulnerabilities(
    project_id: int,
    db: Db,
    ctx: Auth,
    run_id: Run = None,
    risk_level: Literal["critical", "high", "medium", "low", "info"] | None = None,
    verify_status: Literal["pending", "verified", "unverified", "false_positive"] | None = None,
    keyword: str | None = Query(None, max_length=100),
    page: Page = 1,
    page_size: Size = 20,
):
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    return ok(
        await analysis_query.vulnerabilities(db, project, run_id, risk_level, verify_status, keyword, page, page_size)
    )


@router.get("/{project_id}/vulnerabilities/{vuln_id}")
async def vulnerability(project_id: int, vuln_id: int, db: Db, ctx: Auth):
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    return ok(await analysis_query.vulnerability(db, project, vuln_id))


@router.get("/{project_id}/attack-paths")
async def paths(project_id: int, db: Db, ctx: Auth, run_id: Run = None, page: Page = 1, page_size: Size = 20):
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    return ok(await analysis_query.paths(db, project, run_id, page, page_size))


@router.get("/{project_id}/attack-paths/{path_id}")
async def path(project_id: int, path_id: int, db: Db, ctx: Auth):
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    return ok(await analysis_query.path(db, project, path_id))
