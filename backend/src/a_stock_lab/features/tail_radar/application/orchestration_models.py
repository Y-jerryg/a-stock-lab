from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from a_stock_lab.core.time import as_market_timezone
from a_stock_lab.shared.execution.models import RunStatus

TAIL_RADAR_WORKFLOW_JOB_TYPE = "tail_radar.application"
TAIL_RADAR_WORKFLOW_VERSION = "tail-radar-workflow-v2"


class TailRadarWorkflowLifecycle(StrEnum):
    CLAIMED = "claimed"
    SNAPSHOT_RUNNING = "snapshot_running"
    SCREENING_RUNNING = "screening_running"
    CANDIDATE_ANALYSIS_RUNNING = "candidate_analysis_running"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class TailRadarCandidateStageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    NO_EVIDENCE = "no_evidence"
    FAILED = "failed"


class TailRadarWorkflowDisposition(StrEnum):
    CREATED = "created"
    RESUMED = "resumed"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class TailRadarWorkflowData(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_run_id: UUID
    trade_date: date
    intended_snapshot_time: AwareDatetime
    analysis_as_of: AwareDatetime | None
    workflow_version: str = Field(min_length=1, max_length=64)
    lifecycle: TailRadarWorkflowLifecycle
    execution_status: RunStatus
    snapshot_run_id: UUID | None
    snapshot_id: UUID | None
    screening_run_id: UUID | None
    candidate_count: int | None = Field(default=None, ge=0)
    technical_succeeded_count: int = Field(ge=0)
    technical_failed_count: int = Field(ge=0)
    technical_pending_count: int = Field(ge=0)
    research_succeeded_count: int = Field(ge=0)
    research_no_evidence_count: int = Field(ge=0)
    research_failed_count: int = Field(ge=0)
    research_pending_count: int = Field(ge=0)
    error_stage: str | None = Field(default=None, max_length=64)
    error_code: str | None = Field(default=None, max_length=128)
    actual_started_at: AwareDatetime
    actual_finished_at: AwareDatetime | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator(
        "intended_snapshot_time",
        "analysis_as_of",
        "actual_started_at",
        "actual_finished_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def normalize_timestamps(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @model_validator(mode="after")
    def lifecycle_is_coherent(self) -> "TailRadarWorkflowData":
        if self.trade_date != self.intended_snapshot_time.date():
            raise ValueError("workflow trade date must match its intended snapshot time")
        if self.analysis_as_of is not None and self.analysis_as_of.date() != self.trade_date:
            raise ValueError("workflow analysis_as_of must be on the trade date")
        if self.actual_finished_at is not None and self.actual_finished_at < self.actual_started_at:
            raise ValueError("workflow finish cannot precede its start")
        terminal = self.lifecycle in {
            TailRadarWorkflowLifecycle.SUCCEEDED,
            TailRadarWorkflowLifecycle.PARTIAL_SUCCESS,
            TailRadarWorkflowLifecycle.FAILED,
        }
        if terminal != (self.actual_finished_at is not None):
            raise ValueError("workflow terminal lifecycle must agree with its finish timestamp")
        if self.lifecycle is TailRadarWorkflowLifecycle.FAILED:
            if self.execution_status is not RunStatus.FAILED or not self.error_code:
                raise ValueError("failed workflow requires failed execution metadata")
        elif terminal and self.execution_status is not RunStatus.SUCCEEDED:
            raise ValueError("completed workflow requires succeeded execution metadata")
        elif not terminal and self.execution_status is not RunStatus.RUNNING:
            raise ValueError("active workflow requires running execution metadata")
        if self.screening_run_id is not None and (
            self.snapshot_run_id is None or self.snapshot_id is None or self.analysis_as_of is None
        ):
            raise ValueError("screening linkage requires snapshot and analysis provenance")
        counts = (
            self.technical_succeeded_count
            + self.technical_failed_count
            + self.technical_pending_count
        )
        research_counts = (
            self.research_succeeded_count
            + self.research_no_evidence_count
            + self.research_failed_count
            + self.research_pending_count
        )
        if self.candidate_count is not None and (
            counts != self.candidate_count or research_counts != self.candidate_count
        ):
            raise ValueError("workflow stage counts must cover every candidate")
        return self


class TailRadarWorkflowClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow: TailRadarWorkflowData
    created: bool


class TailRadarWorkflowCandidateState(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_run_id: UUID
    candidate_id: UUID
    technical_status: TailRadarCandidateStageStatus
    research_status: TailRadarCandidateStageStatus
    intraday_analysis_id: UUID | None
    research_id: UUID | None
    technical_error_code: str | None
    research_error_code: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)

    @model_validator(mode="after")
    def stage_links_are_coherent(self) -> "TailRadarWorkflowCandidateState":
        if (self.technical_status is TailRadarCandidateStageStatus.SUCCEEDED) != (
            self.intraday_analysis_id is not None
        ):
            raise ValueError("technical success must agree with its artifact")
        if self.technical_status is TailRadarCandidateStageStatus.FAILED:
            if not self.technical_error_code:
                raise ValueError("technical failure requires an error code")
        elif self.technical_error_code is not None:
            raise ValueError("non-failed technical stage cannot have an error code")
        research_success = self.research_status in {
            TailRadarCandidateStageStatus.SUCCEEDED,
            TailRadarCandidateStageStatus.NO_EVIDENCE,
        }
        if research_success != (self.research_id is not None):
            raise ValueError("research success must agree with its analysis")
        if self.research_status is TailRadarCandidateStageStatus.FAILED:
            if not self.research_error_code:
                raise ValueError("research failure requires an error code")
        elif self.research_error_code is not None:
            raise ValueError("non-failed research stage cannot have an error code")
        return self


class TailRadarWorkflowResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    disposition: TailRadarWorkflowDisposition
    workflow: TailRadarWorkflowData
