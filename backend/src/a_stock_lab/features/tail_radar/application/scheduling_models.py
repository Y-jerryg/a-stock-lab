from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from a_stock_lab.core.time import as_market_timezone

TAIL_RADAR_SCHEDULE_JOB_NAME = "tail_radar.official_1430"
TAIL_RADAR_SCHEDULE_VERSION = "tail-radar-schedule-v1"


class TailRadarScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    PREFLIGHT_READY = "preflight_ready"
    PREFLIGHT_DEGRADED = "preflight_degraded"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    MISSED = "missed"
    NOT_TRADING_DAY = "not_trading_day"


class TailRadarPreflightReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_available: bool
    trading_day: bool
    calendar_provider: str = Field(min_length=1, max_length=128)
    quote_provider: str = Field(min_length=1, max_length=128)
    full_snapshot_capability: bool
    intraday_capability: bool
    openai_configured: bool
    notes: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return (
            self.database_available
            and self.trading_day
            and self.full_snapshot_capability
            and self.intraday_capability
        )


class TailRadarScheduleData(BaseModel):
    model_config = ConfigDict(frozen=True)

    schedule_id: UUID
    job_name: str = Field(min_length=1, max_length=128)
    schedule_version: str = Field(min_length=1, max_length=64)
    trade_date: date
    intended_snapshot_time: AwareDatetime
    status: TailRadarScheduleStatus
    is_trading_day: bool
    calendar_provider: str = Field(min_length=1, max_length=128)
    preflight_started_at: AwareDatetime | None = None
    preflight_finished_at: AwareDatetime | None = None
    preflight_report: TailRadarPreflightReport | None = None
    workflow_run_id: UUID | None = None
    execution_started_at: AwareDatetime | None = None
    execution_finished_at: AwareDatetime | None = None
    error_code: str | None = Field(default=None, max_length=128)
    error_details: dict[str, object] = Field(default_factory=dict)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator(
        "intended_snapshot_time",
        "preflight_started_at",
        "preflight_finished_at",
        "execution_started_at",
        "execution_finished_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def normalize_timestamps(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @model_validator(mode="after")
    def schedule_is_coherent(self) -> "TailRadarScheduleData":
        if self.trade_date != self.intended_snapshot_time.date():
            raise ValueError("schedule trade date must match intended snapshot time")
        if self.preflight_finished_at is not None and self.preflight_started_at is None:
            raise ValueError("preflight finish requires a start")
        if (
            self.preflight_started_at is not None
            and self.preflight_finished_at is not None
            and self.preflight_finished_at < self.preflight_started_at
        ):
            raise ValueError("preflight finish cannot precede its start")
        if self.execution_finished_at is not None and self.execution_started_at is not None:
            if self.execution_finished_at < self.execution_started_at:
                raise ValueError("execution finish cannot precede its start")
        if self.status is TailRadarScheduleStatus.NOT_TRADING_DAY and self.is_trading_day:
            raise ValueError("not-trading-day status conflicts with calendar evidence")
        if self.status is TailRadarScheduleStatus.EXECUTING and self.execution_started_at is None:
            raise ValueError("executing schedule requires an execution start")
        if self.status in {
            TailRadarScheduleStatus.SUCCEEDED,
            TailRadarScheduleStatus.PARTIAL_SUCCESS,
        } and (self.workflow_run_id is None or self.execution_finished_at is None):
            raise ValueError("completed schedule requires workflow and finish provenance")
        if self.status is TailRadarScheduleStatus.MISSED and self.workflow_run_id is not None:
            raise ValueError("a missed capture cannot reference a workflow")
        return self


class TailRadarWorkerHeartbeat(BaseModel):
    model_config = ConfigDict(frozen=True)

    worker_id: UUID
    state: str = Field(min_length=1, max_length=32)
    updated_at: AwareDatetime
    last_schedule_status: TailRadarScheduleStatus | None = None
    last_error_code: str | None = Field(default=None, max_length=128)

    @field_validator("updated_at")
    @classmethod
    def normalize_updated_at(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)
