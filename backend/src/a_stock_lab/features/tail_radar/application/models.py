from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from a_stock_lab.core.time import as_market_timezone
from a_stock_lab.features.tail_radar.domain.screening import (
    TailRadarScreeningConfiguration,
    TailRadarScreeningDecision,
    TailRadarSnapshotEvidence,
)
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.models import MarketSnapshotRecord

TAIL_RADAR_CANDIDATE_ARTIFACT_SCHEMA_VERSION = 1
TAIL_RADAR_CANDIDATE_ARTIFACT_TYPE = "tail_radar.candidate"
TAIL_RADAR_JOB_TYPE = "tail_radar.screen"


def tail_radar_execution_version(*, screening_rule_version: str, snapshot_id: UUID) -> str:
    """Create the shared execution identity for one rule applied to one source snapshot."""
    value = f"{screening_rule_version}:{snapshot_id.hex}"
    if len(value) > 64:
        raise ValueError("Tail Radar execution identity exceeds the shared version limit")
    return value


class TailRadarExecutionDisposition(StrEnum):
    CREATED = "created"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class TailRadarRunData(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    snapshot_id: UUID
    trade_date: date
    intended_snapshot_time: AwareDatetime
    actual_started_at: AwareDatetime
    actual_finished_at: AwareDatetime | None = None
    status: RunStatus
    screening_rule_version: str = Field(min_length=1, max_length=64)
    is_official: bool
    rule_configuration: TailRadarScreeningConfiguration
    evaluated_record_count: int | None = Field(default=None, ge=0)
    invalid_record_count: int | None = Field(default=None, ge=0)
    candidate_count: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator(
        "intended_snapshot_time",
        "actual_started_at",
        "actual_finished_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def normalize_market_timestamps(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @model_validator(mode="after")
    def validate_run_state(self) -> "TailRadarRunData":
        if self.screening_rule_version != self.rule_configuration.rule_version:
            raise ValueError("screening rule version must match its configuration")
        counts = (
            self.evaluated_record_count,
            self.invalid_record_count,
            self.candidate_count,
        )
        if self.status is RunStatus.SUCCEEDED and any(value is None for value in counts):
            raise ValueError("a succeeded Tail Radar run requires finalized counts")
        if any(value is not None for value in counts) and any(value is None for value in counts):
            raise ValueError("Tail Radar run counts must be finalized together")
        if (
            self.evaluated_record_count is not None
            and self.invalid_record_count is not None
            and self.candidate_count is not None
            and self.invalid_record_count + self.candidate_count > self.evaluated_record_count
        ):
            raise ValueError("invalid and candidate counts cannot exceed evaluated records")
        if self.trade_date != self.intended_snapshot_time.date():
            raise ValueError("trade date must match intended snapshot time in Asia/Shanghai")
        if self.actual_finished_at is not None and self.actual_finished_at < self.actual_started_at:
            raise ValueError("run finish cannot precede run start")
        return self


class TailRadarRunClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    run: TailRadarRunData
    created: bool


class TailRadarCandidatePayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    screening_rule_version: str = Field(min_length=1, max_length=64)
    rule_configuration: TailRadarScreeningConfiguration
    snapshot_evidence: TailRadarSnapshotEvidence
    snapshot_record: MarketSnapshotRecord
    decision: TailRadarScreeningDecision

    @model_validator(mode="after")
    def validate_included_evidence(self) -> "TailRadarCandidatePayload":
        if self.screening_rule_version != self.rule_configuration.rule_version:
            raise ValueError("candidate screening rule version must match its configuration")
        if not self.decision.included:
            raise ValueError("candidate payload must represent an included decision")
        if (
            self.rule_configuration.pct_change_min != self.decision.inclusive_min
            or self.rule_configuration.pct_change_max != self.decision.inclusive_max
        ):
            raise ValueError("decision range must match its rule configuration")
        if self.snapshot_record.pct_change != self.decision.observed_pct_change:
            raise ValueError("decision percentage must match snapshot evidence")
        if self.snapshot_record.price != self.decision.observed_price:
            raise ValueError("decision price must match snapshot evidence")
        if self.snapshot_record.provider != self.snapshot_evidence.provider:
            raise ValueError("snapshot record provider must match its snapshot evidence")
        if not (
            self.snapshot_evidence.actual_fetch_started_at
            <= self.snapshot_record.fetched_at
            <= self.snapshot_evidence.actual_fetch_finished_at
        ):
            raise ValueError("snapshot record timestamp must fall within the source fetch window")
        return self


class TailRadarCandidateCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: UUID
    run_id: UUID
    snapshot_id: UUID
    symbol: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    as_of: AwareDatetime
    payload: TailRadarCandidatePayload

    @field_validator("as_of")
    @classmethod
    def normalize_as_of(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)

    @model_validator(mode="after")
    def validate_candidate_links(self) -> "TailRadarCandidateCreate":
        if self.snapshot_id != self.payload.snapshot_evidence.snapshot_id:
            raise ValueError("candidate snapshot must match its evidence")
        if self.symbol != self.payload.snapshot_record.symbol:
            raise ValueError("candidate symbol must match its snapshot record")
        if self.trade_date != self.payload.snapshot_evidence.trade_date:
            raise ValueError("candidate trade date must match its snapshot evidence")
        if self.as_of != self.payload.snapshot_evidence.as_of:
            raise ValueError("candidate as_of must equal the latest snapshot observation")
        return self


class TailRadarCandidateData(TailRadarCandidateCreate):
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)


class TailRadarScreeningResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    disposition: TailRadarExecutionDisposition
    run: TailRadarRunData


class TailRadarRunPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[TailRadarRunData, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class TailRadarCandidatePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[TailRadarCandidateData, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
