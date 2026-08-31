"""Create resumable complete Tail Radar workflow lifecycle.

Revision ID: 20260831_0006
Revises: 20260830_0005
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0006"
down_revision: str | None = "20260830_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tail_radar_workflows",
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("workflow_version", sa.String(length=64), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("analysis_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_run_id", sa.UUID(), nullable=True),
        sa.Column("snapshot_id", sa.UUID(), nullable=True),
        sa.Column("screening_run_id", sa.UUID(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.Column("technical_succeeded_count", sa.Integer(), nullable=False),
        sa.Column("technical_failed_count", sa.Integer(), nullable=False),
        sa.Column("technical_pending_count", sa.Integer(), nullable=False),
        sa.Column("research_succeeded_count", sa.Integer(), nullable=False),
        sa.Column("research_no_evidence_count", sa.Integer(), nullable=False),
        sa.Column("research_failed_count", sa.Integer(), nullable=False),
        sa.Column("research_pending_count", sa.Integer(), nullable=False),
        sa.Column("error_stage", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
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
            "lifecycle IN ('claimed', 'snapshot_running', 'screening_running', "
            "'candidate_analysis_running', 'succeeded', 'partial_success', 'failed')",
            name=op.f("ck_tail_radar_workflows_lifecycle_valid"),
        ),
        sa.CheckConstraint(
            "candidate_count IS NULL OR candidate_count >= 0",
            name=op.f("ck_tail_radar_workflows_candidate_count_non_negative"),
        ),
        sa.CheckConstraint(
            "technical_succeeded_count >= 0 AND technical_failed_count >= 0 "
            "AND technical_pending_count >= 0 AND research_succeeded_count >= 0 "
            "AND research_no_evidence_count >= 0 AND research_failed_count >= 0 "
            "AND research_pending_count >= 0",
            name=op.f("ck_tail_radar_workflows_stage_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "candidate_count IS NULL OR "
            "(technical_succeeded_count + technical_failed_count + "
            "technical_pending_count = candidate_count AND "
            "research_succeeded_count + research_no_evidence_count + "
            "research_failed_count + research_pending_count = candidate_count)",
            name=op.f("ck_tail_radar_workflows_stage_counts_cover_candidates"),
        ),
        sa.CheckConstraint(
            "screening_run_id IS NULL OR "
            "(snapshot_run_id IS NOT NULL AND snapshot_id IS NOT NULL "
            "AND analysis_as_of IS NOT NULL)",
            name=op.f("ck_tail_radar_workflows_screening_requires_provenance"),
        ),
        sa.ForeignKeyConstraint(
            ["screening_run_id"],
            ["tail_radar_runs.run_id"],
            name=op.f("fk_tail_radar_workflows_screening_run_id_tail_radar_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["market_snapshot_manifests.snapshot_id"],
            name=op.f("fk_tail_radar_workflows_snapshot_id_market_snapshot_manifests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_run_id"],
            ["execution_runs.run_id"],
            name=op.f("fk_tail_radar_workflows_snapshot_run_id_execution_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["execution_runs.run_id"],
            name=op.f("fk_tail_radar_workflows_workflow_run_id_execution_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workflow_run_id", name=op.f("pk_tail_radar_workflows")),
        sa.UniqueConstraint(
            "screening_run_id",
            name="uq_tail_radar_workflows_screening_run",
        ),
    )
    op.create_index(
        "ix_tail_radar_workflows_snapshot_id",
        "tail_radar_workflows",
        ["snapshot_id"],
        unique=False,
    )
    op.create_table(
        "tail_radar_workflow_candidates",
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("technical_status", sa.String(length=32), nullable=False),
        sa.Column("research_status", sa.String(length=32), nullable=False),
        sa.Column("intraday_analysis_id", sa.UUID(), nullable=True),
        sa.Column("research_id", sa.UUID(), nullable=True),
        sa.Column("technical_error_code", sa.String(length=128), nullable=True),
        sa.Column("research_error_code", sa.String(length=128), nullable=True),
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
            "technical_status IN ('pending', 'running', 'succeeded', 'failed')",
            name=op.f("ck_tail_radar_workflow_candidates_technical_status_valid"),
        ),
        sa.CheckConstraint(
            "research_status IN ('pending', 'running', 'succeeded', 'no_evidence', 'failed')",
            name=op.f("ck_tail_radar_workflow_candidates_research_status_valid"),
        ),
        sa.CheckConstraint(
            "(technical_status = 'succeeded' AND intraday_analysis_id IS NOT NULL "
            "AND technical_error_code IS NULL) OR "
            "(technical_status = 'failed' AND intraday_analysis_id IS NULL "
            "AND technical_error_code IS NOT NULL) OR "
            "(technical_status IN ('pending', 'running') AND intraday_analysis_id IS NULL "
            "AND technical_error_code IS NULL)",
            name=op.f("ck_tail_radar_workflow_candidates_technical_stage_state"),
        ),
        sa.CheckConstraint(
            "(research_status IN ('succeeded', 'no_evidence') AND research_id IS NOT NULL "
            "AND research_error_code IS NULL) OR "
            "(research_status = 'failed' AND research_id IS NULL "
            "AND research_error_code IS NOT NULL) OR "
            "(research_status IN ('pending', 'running') AND research_id IS NULL "
            "AND research_error_code IS NULL)",
            name=op.f("ck_tail_radar_workflow_candidates_research_stage_state"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["tail_radar_candidates.candidate_id"],
            name=op.f("fk_tail_radar_workflow_candidates_candidate_id_tail_radar_candidates"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["intraday_analysis_id"],
            ["tail_radar_intraday_analyses.analysis_id"],
            name=op.f(
                "fk_tail_radar_workflow_candidates_intraday_analysis_id_tail_radar_intraday_analyses"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["research_id"],
            ["tail_radar_research_analyses.research_id"],
            name=op.f("fk_tail_radar_workflow_candidates_research_id_tail_radar_research_analyses"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["tail_radar_workflows.workflow_run_id"],
            name=op.f("fk_tail_radar_workflow_candidates_workflow_run_id_tail_radar_workflows"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workflow_run_id",
            "candidate_id",
            name=op.f("pk_tail_radar_workflow_candidates"),
        ),
    )
    op.create_index(
        "ix_tail_radar_workflow_candidates_candidate",
        "tail_radar_workflow_candidates",
        ["candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tail_radar_workflow_candidates_candidate",
        table_name="tail_radar_workflow_candidates",
    )
    op.drop_table("tail_radar_workflow_candidates")
    op.drop_index(
        "ix_tail_radar_workflows_snapshot_id",
        table_name="tail_radar_workflows",
    )
    op.drop_table("tail_radar_workflows")
