import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from a_stock_lab.database.base import Base


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionRun(Base):
    """Auditable lifecycle record for a background or manually invoked job."""

    __tablename__ = "execution_runs"
    __table_args__ = (
        Index("ix_execution_runs_job_type_intended_time", "job_type", "intended_execution_time"),
        Index("ix_execution_runs_rerun_of_run_id", "rerun_of_run_id"),
        Index(
            "uq_execution_runs_official_logical_key",
            "job_type",
            "trade_date",
            "intended_execution_time",
            "implementation_version",
            unique=True,
            postgresql_where=text("is_official AND trade_date IS NOT NULL"),
        ),
        CheckConstraint(
            "trade_date IS NULL OR "
            "trade_date = (intended_execution_time AT TIME ZONE 'Asia/Shanghai')::date",
            name="trade_date_matches_intended_time",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_type: Mapped[str] = mapped_column(String(128), nullable=False)
    trade_date: Mapped[date | None] = mapped_column(Date)
    intended_execution_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    actual_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="execution_run_status"), nullable=False, default=RunStatus.PENDING
    )
    provider: Mapped[str | None] = mapped_column(String(128))
    implementation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rerun_of_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_runs.run_id", ondelete="RESTRICT"),
    )
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
