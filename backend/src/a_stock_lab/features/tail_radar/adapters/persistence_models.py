import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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
        UniqueConstraint(
            "candidate_id",
            "run_id",
            "snapshot_id",
            "symbol",
            name="uq_tail_radar_candidates_analysis_source",
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


class TailRadarIntradayAnalysisRecord(Base):
    """Relational provenance for one versioned candidate intraday feature artifact."""

    __tablename__ = "tail_radar_intraday_analyses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "run_id", "snapshot_id", "symbol"],
            [
                "tail_radar_candidates.candidate_id",
                "tail_radar_candidates.run_id",
                "tail_radar_candidates.snapshot_id",
                "tail_radar_candidates.symbol",
            ],
            name="fk_tail_radar_intraday_analysis_candidate_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "candidate_id",
            "analysis_as_of",
            "calculation_version",
            name="uq_tail_radar_intraday_candidate_as_of_version",
        ),
        CheckConstraint("symbol ~ '^[0-9]{6}$'", name="symbol_format"),
        Index(
            "ix_tail_radar_intraday_candidate_as_of",
            "candidate_id",
            "analysis_as_of",
        ),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_artifacts.artifact_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(6), nullable=False)
    analysis_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)


class TailRadarResearchRecord(Base):
    """One cached or explicitly forced paid web-research attempt for a candidate."""

    __tablename__ = "tail_radar_research_analyses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "run_id", "snapshot_id", "symbol"],
            [
                "tail_radar_candidates.candidate_id",
                "tail_radar_candidates.run_id",
                "tail_radar_candidates.snapshot_id",
                "tail_radar_candidates.symbol",
            ],
            name="fk_tail_radar_research_candidate_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint("symbol ~ '^[0-9]{6}$'", name="symbol_format"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'no_evidence', 'failed')",
            name="status_valid",
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 "
            "AND total_tokens >= input_tokens + output_tokens",
            name="token_counts_non_negative",
        ),
        CheckConstraint(
            "actual_finished_at IS NULL OR actual_finished_at >= actual_started_at",
            name="timing_order",
        ),
        CheckConstraint(
            "(NOT is_forced AND base_research_id IS NULL) OR is_forced",
            name="forced_lineage",
        ),
        CheckConstraint(
            "base_research_id IS NULL OR base_research_id <> research_id",
            name="lineage_not_self",
        ),
        CheckConstraint(
            "prompt_sha256 ~ '^[0-9a-f]{64}$'",
            name="prompt_hash_format",
        ),
        CheckConstraint(
            "(status = 'running' AND actual_finished_at IS NULL "
            "AND artifact_id IS NULL AND error_code IS NULL) OR "
            "(status = 'failed' AND actual_finished_at IS NOT NULL "
            "AND artifact_id IS NULL AND error_code IS NOT NULL) OR "
            "(status IN ('succeeded', 'no_evidence') AND actual_finished_at IS NOT NULL "
            "AND artifact_id IS NOT NULL AND error_code IS NULL)",
            name="lifecycle_consistent",
        ),
        Index(
            "uq_tail_radar_research_cached_identity",
            "candidate_id",
            "run_id",
            "analysis_as_of",
            "prompt_version",
            "provider",
            "requested_model",
            unique=True,
            postgresql_where=text("is_forced = false"),
        ),
        Index(
            "ix_tail_radar_research_candidate_as_of",
            "candidate_id",
            "analysis_as_of",
        ),
    )

    research_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_artifacts.artifact_id", ondelete="RESTRICT"),
        unique=True,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(6), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    analysis_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_model: Mapped[str] = mapped_column(String(128), nullable=False)
    actual_model: Mapped[str | None] = mapped_column(String(128))
    provider_response_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_forced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_research_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tail_radar_research_analyses.research_id", ondelete="RESTRICT"),
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    actual_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TailRadarResearchSourceRecord(Base):
    """Source metadata stored independently from the research artifact payload."""

    __tablename__ = "tail_radar_research_sources"
    __table_args__ = (
        UniqueConstraint("research_id", "url", name="uq_tail_radar_research_source_url"),
        CheckConstraint(
            "publication_timestamp_status IN ('verified', 'uncertain', 'unavailable')",
            name="publication_status",
        ),
        CheckConstraint(
            "availability_at_as_of IN "
            "('available_at_as_of', 'published_after_as_of', 'uncertain_at_as_of')",
            name="availability_status",
        ),
        CheckConstraint(
            "(publication_timestamp_status = 'verified' AND published_at IS NOT NULL) "
            "OR publication_timestamp_status = 'uncertain' "
            "OR (publication_timestamp_status = 'unavailable' AND published_at IS NULL)",
            name="publication_timestamp",
        ),
        CheckConstraint(
            "(availability_at_as_of IN ('available_at_as_of', 'published_after_as_of') "
            "AND publication_timestamp_status = 'verified') OR "
            "(availability_at_as_of = 'uncertain_at_as_of' "
            "AND publication_timestamp_status <> 'verified')",
            name="availability_timestamp",
        ),
        CheckConstraint(
            "published_at IS NULL OR published_at <= retrieved_at",
            name="publication_retrieval_order",
        ),
        CheckConstraint(
            "jsonb_typeof(relationship_claim_ids) = 'array'",
            name="claim_relationships_array",
        ),
        Index("ix_tail_radar_research_sources_research_id", "research_id"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    research_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tail_radar_research_analyses.research_id", ondelete="RESTRICT"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    publisher_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_timestamp_status: Mapped[str] = mapped_column(String(32), nullable=False)
    availability_at_as_of: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    relationship_claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TailRadarWorkflowRecord(Base):
    """Durable lifecycle for the complete snapshot-to-research application workflow."""

    __tablename__ = "tail_radar_workflows"
    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('claimed', 'snapshot_running', 'screening_running', "
            "'candidate_analysis_running', 'succeeded', 'partial_success', 'failed')",
            name="lifecycle_valid",
        ),
        CheckConstraint(
            "candidate_count IS NULL OR candidate_count >= 0",
            name="candidate_count_non_negative",
        ),
        CheckConstraint(
            "technical_succeeded_count >= 0 AND technical_failed_count >= 0 "
            "AND technical_pending_count >= 0 AND research_succeeded_count >= 0 "
            "AND research_no_evidence_count >= 0 AND research_failed_count >= 0 "
            "AND research_pending_count >= 0",
            name="stage_counts_non_negative",
        ),
        CheckConstraint(
            "candidate_count IS NULL OR "
            "(technical_succeeded_count + technical_failed_count + "
            "technical_pending_count = candidate_count AND "
            "research_succeeded_count + research_no_evidence_count + "
            "research_failed_count + research_pending_count = candidate_count)",
            name="stage_counts_cover_candidates",
        ),
        CheckConstraint(
            "screening_run_id IS NULL OR "
            "(snapshot_run_id IS NOT NULL AND snapshot_id IS NOT NULL "
            "AND analysis_as_of IS NOT NULL)",
            name="screening_requires_provenance",
        ),
        UniqueConstraint("screening_run_id", name="uq_tail_radar_workflows_screening_run"),
        Index("ix_tail_radar_workflows_snapshot_id", "snapshot_id"),
    )

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_runs.run_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    workflow_version: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    analysis_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_runs.run_id", ondelete="RESTRICT")
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("market_snapshot_manifests.snapshot_id", ondelete="RESTRICT"),
    )
    screening_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tail_radar_runs.run_id", ondelete="RESTRICT")
    )
    candidate_count: Mapped[int | None] = mapped_column(Integer)
    technical_succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    technical_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    technical_pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    research_succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    research_no_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    research_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    research_pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_stage: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TailRadarWorkflowCandidateRecord(Base):
    """Per-candidate stage state used for failure isolation and resumability."""

    __tablename__ = "tail_radar_workflow_candidates"
    __table_args__ = (
        CheckConstraint(
            "technical_status IN ('pending', 'running', 'succeeded', 'failed')",
            name="technical_status_valid",
        ),
        CheckConstraint(
            "research_status IN ('pending', 'running', 'succeeded', 'no_evidence', 'failed')",
            name="research_status_valid",
        ),
        CheckConstraint(
            "(technical_status = 'succeeded' AND intraday_analysis_id IS NOT NULL "
            "AND technical_error_code IS NULL) OR "
            "(technical_status = 'failed' AND intraday_analysis_id IS NULL "
            "AND technical_error_code IS NOT NULL) OR "
            "(technical_status IN ('pending', 'running') AND intraday_analysis_id IS NULL "
            "AND technical_error_code IS NULL)",
            name="technical_stage_state",
        ),
        CheckConstraint(
            "(research_status IN ('succeeded', 'no_evidence') AND research_id IS NOT NULL "
            "AND research_error_code IS NULL) OR "
            "(research_status = 'failed' AND research_id IS NULL "
            "AND research_error_code IS NOT NULL) OR "
            "(research_status IN ('pending', 'running') AND research_id IS NULL "
            "AND research_error_code IS NULL)",
            name="research_stage_state",
        ),
        Index("ix_tail_radar_workflow_candidates_candidate", "candidate_id"),
    )

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tail_radar_workflows.workflow_run_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tail_radar_candidates.candidate_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    technical_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    research_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    intraday_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tail_radar_intraday_analyses.analysis_id", ondelete="RESTRICT"),
    )
    research_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tail_radar_research_analyses.research_id", ondelete="RESTRICT"),
    )
    technical_error_code: Mapped[str | None] = mapped_column(String(128))
    research_error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TailRadarScheduleRecord(Base):
    """Operational evidence for one official 14:30 schedule decision."""

    __tablename__ = "tail_radar_schedules"
    __table_args__ = (
        UniqueConstraint(
            "job_name",
            "trade_date",
            "schedule_version",
            name="uq_tail_radar_schedules_logical_day",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'preflight_ready', 'preflight_degraded', "
            "'executing', 'succeeded', 'partial_success', 'failed', 'missed', "
            "'not_trading_day')",
            name="status_valid",
        ),
        CheckConstraint(
            "preflight_finished_at IS NULL OR preflight_started_at IS NOT NULL",
            name="preflight_finish_requires_start",
        ),
        CheckConstraint(
            "preflight_finished_at IS NULL OR preflight_finished_at >= preflight_started_at",
            name="preflight_timing_order",
        ),
        CheckConstraint(
            "execution_finished_at IS NULL OR execution_started_at IS NULL OR "
            "execution_finished_at >= execution_started_at",
            name="execution_timing_order",
        ),
        CheckConstraint(
            "status <> 'executing' OR execution_started_at IS NOT NULL",
            name="executing_requires_start",
        ),
        CheckConstraint(
            "status NOT IN ('succeeded', 'partial_success') OR "
            "(workflow_run_id IS NOT NULL AND execution_finished_at IS NOT NULL)",
            name="completion_requires_provenance",
        ),
        CheckConstraint(
            "status <> 'missed' OR workflow_run_id IS NULL",
            name="missed_has_no_workflow",
        ),
        CheckConstraint(
            "status <> 'not_trading_day' OR is_trading_day = false",
            name="calendar_status_consistent",
        ),
        Index("ix_tail_radar_schedules_trade_date", "trade_date"),
        Index("ix_tail_radar_schedules_status", "status"),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_name: Mapped[str] = mapped_column(String(128), nullable=False)
    schedule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    intended_snapshot_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    calendar_provider: Mapped[str] = mapped_column(String(128), nullable=False)
    preflight_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preflight_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preflight_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tail_radar_workflows.workflow_run_id", ondelete="RESTRICT"),
        unique=True,
    )
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
