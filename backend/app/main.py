import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.analysis import router as analysis_router
from app.api.monitoring import router as monitoring_router
from app.api.projects import router as projects_router
from app.api.reports import router as reports_router
from app.api.system import router as system_router
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import AppError
from app.services import config_service, monitoring
from app.services.run_manager import run_manager
from app.version import __version__

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        async with SessionLocal() as session:
            await config_service.ensure_defaults(session)
    except Exception:  # noqa: BLE001 - 数据库不可用时仍允许启动，由健康检查暴露
        logger.warning("skipped seeding default configs", exc_info=True)
    try:
        await run_manager.recover()
    except Exception:
        # 状态源不可用时不能接受新任务，避免旧 running 与新句柄混杂。
        logger.exception("failed to recover interrupted runs")
        raise
    cleanup = asyncio.create_task(monitoring.prune(SessionLocal))
    try:
        yield
    finally:
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)
        await run_manager.shutdown()


app = FastAPI(title="自动化安全评估系统", version=__version__, lifespan=lifespan)

if settings.cors_allow_origins.strip():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_allow_origins.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(system_router)
app.include_router(projects_router)
app.include_router(analysis_router)
app.include_router(monitoring_router)
app.include_router(reports_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    if errors:
        location = ".".join(str(part) for part in errors[0].get("loc", []))
        message = f"{location}: {errors[0].get('msg', '请求参数不合法')}"
    else:
        message = "请求参数不合法"
    return JSONResponse(
        status_code=400,
        content={"code": 40001, "message": message, "data": None},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": 50001, "message": "服务内部错误", "data": None},
    )
