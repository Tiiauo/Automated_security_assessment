import asyncio
import re
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from app.api.monitoring import Auth, Db, Run
from app.core.errors import AppError
from app.schemas.common import ok
from app.services import project_service, report_service

router = APIRouter(prefix="/api/projects", tags=["reports"])
SAFE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


@router.get("/{project_id}/report")
async def report(
    project_id: int, db: Db, ctx: Auth, run_id: Run = None, format: Literal["json", "html", "markdown"] = "json"
):
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    row = await report_service.get_report(db, project, run_id)
    if format == "html":
        return HTMLResponse(row.report_html, headers=SAFE_HEADERS)
    if format == "markdown":
        return PlainTextResponse(row.report_markdown, media_type="text/markdown", headers=SAFE_HEADERS)
    return JSONResponse(ok(report_service.report_payload(row)), headers=SAFE_HEADERS)


@router.get("/{project_id}/report/download")
async def download(project_id: int, db: Db, ctx: Auth, run_id: Run = None, format: Literal["md", "html"] = "md"):
    project = await project_service.get_visible_project(db, project_id, ctx.user)
    row = await report_service.get_report(db, project, run_id)
    path = report_service.report_base(project_id, row.run_id).with_suffix("." + format)
    content = row.report_markdown if format == "md" else row.report_html
    try:
        stored = await asyncio.to_thread(path.read_bytes)
    except OSError as exc:
        raise AppError("报告文件缺失或不可读，请检查报告存储") from exc
    if stored != content.encode("utf-8"):
        raise AppError("报告文件与数据库内容不一致，拒绝下载")
    name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", project.project_name).strip(" .") or "project"
    filename = quote(f"{name}-run-{row.run_id}-security-report.{format}", safe="")
    headers = {**SAFE_HEADERS, "Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return Response(content=stored, media_type="text/markdown" if format == "md" else "text/html", headers=headers)
