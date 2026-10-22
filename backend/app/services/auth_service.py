import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_user_by_username
from app.core.errors import BadRequest, Conflict, NotFound, TooManyRequests, Unauthorized
from app.core.security import (
    SESSION_HOURS,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.project import Project
from app.models.user import User, UserSession
from app.services.audit import audit

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
_LOCK_THRESHOLD = 5
_LOCK_SECONDS = 600
_demo_password = "Demo@123456"
_failures: dict[str, tuple[int, datetime | None]] = {}


def validate_username(username: str) -> str:
    value = username.strip()
    if not _USERNAME_RE.match(value):
        raise BadRequest("用户名需为 3~64 位字母、数字、下划线、点或短横线")
    return value


def validate_password(password: str) -> str:
    if not 8 <= len(password) <= 128:
        raise BadRequest("密码长度需为 8~128 位")
    return password


def _now() -> datetime:
    return datetime.now(UTC)


def _locked_until(username: str) -> datetime | None:
    _, locked_until = _failures.get(username, (0, None))
    if locked_until and locked_until > _now():
        return locked_until
    if locked_until:
        _failures.pop(username, None)
    return None


def _record_failure(username: str) -> None:
    count, _ = _failures.get(username, (0, None))
    count += 1
    if count >= _LOCK_THRESHOLD:
        _failures[username] = (0, _now() + timedelta(seconds=_LOCK_SECONDS))
    else:
        _failures[username] = (count, None)


def _clear_failures(username: str) -> None:
    _failures.pop(username, None)


async def init_system(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    create_demo_user: bool,
) -> dict:
    # 串行化首次初始化，避免并发创建两个管理员
    await db.execute(text("SELECT pg_advisory_xact_lock(1)"))

    admin_count = await db.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
    if admin_count:
        raise Conflict("系统已初始化")

    username = validate_username(username)
    password = validate_password(password)

    admin = User(
        username=username,
        password_hash=hash_password(password),
        role="admin",
        status="active",
    )
    db.add(admin)
    await db.flush()

    demo_username = None
    demo_password = None
    if create_demo_user:
        if await get_user_by_username(db, "demo_user") is None:
            db.add(
                User(
                    username="demo_user",
                    password_hash=hash_password(_demo_password),
                    role="user",
                    status="active",
                )
            )
            demo_username = "demo_user"
            demo_password = _demo_password

    await audit(
        db,
        "system_init",
        actor_id=admin.id,
        username=admin.username,
        detail={"create_demo_user": create_demo_user},
    )
    await db.commit()

    return {
        "admin_user_id": admin.id,
        "demo_username": demo_username,
        "demo_password": demo_password,
    }


async def authenticate(
    db: AsyncSession, *, username: str, password: str
) -> tuple[User, str, datetime]:
    username = username.strip()
    locked_until = _locked_until(username)
    if locked_until is not None:
        minutes = max(1, int((locked_until - _now()).total_seconds() // 60) + 1)
        raise TooManyRequests(f"登录失败次数过多，请 {minutes} 分钟后再试")

    user = await get_user_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        _record_failure(username)
        await audit(db, "login_failed", username=username, level="warning")
        await db.commit()
        raise Unauthorized("用户名或密码错误")

    if user.status != "active":
        await audit(db, "login_disabled", username=username, level="warning")
        await db.commit()
        raise Unauthorized("账号已被禁用")

    _clear_failures(username)

    jti = uuid.uuid4().hex
    expires_at = _now() + timedelta(hours=SESSION_HOURS)
    db.add(UserSession(jti=jti, user_id=user.id, expires_at=expires_at))
    await audit(db, "login", actor_id=user.id, username=user.username)
    await db.commit()

    token = create_access_token(
        user_id=user.id, role=user.role, jti=jti, expires_at=expires_at
    )
    return user, token, expires_at


async def revoke_session(db: AsyncSession, *, jti: str, user: User) -> None:
    session = await db.get(UserSession, jti)
    if session is not None and session.revoked_at is None:
        session.revoked_at = _now()
        await audit(db, "logout", actor_id=user.id, username=user.username)
        await db.commit()


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    role: str = "user",
    actor: User | None = None,
) -> User:
    username = validate_username(username)
    validate_password(password)
    if role != "user":
        raise BadRequest("只能创建普通用户")
    if await get_user_by_username(db, username) is not None:
        raise Conflict("用户名已存在")

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        status="active",
    )
    db.add(user)
    await db.flush()
    await audit(
        db,
        "user_create",
        actor_id=actor.id if actor else None,
        detail={"username": username, "role": role},
    )
    await db.commit()
    return user


async def list_users(db: AsyncSession, *, page: int, page_size: int) -> tuple[list[User], int]:
    total = await db.scalar(select(func.count()).select_from(User))
    rows = (
        await db.scalars(
            select(User).order_by(User.id).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return list(rows), int(total or 0)


async def set_user_status(
    db: AsyncSession, *, user_id: int, status: str, actor: User
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFound("用户不存在")
    if user.id == actor.id and status == "disabled":
        raise BadRequest("不能禁用当前登录账号")

    user.status = status
    if status == "disabled":
        await db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
    await audit(
        db,
        "user_status_change",
        actor_id=actor.id,
        username=actor.username,
        detail={"target": user.username, "status": status},
    )
    await db.commit()
    return user


async def delete_user(db: AsyncSession, *, user_id: int, actor: User) -> int:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFound("用户不存在")
    if user.id == actor.id:
        raise BadRequest("不能删除当前登录账号")
    if user.role == "admin":
        admin_count = await db.scalar(
            select(func.count()).select_from(User).where(User.role == "admin")
        )
        if int(admin_count or 0) <= 1:
            raise BadRequest("不能删除唯一的管理员账号")

    project_count = await db.scalar(
        select(func.count()).select_from(Project).where(Project.created_by == user.id)
    )
    if int(project_count or 0) > 0:
        raise Conflict("该用户下仍有项目，请先删除项目或禁用账号")

    target_name = user.username
    target_id = user.id
    await db.delete(user)
    await audit(
        db,
        "user_delete",
        actor_id=actor.id,
        username=actor.username,
        detail={"target": target_name, "target_id": target_id},
    )
    await db.commit()
    return target_id
