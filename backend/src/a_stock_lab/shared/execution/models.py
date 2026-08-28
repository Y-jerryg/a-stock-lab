import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, Index, String, Text, func
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
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_type: Mapped[str] = mapped_column(String(128), nullable=False)
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
