"""Create point-in-time market snapshot execution persistence.

Revision ID: 20260829_0002
Revises: 20260828_0001
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260829_0002"
down_revision: str | None = "20260828_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

snapshot_manifest_status = postgresql.ENUM(
    "AVAILABLE",
    name="snapshot_manifest_status",
    create_type=False,
)


def upgrade() -> None:
    op.add_column("execution_runs", sa.Column("trade_date", sa.Date(), nullable=True))
    op.add_column(
        "execution_runs",
        sa.Column("is_official", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "execution_runs",
        sa.Column("rerun_of_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_execution_runs_trade_date_matches_intended_time"),
        "execution_runs",
        "trade_date IS NULL OR "
        "trade_date = (intended_execution_time AT TIME ZONE 'Asia/Shanghai')::date",
    )
    op.create_foreign_key(
        op.f("fk_execution_runs_rerun_of_run_id_execution_runs"),
        "execution_runs",
        "execution_runs",
        ["rerun_of_run_id"],
        ["run_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_execution_runs_rerun_of_run_id",
        "execution_runs",
        ["rerun_of_run_id"],
        unique=False,
    )
    op.create_index(
        "uq_execution_runs_official_logical_key",
        "execution_runs",
        ["job_type", "trade_date", "intended_execution_time", "implementation_version"],
        unique=True,
        postgresql_where=sa.text("is_official AND trade_date IS NOT NULL"),
    )

    snapshot_manifest_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "market_snapshot_manifests",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("intended_snapshot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_fetch_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_fetch_finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("provider_version", sa.String(length=128), nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("quality_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", snapshot_manifest_status, nullable=False),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_market_snapshot_manifests_checksum_sha256_format"),
        ),
        sa.CheckConstraint(
            "actual_fetch_finished_at >= actual_fetch_started_at",
            name=op.f("ck_market_snapshot_manifests_fetch_timing_ordered"),
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name=op.f("ck_market_snapshot_manifests_latency_non_negative"),
        ),
        sa.CheckConstraint(
            "persisted_at >= actual_fetch_finished_at",
            name=op.f("ck_market_snapshot_manifests_persisted_after_fetch"),
        ),
        sa.CheckConstraint(
            "row_count > 0",
            name=op.f("ck_market_snapshot_manifests_row_count_positive"),
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name=op.f("ck_market_snapshot_manifests_schema_version_positive"),
        ),
        sa.CheckConstraint(
            "trade_date = (intended_snapshot_time AT TIME ZONE 'Asia/Shanghai')::date",
            name=op.f("ck_market_snapshot_manifests_trade_date_matches_intended_time"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["execution_runs.run_id"],
            name=op.f("fk_market_snapshot_manifests_run_id_execution_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", name=op.f("pk_market_snapshot_manifests")),
        sa.UniqueConstraint("run_id", name=op.f("uq_market_snapshot_manifests_run_id")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_market_snapshot_manifests_storage_key")),
    )
    op.create_index(
        "ix_market_snapshot_manifests_trade_date_intended_time",
        "market_snapshot_manifests",
        ["trade_date", "intended_snapshot_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_snapshot_manifests_trade_date_intended_time",
        table_name="market_snapshot_manifests",
    )
    op.drop_table("market_snapshot_manifests")
    snapshot_manifest_status.drop(op.get_bind(), checkfirst=True)
    op.drop_index("uq_execution_runs_official_logical_key", table_name="execution_runs")
    op.drop_index("ix_execution_runs_rerun_of_run_id", table_name="execution_runs")
    op.drop_constraint(
        op.f("fk_execution_runs_rerun_of_run_id_execution_runs"),
        "execution_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_execution_runs_trade_date_matches_intended_time"),
        "execution_runs",
        type_="check",
    )
    op.drop_column("execution_runs", "rerun_of_run_id")
    op.drop_column("execution_runs", "is_official")
    op.drop_column("execution_runs", "trade_date")
