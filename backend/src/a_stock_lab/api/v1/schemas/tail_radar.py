from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from a_stock_lab.features.tail_radar.application.intraday_models import (
    TailRadarIntradayAnalysisData,
)
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateData,
    TailRadarRunData,
)
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TailRadarWorkflowCandidateState,
    TailRadarWorkflowData,
)
from a_stock_lab.features.tail_radar.application.query_models import (
    TailRadarCandidateOverviewData,
)
from a_stock_lab.features.tail_radar.application.research_models import TailRadarResearchData
from a_stock_lab.features.tail_radar.domain.research import TailRadarResearchClaim
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.models import AShareExchange, SnapshotQualityReport
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest


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
    amount: float | None
    turnover_rate: float | None
    as_of: AwareDatetime
    screening_rule_version: str
    intraday_position: float | None = None
    distance_from_high_pct: float | None = None
    previous_5m_return_pct: float | None = None
    previous_15m_return_pct: float | None = None
    previous_30m_return_pct: float | None = None
    technical_status: Literal["pending", "running", "succeeded", "failed"] | None = None
    research_status: Literal["pending", "running", "succeeded", "no_evidence", "failed"] | None = (
        None
    )

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
            amount=record.amount,
            turnover_rate=record.turnover_rate,
            as_of=data.as_of,
            screening_rule_version=data.payload.screening_rule_version,
        )

    @classmethod
    def from_overview(
        cls, data: TailRadarCandidateOverviewData
    ) -> "TailRadarCandidateSummaryResponse":
        response = cls.from_data(data.candidate)
        price = None if data.intraday_analysis is None else data.intraday_analysis.payload.price
        state = data.workflow_state
        return response.model_copy(
            update={
                "intraday_position": None if price is None else price.normalized_intraday_position,
                "distance_from_high_pct": (
                    None if price is None else price.distance_from_intraday_high_pct
                ),
                "previous_5m_return_pct": (None if price is None else price.previous_5m_return_pct),
                "previous_15m_return_pct": (
                    None if price is None else price.previous_15m_return_pct
                ),
                "previous_30m_return_pct": (
                    None if price is None else price.previous_30m_return_pct
                ),
                "technical_status": (None if state is None else state.technical_status.value),
                "research_status": None if state is None else state.research_status.value,
            }
        )


class TailRadarCandidateListResponse(BaseModel):
    items: tuple[TailRadarCandidateSummaryResponse, ...]
    total: int
    page: int
    page_size: int


class TailRadarWorkflowResponse(BaseModel):
    workflow_run_id: UUID
    workflow_version: str
    lifecycle: Literal[
        "claimed",
        "snapshot_running",
        "screening_running",
        "candidate_analysis_running",
        "succeeded",
        "partial_success",
        "failed",
    ]
    execution_status: RunStatus
    analysis_as_of: AwareDatetime | None
    candidate_count: int | None
    technical_succeeded_count: int
    technical_failed_count: int
    technical_pending_count: int
    research_succeeded_count: int
    research_no_evidence_count: int
    research_failed_count: int
    research_pending_count: int
    error_stage: str | None
    error_code: str | None
    actual_started_at: AwareDatetime
    actual_finished_at: AwareDatetime | None

    @classmethod
    def from_data(cls, data: TailRadarWorkflowData) -> "TailRadarWorkflowResponse":
        return cls.model_validate(data.model_dump(mode="python"))


class TailRadarSnapshotMetricsResponse(BaseModel):
    snapshot_run_id: UUID
    snapshot_id: UUID
    provider: str
    provider_version: str | None
    intended_snapshot_time: AwareDatetime
    actual_fetch_started_at: AwareDatetime
    actual_fetch_finished_at: AwareDatetime
    provider_timestamp: AwareDatetime | None
    persisted_at: AwareDatetime
    latency_ms: float
    row_count: int
    schema_version: int
    quality_report: SnapshotQualityReport

    @classmethod
    def from_data(cls, data: PersistedSnapshotManifest) -> "TailRadarSnapshotMetricsResponse":
        return cls(
            snapshot_run_id=data.run_id,
            snapshot_id=data.snapshot_id,
            provider=data.provider,
            provider_version=data.provider_version,
            intended_snapshot_time=data.intended_snapshot_time,
            actual_fetch_started_at=data.actual_fetch_started_at,
            actual_fetch_finished_at=data.actual_fetch_finished_at,
            provider_timestamp=data.provider_timestamp,
            persisted_at=data.persisted_at,
            latency_ms=data.latency_ms,
            row_count=data.row_count,
            schema_version=data.schema_version,
            quality_report=data.quality_report,
        )


class TailRadarRunSummaryResponse(BaseModel):
    run: TailRadarRunResponse
    workflow: TailRadarWorkflowResponse | None
    snapshot: TailRadarSnapshotMetricsResponse


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


