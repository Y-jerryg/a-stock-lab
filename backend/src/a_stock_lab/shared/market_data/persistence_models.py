import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from a_stock_lab.database.base import Base
from a_stock_lab.shared.market_data.models import SnapshotManifestStatus


class MarketSnapshotManifestRecord(Base):
    """Immutable PostgreSQL reference to one accepted Parquet market snapshot."""

    __tablename__ = "market_snapshot_manifests"
    __table_args__ = (
        Index(
            "ix_market_snapshot_manifests_trade_date_intended_time",
            "trade_date",
            "intended_snapshot_time",
        ),
        CheckConstraint("row_count > 0", name="row_count_positive"),
        CheckConstraint("latency_ms >= 0", name="latency_non_negative"),
        CheckConstraint("schema_version > 0", name="schema_version_positive"),
        CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="checksum_sha256_format",
        ),
        CheckConstraint(
            "actual_fetch_finished_at >= actual_fetch_started_at",
            name="fetch_timing_ordered",
        ),
        CheckConstraint(
            "persisted_at >= actual_fetch_finished_at",
            name="persisted_after_fetch",
        ),
        CheckConstraint(
            "trade_date = (intended_snapshot_time AT TIME ZONE 'Asia/Shanghai')::date",
            name="trade_date_matches_intended_time",
        ),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_runs.run_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    intended_snapshot_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    actual_fetch_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    actual_fetch_finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_version: Mapped[str | None] = mapped_column(String(128))
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    quality_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SnapshotManifestStatus] = mapped_column(
        Enum(SnapshotManifestStatus, name="snapshot_manifest_status"),
        nullable=False,
        default=SnapshotManifestStatus.AVAILABLE,
    )
    persisted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
