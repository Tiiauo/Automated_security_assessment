import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collab import RuntimeLog


async def audit(
    db: AsyncSession,
    action: str,
    *,
    actor_id: int | None = None,
    username: str | None = None,
    detail: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    """写入系统级审计日志（project_id / run_id 为空）。调用方负责 commit。"""
    payload: dict[str, Any] = {"action": action}
    if actor_id is not None:
        payload["actor_id"] = actor_id
    if username:
        payload["username"] = username
    if detail:
        payload["detail"] = detail
    db.add(
        RuntimeLog(
            project_id=None,
            run_id=None,
            log_level=level,
            log_content=json.dumps(payload, ensure_ascii=False, default=str),
        )
    )