class IntradayBarResponse(BaseModel):
    symbol: str
    interval_minutes: int
    ended_at: AwareDatetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    provider: str
    provider_timestamp: AwareDatetime | None
    fetched_at: AwareDatetime


class IntradayDataQualityResponse(BaseModel):
    status: Literal["good", "degraded", "invalid"]
    raw_bar_count: int = Field(ge=0)
    eligible_bar_count: int = Field(ge=0)
    used_bar_count: int = Field(ge=0)
    future_bar_count: int = Field(ge=0)
    duplicate_timestamp_count: int = Field(ge=0)
    missing_expected_bar_count: int = Field(ge=0)
    off_session_bar_count: int = Field(ge=0)
    normalization_issue_count: int = Field(ge=0)
    was_out_of_order: bool
    complete_from_market_open: bool
    issues: tuple[
        Literal[
            "no_eligible_bars",
            "future_bars_excluded",
            "duplicate_bar_timestamps",
            "out_of_order_bars",
            "missing_expected_bars",
            "malformed_provider_rows",
            "off_session_bars",
        ],
        ...,
    ]


class IntradayPriceFeaturesResponse(BaseModel):
    previous_5m_return_pct: float | None
    previous_15m_return_pct: float | None
    previous_30m_return_pct: float | None
    return_since_open_pct: float | None
    distance_from_intraday_high_pct: float | None
    distance_from_intraday_low_pct: float | None
    normalized_intraday_position: float | None
    drawdown_from_intraday_high_pct: float | None


class IntradayVolumeFeaturesResponse(BaseModel):
    recent_5m_volume: float | None
    previous_comparable_5m_volume: float | None
    recent_volume_acceleration_ratio: float | None
    recent_turnover_amount: float | None
    vwap: float | None
    distance_from_vwap_pct: float | None


class IntradayPathCharacteristicsResponse(BaseModel):
    steady_strengthening: bool | None
    late_acceleration: bool | None
    early_spike_followed_by_pullback: bool | None
    recovery_from_intraday_weakness: bool | None
    materially_below_earlier_intraday_peak: bool | None


class TailRadarIntradayAnalysisResponse(BaseModel):
    analysis_id: UUID
    candidate_id: UUID
    source_run_id: UUID
    source_snapshot_id: UUID
    symbol: str
    source_candidate_as_of: AwareDatetime
    analysis_as_of: AwareDatetime
    used_bars: tuple[IntradayBarResponse, ...] | None
    latest_bar_used: IntradayBarResponse | None
    feature_schema_version: int
    calculation_version: str
    provider: str
    provider_version: str | None
    data_quality: IntradayDataQualityResponse
    price: IntradayPriceFeaturesResponse
    volume: IntradayVolumeFeaturesResponse
    path: IntradayPathCharacteristicsResponse
    created_at: AwareDatetime

    @classmethod
    def from_data(cls, data: TailRadarIntradayAnalysisData) -> "TailRadarIntradayAnalysisResponse":
        payload = data.payload
        return cls(
            analysis_id=data.analysis_id,
            candidate_id=data.candidate_id,
            source_run_id=data.run_id,
            source_snapshot_id=data.snapshot_id,
            symbol=data.symbol,
            source_candidate_as_of=payload.source_candidate_as_of,
            analysis_as_of=data.analysis_as_of,
            used_bars=(
                None
                if payload.used_bars is None
                else tuple(
                    IntradayBarResponse.model_validate(bar.model_dump(mode="python"))
                    for bar in payload.used_bars
                )
            ),
            latest_bar_used=(
                None
                if payload.latest_bar_used is None
                else IntradayBarResponse.model_validate(
                    payload.latest_bar_used.model_dump(mode="python")
                )
            ),
            feature_schema_version=payload.feature_schema_version,
            calculation_version=payload.calculation_version,
            provider=payload.provider,
            provider_version=payload.provider_version,
            data_quality=IntradayDataQualityResponse.model_validate(
                payload.data_quality.model_dump(mode="python")
            ),
            price=IntradayPriceFeaturesResponse.model_validate(
                payload.price.model_dump(mode="python")
            ),
            volume=IntradayVolumeFeaturesResponse.model_validate(
                payload.volume.model_dump(mode="python")
            ),
            path=IntradayPathCharacteristicsResponse.model_validate(
                payload.path.model_dump(mode="python")
            ),
            created_at=data.created_at,
        )


class TailRadarResearchClaimResponse(BaseModel):
    claim_id: str
    statement: str
    classification: Literal[
        "verified_fact",
        "interpretation",
        "insufficient_evidence",
    ]
    source_ids: tuple[UUID, ...]


