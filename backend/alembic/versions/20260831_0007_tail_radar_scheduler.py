"""Create durable Tail Radar worker schedule state.

Revision ID: 20260831_0007
Revises: 20260831_0006
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0007"
down_revision: str | None = "20260831_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tail_radar_schedules",
        sa.Column("schedule_id", sa.UUID(), nullable=False),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("schedule_version", sa.String(length=64), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("intended_snapshot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_trading_day", sa.Boolean(), nullable=False),
        sa.Column("calendar_provider", sa.String(length=128), nullable=False),
        sa.Column("preflight_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preflight_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preflight_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column(
            "error_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
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
            "status IN ('scheduled', 'preflight_ready', 'preflight_degraded', "
            "'executing', 'succeeded', 'partial_success', 'failed', 'missed', "
            "'not_trading_day')",
            name=op.f("ck_tail_radar_schedules_status_valid"),
        ),
        sa.CheckConstraint(
            "preflight_finished_at IS NULL OR preflight_started_at IS NOT NULL",
            name=op.f("ck_tail_radar_schedules_preflight_finish_requires_start"),
        ),
        sa.CheckConstraint(
            "preflight_finished_at IS NULL OR preflight_finished_at >= preflight_started_at",
            name=op.f("ck_tail_radar_schedules_preflight_timing_order"),
        ),
        sa.CheckConstraint(
            "execution_finished_at IS NULL OR execution_started_at IS NULL OR "
            "execution_finished_at >= execution_started_at",
            name=op.f("ck_tail_radar_schedules_execution_timing_order"),
        ),
        sa.CheckConstraint(
            "status <> 'executing' OR execution_started_at IS NOT NULL",
            name=op.f("ck_tail_radar_schedules_executing_requires_start"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('succeeded', 'partial_success') OR "
            "(workflow_run_id IS NOT NULL AND execution_finished_at IS NOT NULL)",
            name=op.f("ck_tail_radar_schedules_completion_requires_provenance"),
        ),
        sa.CheckConstraint(
            "status <> 'missed' OR workflow_run_id IS NULL",
            name=op.f("ck_tail_radar_schedules_missed_has_no_workflow"),
        ),
        sa.CheckConstraint(
            "status <> 'not_trading_day' OR is_trading_day = false",
            name=op.f("ck_tail_radar_schedules_calendar_status_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["tail_radar_workflows.workflow_run_id"],
            name=op.f("fk_tail_radar_schedules_workflow_run_id_tail_radar_workflows"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("schedule_id", name=op.f("pk_tail_radar_schedules")),
        sa.UniqueConstraint(
            "job_name",
            "trade_date",
            "schedule_version",
            name="uq_tail_radar_schedules_logical_day",
        ),
        sa.UniqueConstraint(
            "workflow_run_id",
            name=op.f("uq_tail_radar_schedules_workflow_run_id"),
        ),
    )
    op.create_index(
        "ix_tail_radar_schedules_status",
        "tail_radar_schedules",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_tail_radar_schedules_trade_date",
        "tail_radar_schedules",
        ["trade_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tail_radar_schedules_trade_date", table_name="tail_radar_schedules")
    op.drop_index("ix_tail_radar_schedules_status", table_name="tail_radar_schedules")
    op.drop_table("tail_radar_schedules")
