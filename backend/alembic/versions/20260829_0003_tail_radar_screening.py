"""Create deterministic Tail Radar run and candidate persistence.

Revision ID: 20260829_0003
Revises: 20260829_0002
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260829_0003"
down_revision: str | None = "20260829_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tail_radar_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("screening_rule_version", sa.String(length=64), nullable=False),
        sa.Column(
            "rule_configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("evaluated_record_count", sa.Integer(), nullable=True),
        sa.Column("invalid_record_count", sa.Integer(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "candidate_count IS NULL OR candidate_count >= 0",
            name=op.f("ck_tail_radar_runs_candidate_count_non_negative"),
        ),
        sa.CheckConstraint(
            "(evaluated_record_count IS NULL AND invalid_record_count IS NULL "
            "AND candidate_count IS NULL) OR "
            "(evaluated_record_count IS NOT NULL AND invalid_record_count IS NOT NULL "
            "AND candidate_count IS NOT NULL)",
            name=op.f("ck_tail_radar_runs_counts_finalized_together"),
        ),
        sa.CheckConstraint(
            "evaluated_record_count IS NULL OR evaluated_record_count >= 0",
            name=op.f("ck_tail_radar_runs_evaluated_count_non_negative"),
        ),
        sa.CheckConstraint(
            "invalid_record_count IS NULL OR invalid_record_count >= 0",
            name=op.f("ck_tail_radar_runs_invalid_count_non_negative"),
        ),
        sa.CheckConstraint(
            "evaluated_record_count IS NULL OR "
            "invalid_record_count + candidate_count <= evaluated_record_count",
            name=op.f("ck_tail_radar_runs_counts_within_evaluated"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["execution_runs.run_id"],
            name=op.f("fk_tail_radar_runs_run_id_execution_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["market_snapshot_manifests.snapshot_id"],
            name=op.f("fk_tail_radar_runs_snapshot_id_market_snapshot_manifests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_tail_radar_runs")),
        sa.UniqueConstraint(
            "run_id",
            "snapshot_id",
            name="uq_tail_radar_runs_run_snapshot",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "screening_rule_version",
            name="uq_tail_radar_runs_snapshot_rule_version",
        ),
    )
    op.create_index(
        "ix_tail_radar_runs_snapshot_id",
        "tail_radar_runs",
        ["snapshot_id"],
        unique=False,
    )

    op.create_table(
        "tail_radar_candidates",
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=6), nullable=False),
        sa.CheckConstraint(
            "symbol ~ '^[0-9]{6}$'",
            name=op.f("ck_tail_radar_candidates_symbol_format"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["research_artifacts.artifact_id"],
            name=op.f("fk_tail_radar_candidates_candidate_id_research_artifacts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "snapshot_id"],
            ["tail_radar_runs.run_id", "tail_radar_runs.snapshot_id"],
            name="fk_tail_radar_candidates_run_snapshot_tail_radar_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("candidate_id", name=op.f("pk_tail_radar_candidates")),
        sa.UniqueConstraint(
            "run_id",
            "symbol",
            name="uq_tail_radar_candidates_run_symbol",
        ),
    )
    op.create_index(
        "ix_tail_radar_candidates_snapshot_symbol",
        "tail_radar_candidates",
        ["snapshot_id", "symbol"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tail_radar_candidates_snapshot_symbol",
        table_name="tail_radar_candidates",
    )
    op.drop_table("tail_radar_candidates")
    op.drop_index("ix_tail_radar_runs_snapshot_id", table_name="tail_radar_runs")
    op.drop_table("tail_radar_runs")
