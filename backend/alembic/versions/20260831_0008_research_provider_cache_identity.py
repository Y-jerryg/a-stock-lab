"""Align the paid research cache index with provider-aware identity.

Revision ID: 20260831_0008
Revises: 20260831_0007
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0008"
down_revision: str | None = "20260831_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "uq_tail_radar_research_cached_identity",
        table_name="tail_radar_research_analyses",
        postgresql_where=sa.text("is_forced = false"),
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


def downgrade() -> None:
    op.drop_index(
        "uq_tail_radar_research_cached_identity",
        table_name="tail_radar_research_analyses",
        postgresql_where=sa.text("is_forced = false"),
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
