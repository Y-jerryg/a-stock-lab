"""Create cached Tail Radar web-research attempts and separate sources.

Revision ID: 20260830_0005
Revises: 20260829_0004
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0005"
down_revision: str | None = "20260829_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tail_radar_research_analyses",
        sa.Column("research_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=6), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("analysis_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("requested_model", sa.String(length=128), nullable=False),
        sa.Column("actual_model", sa.String(length=128), nullable=True),
        sa.Column("provider_response_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_forced", sa.Boolean(), nullable=False),
        sa.Column("base_research_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("actual_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "symbol ~ '^[0-9]{6}$'",
            name=op.f("ck_tail_radar_research_analyses_symbol_format"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'no_evidence', 'failed')",
            name=op.f("ck_tail_radar_research_analyses_status_valid"),
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 "
            "AND total_tokens >= input_tokens + output_tokens",
            name=op.f("ck_tail_radar_research_analyses_token_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "actual_finished_at IS NULL OR actual_finished_at >= actual_started_at",
            name=op.f("ck_tail_radar_research_analyses_timing_order"),
        ),
        sa.CheckConstraint(
            "(NOT is_forced AND base_research_id IS NULL) OR is_forced",
            name=op.f("ck_tail_radar_research_analyses_forced_lineage"),
        ),
        sa.CheckConstraint(
            "base_research_id IS NULL OR base_research_id <> research_id",
            name=op.f("ck_tail_radar_research_analyses_lineage_not_self"),
        ),
        sa.CheckConstraint(
            "prompt_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_tail_radar_research_analyses_prompt_hash_format"),
        ),
        sa.CheckConstraint(
            "(status = 'running' AND actual_finished_at IS NULL "
            "AND artifact_id IS NULL AND error_code IS NULL) OR "
            "(status = 'failed' AND actual_finished_at IS NOT NULL "
            "AND artifact_id IS NULL AND error_code IS NOT NULL) OR "
            "(status IN ('succeeded', 'no_evidence') AND actual_finished_at IS NOT NULL "
            "AND artifact_id IS NOT NULL AND error_code IS NULL)",
            name=op.f("ck_tail_radar_research_analyses_lifecycle_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["research_artifacts.artifact_id"],
            name=op.f("fk_tail_radar_research_analyses_artifact_id_research_artifacts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_research_id"],
            ["tail_radar_research_analyses.research_id"],
            name=op.f(
                "fk_tail_radar_research_analyses_base_research_id_tail_radar_research_analyses"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("research_id", name=op.f("pk_tail_radar_research_analyses")),
        sa.UniqueConstraint(
            "artifact_id",
            name=op.f("uq_tail_radar_research_analyses_artifact_id"),
        ),
    )
    op.create_index(
        "ix_tail_radar_research_candidate_as_of",
        "tail_radar_research_analyses",
        ["candidate_id", "analysis_as_of"],
        unique=False,
    )
    op.create_index(
        "uq_tail_radar_research_cached_identity",
        "tail_radar_research_analyses",
        [
            "candidate_id",
            "run_id",
            "analysis_as_of",
            "prompt_version",
            "provider",
            "requested_model",
        ],
        unique=True,
        postgresql_where=sa.text("is_forced = false"),
    )
    op.create_table(
        "tail_radar_research_sources",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("publisher_domain", sa.String(length=253), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publication_timestamp_status", sa.String(length=32), nullable=False),
        sa.Column("availability_at_as_of", sa.String(length=32), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "relationship_claim_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "availability_at_as_of IN "
            "('available_at_as_of', 'published_after_as_of', 'uncertain_at_as_of')",
            name=op.f("ck_tail_radar_research_sources_availability_status"),
        ),
        sa.CheckConstraint(
            "publication_timestamp_status IN ('verified', 'uncertain', 'unavailable')",
            name=op.f("ck_tail_radar_research_sources_publication_status"),
        ),
        sa.CheckConstraint(
            "(publication_timestamp_status = 'verified' AND published_at IS NOT NULL) "
            "OR publication_timestamp_status = 'uncertain' "
            "OR (publication_timestamp_status = 'unavailable' AND published_at IS NULL)",
            name=op.f("ck_tail_radar_research_sources_publication_timestamp"),
        ),
        sa.CheckConstraint(
            "(availability_at_as_of IN ('available_at_as_of', 'published_after_as_of') "
            "AND publication_timestamp_status = 'verified') OR "
            "(availability_at_as_of = 'uncertain_at_as_of' "
            "AND publication_timestamp_status <> 'verified')",
            name=op.f("ck_tail_radar_research_sources_availability_timestamp"),
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR published_at <= retrieved_at",
            name=op.f("ck_tail_radar_research_sources_publication_retrieval_order"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(relationship_claim_ids) = 'array'",
            name=op.f("ck_tail_radar_research_sources_claim_relationships_array"),
        ),
        sa.ForeignKeyConstraint(
            ["research_id"],
            ["tail_radar_research_analyses.research_id"],
            name=op.f("fk_tail_radar_research_sources_research_id_tail_radar_research_analyses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_id", name=op.f("pk_tail_radar_research_sources")),
        sa.UniqueConstraint(
            "research_id",
            "url",
            name="uq_tail_radar_research_source_url",
        ),
    )
    op.create_index(
        "ix_tail_radar_research_sources_research_id",
        "tail_radar_research_sources",
        ["research_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tail_radar_research_sources_research_id",
        table_name="tail_radar_research_sources",
    )
    op.drop_table("tail_radar_research_sources")
    op.drop_index(
        "uq_tail_radar_research_cached_identity",
        table_name="tail_radar_research_analyses",
        postgresql_where=sa.text("is_forced = false"),
    )
    op.drop_index(
        "ix_tail_radar_research_candidate_as_of",
        table_name="tail_radar_research_analyses",
    )
    op.drop_table("tail_radar_research_analyses")
