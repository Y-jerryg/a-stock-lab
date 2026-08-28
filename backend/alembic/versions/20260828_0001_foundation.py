"""Create shared research artifact and execution run tables.

Revision ID: 20260828_0001
Revises:
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260828_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

run_status = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    name="execution_run_status",
    create_type=False,
)


def upgrade() -> None:
    run_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "execution_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=128), nullable=False),
        sa.Column("intended_execution_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", run_status, nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=True),
        sa.Column("implementation_version", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_execution_runs")),
    )
    op.create_index(
        "ix_execution_runs_job_type_intended_time",
        "execution_runs",
        ["job_type", "intended_execution_time"],
        unique=False,
    )
    op.create_table(
        "research_artifacts",
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "schema_version > 0", name=op.f("ck_research_artifacts_schema_version_positive")
        ),
        sa.PrimaryKeyConstraint("artifact_id", name=op.f("pk_research_artifacts")),
    )
    op.create_index(
        "ix_research_artifacts_module_as_of",
        "research_artifacts",
        ["module", "as_of"],
        unique=False,
    )
    op.create_index(
        "ix_research_artifacts_symbol_trade_date",
        "research_artifacts",
        ["symbol", "trade_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_research_artifacts_symbol_trade_date", table_name="research_artifacts")
    op.drop_index("ix_research_artifacts_module_as_of", table_name="research_artifacts")
    op.drop_table("research_artifacts")
    op.drop_index("ix_execution_runs_job_type_intended_time", table_name="execution_runs")
    op.drop_table("execution_runs")
    run_status.drop(op.get_bind(), checkfirst=True)
