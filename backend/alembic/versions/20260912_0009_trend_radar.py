"""Add local Trend Radar evidence, cache and result history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260912_0009"
down_revision: str | None = "20260831_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trend_scan_runs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("trade_date", sa.Date()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_trend_scan_runs_status_started", "trend_scan_runs", ["status", "started_at"]
    )
    op.create_table(
        "trend_daily_heat",
        sa.Column("run_id", sa.UUID(), sa.ForeignKey("trend_scan_runs.id"), primary_key=True),
        sa.Column("symbol", sa.String(6), primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_trend_daily_heat_trade_date", "trend_daily_heat", ["trade_date"])
    op.create_table(
        "trend_daily_bars",
        sa.Column("symbol", sa.String(6), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("vintage_date", sa.Date(), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "trend_scan_results",
        sa.Column("run_id", sa.UUID(), sa.ForeignKey("trend_scan_runs.id"), primary_key=True),
        sa.Column("symbol", sa.String(6), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("input_bars", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    for table in ("trend_scan_results", "trend_daily_bars", "trend_daily_heat", "trend_scan_runs"):
        op.drop_table(table)
