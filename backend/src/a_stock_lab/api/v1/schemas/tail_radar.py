from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateData,
    TailRadarRunData,
)
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.models import AShareExchange


class TailRadarRuleConfigurationResponse(BaseModel):
    pct_change_min: float
    pct_change_max: float
    exclude_st: bool
    minimum_amount: float | None
    minimum_float_market_cap: float | None
    maximum_float_market_cap: float | None
    allowed_exchanges: frozenset[AShareExchange] | None
    allowed_boards: frozenset[str] | None


class TailRadarRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    snapshot_id: UUID
    trade_date: date
    intended_snapshot_time: AwareDatetime
    actual_started_at: AwareDatetime
    actual_finished_at: AwareDatetime | None
    status: RunStatus
    screening_rule_version: str
    is_official: bool
    rule_configuration: TailRadarRuleConfigurationResponse
    evaluated_record_count: int | None
    invalid_record_count: int | None
    candidate_count: int | None
    error_code: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @classmethod
    def from_data(cls, data: TailRadarRunData) -> "TailRadarRunResponse":
        payload = data.model_dump(mode="python")
        payload["rule_configuration"] = data.rule_configuration.model_dump(mode="python")
        return cls.model_validate(payload)


class TailRadarRunListResponse(BaseModel):
    items: tuple[TailRadarRunResponse, ...]
    total: int
    page: int
    page_size: int


class TailRadarCandidateSummaryResponse(BaseModel):
    candidate_id: UUID
    run_id: UUID
    snapshot_id: UUID
    symbol: str
    exchange: AShareExchange | None
    name: str | None
    price: float
    pct_change: float
    as_of: AwareDatetime
    screening_rule_version: str

    @classmethod
    def from_data(cls, data: TailRadarCandidateData) -> "TailRadarCandidateSummaryResponse":
        record = data.payload.snapshot_record
        if record.price is None or record.pct_change is None:
            raise ValueError("persisted Tail Radar candidate lacks required price evidence")
        return cls(
            candidate_id=data.candidate_id,
            run_id=data.run_id,
            snapshot_id=data.snapshot_id,
            symbol=data.symbol,
            exchange=record.exchange,
            name=record.name,
            price=record.price,
            pct_change=record.pct_change,
            as_of=data.as_of,
            screening_rule_version=data.payload.screening_rule_version,
        )


class TailRadarCandidateListResponse(BaseModel):
    items: tuple[TailRadarCandidateSummaryResponse, ...]
    total: int
    page: int
    page_size: int


class SnapshotRecordResponse(BaseModel):
    symbol: str
    exchange: AShareExchange | None
    name: str | None
    price: float | None
    pct_change: float | None
    absolute_change: float | None
    open: float | None
    high: float | None
    low: float | None
    previous_close: float | None
    volume: float | None
    amount: float | None
    amplitude: float | None
    volume_ratio: float | None
    turnover_rate: float | None
    pe_dynamic: float | None
    pb: float | None
    total_market_cap: float | None
    float_market_cap: float | None
    provider: str
    provider_timestamp: AwareDatetime | None
    fetched_at: AwareDatetime


class SnapshotEvidenceResponse(BaseModel):
    snapshot_id: UUID
    snapshot_run_id: UUID
    trade_date: date
    intended_snapshot_time: AwareDatetime
    actual_fetch_started_at: AwareDatetime
    actual_fetch_finished_at: AwareDatetime
    provider: str
    provider_timestamp: AwareDatetime | None
    checksum_sha256: str
    snapshot_schema_version: int


class ScreeningDecisionResponse(BaseModel):
    outcome: Literal["included"]
    reason: Literal["pct_change_in_inclusive_range"]
    observed_pct_change: float
    observed_price: float
    inclusive_min: float
    inclusive_max: float


class TailRadarCandidateDetailResponse(BaseModel):
    candidate_id: UUID
    run_id: UUID
    snapshot_id: UUID
    symbol: str
    trade_date: date
    as_of: AwareDatetime
    screening_rule_version: str
    rule_configuration: TailRadarRuleConfigurationResponse
    snapshot_evidence: SnapshotEvidenceResponse
    snapshot_data: SnapshotRecordResponse
    decision: ScreeningDecisionResponse
    created_at: AwareDatetime

    @classmethod
    def from_data(cls, data: TailRadarCandidateData) -> "TailRadarCandidateDetailResponse":
        payload = data.payload
        decision = payload.decision
        if decision.observed_pct_change is None or decision.observed_price is None:
            raise ValueError("persisted Tail Radar candidate lacks decision evidence")
        return cls(
            candidate_id=data.candidate_id,
            run_id=data.run_id,
            snapshot_id=data.snapshot_id,
            symbol=data.symbol,
            trade_date=data.trade_date,
            as_of=data.as_of,
            screening_rule_version=payload.screening_rule_version,
            rule_configuration=TailRadarRuleConfigurationResponse.model_validate(
                payload.rule_configuration.model_dump(mode="python")
            ),
            snapshot_evidence=SnapshotEvidenceResponse.model_validate(
                payload.snapshot_evidence.model_dump(mode="python")
            ),
            snapshot_data=SnapshotRecordResponse.model_validate(
                payload.snapshot_record.model_dump(mode="python")
            ),
            decision=ScreeningDecisionResponse(
                outcome=decision.outcome,
                reason=decision.reason,
                observed_pct_change=decision.observed_pct_change,
                observed_price=decision.observed_price,
                inclusive_min=decision.inclusive_min,
                inclusive_max=decision.inclusive_max,
            ),
            created_at=data.created_at,
        )
