import asyncio
import logging
import re

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import AuthContext, get_auth_context, require_admin
from app.core.errors import BadRequest
from app.core.security import COOKIE_NAME, SESSION_HOURS, mask_secret
from app.models.project import Project
from app.models.user import User
from app.schemas.common import ok
from app.schemas.system import (
    InitRequest,
    LoginRequest,
    TestLLMRequest,
    UserCreateRequest,
    UserPatchRequest,
)
from app.services import auth_service, config_service, sandbox_service
from app.services.audit import audit
from app.services.llm_probe import probe_llm
from app.version import __version__

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

_SANDBOX_REFERENCE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _docker_ping() -> bool:
    import docker

    settings = get_settings()
    try:
        if settings.docker_host:
            client = docker.DockerClient(base_url=settings.docker_host, timeout=3)
        else:
            client = docker.from_env(timeout=3)
        try:
            return bool(client.ping())
        finally:
            client.close()
    except Exception:  # noqa: BLE001 - 健康检查只关心结果
        return False


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "status": user.status,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/init")
async def system_init(payload: InitRequest, db: AsyncSession = Depends(get_db)) -> dict:
    data = await auth_service.init_system(
        db,
        username=payload.username,
        password=payload.password,
        create_demo_user=payload.create_demo_user,
    )
    return ok(data)


@router.get("/status")
async def system_status(db: AsyncSession = Depends(get_db)) -> dict:
    count = await db.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
    return ok({"initialized": bool(count)})


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        logger.warning("health check: database unreachable", exc_info=True)
        db_status = "error"

    docker_status = "ok" if await asyncio.to_thread(_docker_ping) else "error"
    overall = "ok" if db_status == "ok" and docker_status == "ok" else "degraded"
    return ok(
        {
            "status": overall,
            "version": __version__,
            "db": db_status,
            "docker": docker_status,
        }
    )


@router.post("/login")
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user, token, expires_at = await auth_service.authenticate(
        db, username=payload.username, password=payload.password
    )
    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return ok(
        {
            "user": {"id": user.id, "username": user.username, "role": user.role},
            "expires_at": expires_at.isoformat(),
        }
    )


@router.post("/logout")
async def logout(
    response: Response,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await auth_service.revoke_session(db, jti=ctx.jti, user=ctx.user)
    response.delete_cookie(COOKIE_NAME, path="/")
    return ok({"logged_out": True})


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    users, total = await auth_service.list_users(db, page=page, page_size=page_size)
    return ok(
        {
            "items": [_user_payload(user) for user in users],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/users")
async def create_user(
    payload: UserCreateRequest,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await auth_service.create_user(
        db,
        username=payload.username,
        password=payload.password,
        role=payload.role,
        actor=ctx.user,
    )
    return ok({"user_id": user.id, "username": user.username})


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int,
    payload: UserPatchRequest,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await auth_service.set_user_status(
        db, user_id=user_id, status=payload.status, actor=ctx.user
    )
    return ok({"user_id": user.id, "status": user.status})


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    deleted_id = await auth_service.delete_user(db, user_id=user_id, actor=ctx.user)
    return ok({"user_id": deleted_id, "deleted": True})


@router.get("/config")
async def get_config(
    _: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return ok(await config_service.get_config_masked(db))


@router.put("/config")
async def put_config(
    payload: dict[str, object] = Body(...),
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return ok(await config_service.update_config(db, payload, actor_id=ctx.user.id))


@router.post("/config/test-llm")
async def test_llm(
    payload: TestLLMRequest,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    raw = await config_service.get_config_raw(db)
    base_url = (payload.base_url or raw["llm.base_url"]).strip()
    model = (payload.model or raw["llm.model"]).strip()
    api_key = payload.api_key or ""
    if not api_key or api_key == mask_secret(raw["llm.api_key"]):
        api_key = raw["llm.api_key"]
    timeout_seconds = int(float(raw["llm.timeout_seconds"]))

    result = await probe_llm(
        base_url=base_url, model=model, api_key=api_key, timeout_seconds=timeout_seconds
    )
    await audit(
        db,
        "llm_connection_test",
        actor_id=ctx.user.id,
        detail={key: result[key] for key in ("url_ok", "model_ok", "auth_ok", "tools_ok")},
    )
    await db.commit()
    return ok(result)


@router.get("/sandboxes")
async def list_sandboxes(
    _: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    data = await sandbox_service.list_sandboxes(db)
    return ok(
        {
            "items": [
                {
                    "sandbox_id": item["id"],
                    "name": item["name"],
                    "project_id": item.get("project_id"),
                    "project_name": item.get("project_name"),
                    "run_id": item.get("run_id"),
                    "status": item["status"],
                    "image": item.get("image"),
                    "created_at": item.get("created_at"),
                }
                for item in data["containers"]
            ],
            "cleanup_pending": [
                {
                    "project_id": project["id"],
                    "project_name": project["project_name"],
                    "cleanup_error": project["cleanup_error"],
                    "updated_at": project["updated_at"],
                }
                for project in data["cleanup_pending_projects"]
            ],
            "volumes": data["volumes"],
        }
    )


@router.delete("/sandboxes/{sandbox_id}")
async def destroy_sandbox(
    sandbox_id: str,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not _SANDBOX_REFERENCE.fullmatch(sandbox_id):
        raise BadRequest("隔离环境编号不合法")

    await sandbox_service.force_remove(sandbox_id)
    await db.execute(
        update(Project).where(Project.sandbox_id == sandbox_id).values(sandbox_id=None)
    )
    await audit(
        db,
        "sandbox_force_destroy",
        actor_id=ctx.user.id,
        detail={"sandbox_id": sandbox_id},
    )
    await db.commit()
    return ok({"cleaned": True})
