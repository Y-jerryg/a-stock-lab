"""Coordinate scheduled Trend Radar scans locally, independent of a cloud queue."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0010"
down_revision: str | None = "20260912_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trend_schedule_claims",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column(
            "run_id", sa.UUID(), sa.ForeignKey("trend_scan_runs.id"), nullable=False, unique=True
        ),
    )
    # Preserve earlier scheduled identities, including failed attempts. No historical data deletion.
    op.execute("""
        INSERT INTO trend_schedule_claims(trade_date, run_id)
        SELECT DISTINCT ON (trade_date) trade_date, id FROM trend_scan_runs
        WHERE payload->>'trigger_type' = 'scheduled' AND trade_date IS NOT NULL
        ORDER BY trade_date, started_at, id
    """)


def downgrade() -> None:
    op.drop_table("trend_schedule_claims")
