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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Vulnerability(Base):
    __tablename__ = "vulnerabilities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "run_id"],
            ["project_runs.project_id", "project_runs.run_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("project_id", "run_id", "vuln_code", name="uq_vuln_project_run_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    stage_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("runtime_stages.id", ondelete="SET NULL"),
        nullable=True,
    )
    vuln_code: Mapped[str] = mapped_column(String(32), nullable=False)
    vuln_title: Mapped[str] = mapped_column(String(200), nullable=False)
    vuln_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    cvss_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    impact_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    verify_status: Mapped[str] = mapped_column(String(16), nullable=False)
    reproduce_steps_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    verify_code_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AttackPath(Base):
    __tablename__ = "attack_paths"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "run_id"],
            ["project_runs.project_id", "project_runs.run_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("project_id", "run_id", "path_code", name="uq_path_project_run_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    path_code: Mapped[str] = mapped_column(String(32), nullable=False)
    path_title: Mapped[str] = mapped_column(String(200), nullable=False)
    path_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_impact_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AttackPathItem(Base):
    __tablename__ = "attack_path_items"
    __table_args__ = (
        UniqueConstraint("path_id", "step_order", name="uq_path_item_step"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    path_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attack_paths.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vuln_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vulnerabilities.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_text: Mapped[str | None] = mapped_column(Text, nullable=True)