class TailRadarResearchSourceResponse(BaseModel):
    source_id: UUID
    url: str
    title: str | None
    publisher_domain: str
    published_at: AwareDatetime | None
    publication_timestamp_status: Literal["verified", "uncertain", "unavailable"]
    availability_at_as_of: Literal[
        "available_at_as_of",
        "published_after_as_of",
        "uncertain_at_as_of",
    ]
    retrieved_at: AwareDatetime
    relationship_claim_ids: tuple[str, ...]


class TailRadarWebResearchResponse(BaseModel):
    research_id: UUID
    candidate_id: UUID
    source_run_id: UUID
    source_snapshot_id: UUID
    symbol: str
    analysis_as_of: AwareDatetime
    status: Literal["succeeded", "no_evidence"]
    concise_summary: str
    verified_facts: tuple[TailRadarResearchClaimResponse, ...]
    likely_drivers: tuple[TailRadarResearchClaimResponse, ...]
    company_context: tuple[TailRadarResearchClaimResponse, ...]
    sector_context: tuple[TailRadarResearchClaimResponse, ...]
    market_context: tuple[TailRadarResearchClaimResponse, ...]
    positive_factors: tuple[TailRadarResearchClaimResponse, ...]
    risk_factors: tuple[TailRadarResearchClaimResponse, ...]
    unresolved_questions: tuple[str, ...]
    evidence_quality: Literal["high", "medium", "low", "insufficient"]
    confidence: float
    sources: tuple[TailRadarResearchSourceResponse, ...]
    provider: str
    model_identifier: str
    prompt_version: str
    created_at: AwareDatetime

    @classmethod
    def from_data(cls, data: TailRadarResearchData) -> "TailRadarWebResearchResponse":
        payload = data.payload
        if payload is None or data.status.value not in {"succeeded", "no_evidence"}:
            raise ValueError("public Tail Radar research must have a successful artifact")

        def claims(
            values: tuple[TailRadarResearchClaim, ...],
        ) -> tuple[TailRadarResearchClaimResponse, ...]:
            return tuple(
                TailRadarResearchClaimResponse.model_validate(value.model_dump(mode="python"))
                for value in values
            )

        return cls(
            research_id=data.research_id,
            candidate_id=data.candidate_id,
            source_run_id=data.run_id,
            source_snapshot_id=data.snapshot_id,
            symbol=data.symbol,
            analysis_as_of=data.analysis_as_of,
            status=data.status.value,
            concise_summary=payload.concise_summary,
            verified_facts=claims(payload.verified_facts),
            likely_drivers=claims(payload.likely_drivers),
            company_context=claims(payload.company_context),
            sector_context=claims(payload.sector_context),
            market_context=claims(payload.market_context),
            positive_factors=claims(payload.positive_factors),
            risk_factors=claims(payload.risk_factors),
            unresolved_questions=payload.unresolved_questions,
            evidence_quality=payload.evidence_quality.value,
            confidence=payload.confidence,
            sources=tuple(
                TailRadarResearchSourceResponse.model_validate(source.model_dump(mode="python"))
                for source in data.sources
            ),
            provider=payload.provider,
            model_identifier=payload.model_identifier,
            prompt_version=payload.prompt_version,
            created_at=data.created_at,
        )


class TailRadarCandidateWorkflowStateResponse(BaseModel):
    workflow_run_id: UUID
    technical_status: Literal["pending", "running", "succeeded", "failed"]
    research_status: Literal["pending", "running", "succeeded", "no_evidence", "failed"]
    technical_error_code: str | None
    research_error_code: str | None

    @classmethod
    def from_data(
        cls, data: TailRadarWorkflowCandidateState
    ) -> "TailRadarCandidateWorkflowStateResponse":
        return cls.model_validate(data.model_dump(mode="python"))


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
    intraday_analysis: TailRadarIntradayAnalysisResponse | None
    web_research: TailRadarWebResearchResponse | None
    workflow_state: TailRadarCandidateWorkflowStateResponse | None
    created_at: AwareDatetime

    @classmethod
    def from_data(
        cls,
        data: TailRadarCandidateData,
        intraday_analysis: TailRadarIntradayAnalysisData | None = None,
        web_research: TailRadarResearchData | None = None,
        workflow_state: TailRadarWorkflowCandidateState | None = None,
    ) -> "TailRadarCandidateDetailResponse":
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
            intraday_analysis=(
                None
                if intraday_analysis is None
                else TailRadarIntradayAnalysisResponse.from_data(intraday_analysis)
            ),
            web_research=(
                None
                if web_research is None
                else TailRadarWebResearchResponse.from_data(web_research)
            ),
            workflow_state=(
                None
                if workflow_state is None
                else TailRadarCandidateWorkflowStateResponse.from_data(workflow_state)
            ),
            created_at=data.created_at,
        )
