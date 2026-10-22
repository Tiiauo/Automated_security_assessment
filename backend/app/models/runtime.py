from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RuntimeStage(Base):
    __tablename__ = "runtime_stages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "run_id"],
            ["project_runs.project_id", "project_runs.run_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("project_id", "run_id", "stage_name", name="uq_stage_project_run_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    stage_name: Mapped[str] = mapped_column(String(32), nullable=False)
    stage_status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkerTask(Base):
    __tablename__ = "worker_tasks"
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
    stage_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("runtime_stages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    worker_role: Mapped[str] = mapped_column(String(32), nullable=False)
    task_content: Mapped[str] = mapped_column(Text, nullable=False)
    task_status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
