"""Create deterministic Tail Radar intraday feature persistence.

Revision ID: 20260829_0004
Revises: 20260829_0003
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260829_0004"
down_revision: str | None = "20260829_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_tail_radar_candidates_analysis_source",
        "tail_radar_candidates",
        ["candidate_id", "run_id", "snapshot_id", "symbol"],
    )
    op.create_table(
        "tail_radar_intraday_analyses",
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=6), nullable=False),
        sa.Column("analysis_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculation_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "symbol ~ '^[0-9]{6}$'",
            name=op.f("ck_tail_radar_intraday_analyses_symbol_format"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["research_artifacts.artifact_id"],
            name=op.f("fk_tail_radar_intraday_analyses_analysis_id_research_artifacts"),
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
            name="fk_tail_radar_intraday_analysis_candidate_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "analysis_id",
            name=op.f("pk_tail_radar_intraday_analyses"),
        ),
        sa.UniqueConstraint(
            "candidate_id",
            "analysis_as_of",
            "calculation_version",
            name="uq_tail_radar_intraday_candidate_as_of_version",
        ),
    )
    op.create_index(
        "ix_tail_radar_intraday_candidate_as_of",
        "tail_radar_intraday_analyses",
        ["candidate_id", "analysis_as_of"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tail_radar_intraday_candidate_as_of",
        table_name="tail_radar_intraday_analyses",
    )
    op.drop_table("tail_radar_intraday_analyses")
    op.drop_constraint(
        "uq_tail_radar_candidates_analysis_source",
        "tail_radar_candidates",
        type_="unique",
    )
