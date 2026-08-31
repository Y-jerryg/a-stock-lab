from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from a_stock_lab.core.time import as_market_timezone
from a_stock_lab.features.tail_radar.domain.intraday import (
    INTRADAY_CALCULATION_VERSION,
    INTRADAY_FEATURE_SCHEMA_VERSION,
    LEGACY_INTRADAY_CALCULATION_VERSION,
    LEGACY_INTRADAY_FEATURE_SCHEMA_VERSION,
    IntradayDataQualityReport,
    IntradayFeatureComputation,
    IntradayFeatureConfiguration,
    IntradayPathCharacteristics,
    IntradayPriceFeatures,
    IntradayVolumeFeatures,
)
from a_stock_lab.shared.market_data.models import IntradayBar, IntradayBarRequest

TAIL_RADAR_INTRADAY_ARTIFACT_TYPE = "tail_radar.intraday_features"


class IntradayAnalysisDisposition(StrEnum):
    CREATED = "created"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class TailRadarIntradayAnalysisPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(pattern=r"^\d{6}$")
    candidate_id: UUID
    source_run_id: UUID
    source_snapshot_id: UUID
    source_candidate_as_of: AwareDatetime
    analysis_as_of: AwareDatetime
    provider: str = Field(min_length=1, max_length=128)
    provider_version: str | None = Field(default=None, max_length=128)
    provider_metadata: dict[str, JsonValue]
    provider_fetched_at: AwareDatetime
    intraday_request: IntradayBarRequest
    # Schema 1 did not persist its normalized input series. None preserves that distinction.
    used_bars: tuple[IntradayBar, ...] | None = None
    latest_bar_used: IntradayBar | None
    feature_schema_version: int = INTRADAY_FEATURE_SCHEMA_VERSION
    calculation_version: str = INTRADAY_CALCULATION_VERSION
    configuration: IntradayFeatureConfiguration
    data_quality: IntradayDataQualityReport
    price: IntradayPriceFeatures
    volume: IntradayVolumeFeatures
    path: IntradayPathCharacteristics

    @field_validator("source_candidate_as_of", "analysis_as_of", "provider_fetched_at")
    @classmethod
    def normalize_timestamps(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)

    @model_validator(mode="after")
    def validate_provenance(self) -> "TailRadarIntradayAnalysisPayload":
        supported_versions = {
            LEGACY_INTRADAY_FEATURE_SCHEMA_VERSION: LEGACY_INTRADAY_CALCULATION_VERSION,
            INTRADAY_FEATURE_SCHEMA_VERSION: INTRADAY_CALCULATION_VERSION,
        }
        if self.feature_schema_version not in supported_versions:
            raise ValueError("unsupported Tail Radar intraday feature schema")
        if self.calculation_version != supported_versions[self.feature_schema_version]:
            raise ValueError("unsupported Tail Radar intraday calculation version")
        if self.feature_schema_version == LEGACY_INTRADAY_FEATURE_SCHEMA_VERSION:
            if self.used_bars is not None:
                raise ValueError("legacy intraday artifacts cannot claim a persisted bar series")
        elif self.used_bars is None:
            raise ValueError("current intraday artifacts require their persisted bar series")
        if self.source_candidate_as_of > self.analysis_as_of:
            raise ValueError("intraday analysis cannot precede candidate evidence")
        if self.intraday_request.symbol != self.symbol:
            raise ValueError("intraday request symbol must match the analysis symbol")
        if self.intraday_request.end_at != self.analysis_as_of:
            raise ValueError("intraday request must end at analysis_as_of")
        persisted_bars = self.used_bars or ()
        if any(bar.symbol != self.symbol for bar in persisted_bars):
            raise ValueError("intraday series symbols must match the analysis")
        if any(bar.provider != self.provider for bar in persisted_bars):
            raise ValueError("intraday series providers must match the analysis")
        if any(bar.ended_at > self.analysis_as_of for bar in persisted_bars):
            raise ValueError("intraday series cannot contain future bars")
        if tuple(sorted(persisted_bars, key=lambda bar: bar.ended_at)) != persisted_bars:
            raise ValueError("intraday series must be ordered")
        if len({bar.ended_at for bar in persisted_bars}) != len(persisted_bars):
            raise ValueError("intraday series must have unique timestamps")
        if self.latest_bar_used is not None:
            if self.latest_bar_used.symbol != self.symbol:
                raise ValueError("latest intraday bar symbol must match the analysis")
            if self.latest_bar_used.provider != self.provider:
                raise ValueError("latest intraday bar provider must match the analysis")
            if self.latest_bar_used.ended_at > self.analysis_as_of:
                raise ValueError("latest intraday bar cannot be later than analysis_as_of")
            if self.latest_bar_used.fetched_at != self.provider_fetched_at:
                raise ValueError("latest intraday bar fetch timestamp must match provider evidence")
            if self.latest_bar_used.interval_minutes != self.intraday_request.interval_minutes:
                raise ValueError("latest intraday bar interval must match the request")
        if (self.latest_bar_used is None) != (self.data_quality.used_bar_count == 0):
            raise ValueError("latest intraday bar must agree with the used-bar count")
        if self.used_bars is not None:
            if self.data_quality.used_bar_count != len(self.used_bars):
                raise ValueError("intraday series must agree with the used-bar count")
            if self.latest_bar_used != (None if not self.used_bars else self.used_bars[-1]):
                raise ValueError("latest intraday bar must agree with the series")
        return self

    @classmethod
    def from_computation(
        cls,
        *,
        symbol: str,
        candidate_id: UUID,
        source_run_id: UUID,
        source_snapshot_id: UUID,
        source_candidate_as_of: AwareDatetime,
        provider: str,
        provider_version: str | None,
        provider_metadata: dict[str, JsonValue],
        provider_fetched_at: AwareDatetime,
        intraday_request: IntradayBarRequest,
        configuration: IntradayFeatureConfiguration,
        computation: IntradayFeatureComputation,
    ) -> "TailRadarIntradayAnalysisPayload":
        return cls(
            symbol=symbol,
            candidate_id=candidate_id,
            source_run_id=source_run_id,
            source_snapshot_id=source_snapshot_id,
            source_candidate_as_of=source_candidate_as_of,
            analysis_as_of=computation.analysis_as_of,
            provider=provider,
            provider_version=provider_version,
            provider_metadata=provider_metadata,
            provider_fetched_at=provider_fetched_at,
            intraday_request=intraday_request,
            used_bars=computation.used_bars,
            latest_bar_used=computation.latest_bar_used,
            configuration=configuration,
            data_quality=computation.data_quality,
            price=computation.price,
            volume=computation.volume,
            path=computation.path,
        )


class TailRadarIntradayAnalysisCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: UUID
    candidate_id: UUID
    run_id: UUID
    snapshot_id: UUID
    symbol: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    analysis_as_of: AwareDatetime
    payload: TailRadarIntradayAnalysisPayload

    @field_validator("analysis_as_of")
    @classmethod
    def normalize_as_of(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)

    @model_validator(mode="after")
    def validate_links(self) -> "TailRadarIntradayAnalysisCreate":
        if self.candidate_id != self.payload.candidate_id:
            raise ValueError("intraday analysis candidate link is inconsistent")
        if self.run_id != self.payload.source_run_id:
            raise ValueError("intraday analysis run link is inconsistent")
        if self.snapshot_id != self.payload.source_snapshot_id:
            raise ValueError("intraday analysis snapshot link is inconsistent")
        if self.symbol != self.payload.symbol:
            raise ValueError("intraday analysis symbol is inconsistent")
        if self.analysis_as_of != self.payload.analysis_as_of:
            raise ValueError("intraday analysis as_of is inconsistent")
        if self.trade_date != self.analysis_as_of.date():
            raise ValueError("intraday analysis trade date must match analysis_as_of")
        return self


class TailRadarIntradayAnalysisData(TailRadarIntradayAnalysisCreate):
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)


class TailRadarIntradayAnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    disposition: IntradayAnalysisDisposition
    analysis: TailRadarIntradayAnalysisData
