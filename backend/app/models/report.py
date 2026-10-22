from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "run_id"],
            ["project_runs.project_id", "project_runs.run_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("project_id", "run_id", name="uq_report_project_run"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    report_html: Mapped[str] = mapped_column(Text, nullable=False)
    report_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
