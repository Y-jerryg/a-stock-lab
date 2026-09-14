"""Allow explicit completed-with-warnings scan status."""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0011"
down_revision = "20260913_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("trend_scan_runs", "status", existing_type=sa.String(16), type_=sa.String(32))


def downgrade() -> None:
    # An older application cannot interpret partial completion as an authoritative success.
    op.execute("""
        UPDATE trend_scan_runs SET status = 'failed',
            payload = payload || '{"status":"failed","error_message":"partial_scan_legacy"}'::jsonb
        WHERE status = 'completed_with_warnings'
    """)
    op.alter_column("trend_scan_runs", "status", existing_type=sa.String(32), type_=sa.String(16))
