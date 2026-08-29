import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from a_stock_lab.database.base import Base


class TailRadarRunRecord(Base):
    """Feature-specific evidence for one shared execution lifecycle record."""

    __tablename__ = "tail_radar_runs"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "screening_rule_version",
            name="uq_tail_radar_runs_snapshot_rule_version",
        ),
        UniqueConstraint(
            "run_id",
            "snapshot_id",
            name="uq_tail_radar_runs_run_snapshot",
        ),
        CheckConstraint(
            "(evaluated_record_count IS NULL AND invalid_record_count IS NULL "
            "AND candidate_count IS NULL) OR "
            "(evaluated_record_count IS NOT NULL AND invalid_record_count IS NOT NULL "
            "AND candidate_count IS NOT NULL)",
            name="counts_finalized_together",
        ),
        CheckConstraint(
            "evaluated_record_count IS NULL OR evaluated_record_count >= 0",
            name="evaluated_count_non_negative",
        ),
        CheckConstraint(
            "invalid_record_count IS NULL OR invalid_record_count >= 0",
            name="invalid_count_non_negative",
        ),
        CheckConstraint(
            "candidate_count IS NULL OR candidate_count >= 0",
            name="candidate_count_non_negative",
        ),
        CheckConstraint(
            "evaluated_record_count IS NULL OR "
            "invalid_record_count + candidate_count <= evaluated_record_count",
            name="counts_within_evaluated",
        ),
        Index("ix_tail_radar_runs_snapshot_id", "snapshot_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_runs.run_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("market_snapshot_manifests.snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    )
    screening_rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evaluated_record_count: Mapped[int | None] = mapped_column(Integer)
    invalid_record_count: Mapped[int | None] = mapped_column(Integer)
    candidate_count: Mapped[int | None] = mapped_column(Integer)


class TailRadarCandidateRecord(Base):
    """Relational link from a versioned candidate artifact to its run and snapshot."""

    __tablename__ = "tail_radar_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "snapshot_id"],
            ["tail_radar_runs.run_id", "tail_radar_runs.snapshot_id"],
            name="fk_tail_radar_candidates_run_snapshot_tail_radar_runs",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "run_id",
            "symbol",
            name="uq_tail_radar_candidates_run_symbol",
        ),
        CheckConstraint("symbol ~ '^[0-9]{6}$'", name="symbol_format"),
        Index("ix_tail_radar_candidates_snapshot_symbol", "snapshot_id", "symbol"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_artifacts.artifact_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(6), nullable=False)
