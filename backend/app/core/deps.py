from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import COOKIE_NAME, decode_access_token
from app.models.user import User, UserSession


@dataclass
class AuthContext:
    user: User
    jti: str


async def get_auth_context(
    request: HTTPConnection,
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise Unauthorized("未登录")
    payload = decode_access_token(token)
    jti = str(payload.get("jti") or "")
    if not jti:
        raise Unauthorized("登录状态无效")

    session = await db.get(UserSession, jti)
    if session is None or session.revoked_at is not None:
        raise Unauthorized("登录已失效，请重新登录")
    if session.expires_at <= datetime.now(UTC):
        raise Unauthorized("登录已过期，请重新登录")

    user = await db.get(User, int(payload["sub"]))
    if user is None or user.status != "active":
        raise Unauthorized("账号不可用")

    return AuthContext(user=user, jti=jti)


async def require_admin(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if ctx.user.role != "admin":
        raise Forbidden("需要管理员权限")
    return ctx


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    return await db.scalar(select(User).where(User.username == username))
