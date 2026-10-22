from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "run_id"],
            ["project_runs.project_id", "project_runs.run_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    worker_role: Mapped[str] = mapped_column(String(32), nullable=False)
    message_type: Mapped[str] = mapped_column(String(16), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RuntimeLog(Base):
    __tablename__ = "runtime_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("runtime_stages.id", ondelete="SET NULL"), nullable=True
    )
    worker_task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("worker_tasks.id", ondelete="SET NULL"), nullable=True
    )
    log_level: Mapped[str] = mapped_column(String(16), nullable=False)
    log_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )


class ResourceUsage(Base):
    __tablename__ = "resource_usages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "run_id"],
            ["project_runs.project_id", "project_runs.run_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    cpu_usage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    memory_usage: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
