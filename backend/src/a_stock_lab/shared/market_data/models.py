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


class AShareExchange(StrEnum):
    SHANGHAI = "SSE"
    SHENZHEN = "SZSE"
    BEIJING = "BSE"


class MarketDataCapability(StrEnum):
    FULL_MARKET_SNAPSHOT = "full_market_snapshot"
    INTRADAY_BARS = "intraday_bars"
    DAILY_BARS = "daily_bars"
    SECURITY_MASTER = "security_master"
    TRADING_CALENDAR = "trading_calendar"


class SnapshotManifestStatus(StrEnum):
    AVAILABLE = "available"


class NormalizationIssueCode(StrEnum):
    MISSING_SYMBOL = "missing_symbol"
    INVALID_SYMBOL = "invalid_symbol"
    MISSING_NAME = "missing_name"
    INVALID_NUMERIC_VALUE = "invalid_numeric_value"
    MALFORMED_ROW = "malformed_row"


class NormalizationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    row_number: int = Field(ge=1)
    code: NormalizationIssueCode
    field: str | None = None


class MarketSnapshotRecord(BaseModel):
    """One normalized A-share quote, independent of any provider's source schema."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    symbol: str = Field(pattern=r"^\d{6}$")
    exchange: AShareExchange | None = None
    name: str | None = None
    price: float | None = None
    pct_change: float | None = None
    absolute_change: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    previous_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    amplitude: float | None = None
    volume_ratio: float | None = None
    turnover_rate: float | None = None
    pe_dynamic: float | None = None
    pb: float | None = None
    total_market_cap: float | None = None
    float_market_cap: float | None = None
    provider: str = Field(min_length=1, max_length=128)
    provider_timestamp: AwareDatetime | None = None
    fetched_at: AwareDatetime

    @field_validator("provider_timestamp", "fetched_at")
    @classmethod
    def normalize_timestamps_to_market_timezone(
        cls, value: AwareDatetime | None
    ) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)


class ProviderSnapshotBatch(BaseModel):
    """Normalized adapter output before provider-independent quality acceptance."""

    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1, max_length=128)
    records: tuple[MarketSnapshotRecord, ...]
    raw_record_count: int = Field(ge=0)
    normalization_issues: tuple[NormalizationIssue, ...] = ()
    provider_version: str | None = Field(default=None, max_length=128)
    provider_timestamp: AwareDatetime | None = None
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("provider_timestamp")
    @classmethod
    def normalize_provider_timestamp(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @model_validator(mode="after")
    def normalized_count_cannot_exceed_raw_count(self) -> "ProviderSnapshotBatch":
        if len(self.records) > self.raw_record_count:
            raise ValueError("normalized record count cannot exceed raw record count")
        if any(record.provider != self.provider for record in self.records):
            raise ValueError("record provider must match batch provider")
        if any(issue.row_number > self.raw_record_count for issue in self.normalization_issues):
            raise ValueError("normalization issue row cannot exceed raw record count")
        return self


class SnapshotQualityThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_record_count: int = Field(default=4_000, ge=1)
    max_duplicate_symbols: int = Field(default=0, ge=0)
    max_missing_symbol_ratio: float = Field(default=0.001, ge=0, le=1)
    max_invalid_price_ratio: float = Field(default=0.005, ge=0, le=1)
    max_invalid_pct_change_ratio: float = Field(default=0.005, ge=0, le=1)
    max_malformed_row_ratio: float = Field(default=0.01, ge=0, le=1)
    max_abs_pct_change: float = Field(default=1_000.0, gt=0)


class ProviderRetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=2, ge=1, le=3)
    delay_seconds: float = Field(default=5.0, ge=0, le=60)


class SnapshotQualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    raw_record_count: int = Field(ge=0)
    normalized_record_count: int = Field(ge=0)
    duplicate_symbol_count: int = Field(ge=0)
    missing_symbol_count: int = Field(ge=0)
    invalid_price_count: int = Field(ge=0)
    invalid_pct_change_count: int = Field(ge=0)
    malformed_row_count: int = Field(ge=0)
    missing_symbol_ratio: float = Field(ge=0, le=1)
    invalid_price_ratio: float = Field(ge=0, le=1)
    invalid_pct_change_ratio: float = Field(ge=0, le=1)
    malformed_row_ratio: float = Field(ge=0, le=1)
    thresholds: SnapshotQualityThresholds
    violations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def pass_state_matches_violations(self) -> "SnapshotQualityReport":
        if self.passed == bool(self.violations):
            raise ValueError("quality pass state must agree with violations")
        return self


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: UUID
    provider: str = Field(min_length=1, max_length=128)
    provider_version: str | None = Field(default=None, max_length=128)
    provider_timestamp: AwareDatetime | None = None
    actual_fetch_started_at: AwareDatetime
    actual_fetch_finished_at: AwareDatetime
    latency_ms: float = Field(ge=0)
    record_count: int = Field(ge=0)
    schema_version: int = Field(ge=1)
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    quality_report: SnapshotQualityReport

    @field_validator(
        "provider_timestamp",
        "actual_fetch_started_at",
        "actual_fetch_finished_at",
    )
    @classmethod
    def normalize_timestamps_to_market_timezone(
        cls, value: AwareDatetime | None
    ) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @model_validator(mode="after")
    def timing_and_count_are_consistent(self) -> "SnapshotManifest":
        if self.actual_fetch_finished_at < self.actual_fetch_started_at:
            raise ValueError("fetch finish cannot precede fetch start")
        if self.record_count != self.quality_report.normalized_record_count:
            raise ValueError("manifest record count must match the quality report")
        return self


class FullMarketSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest: SnapshotManifest
    records: tuple[MarketSnapshotRecord, ...]

    @model_validator(mode="after")
    def record_count_matches_manifest(self) -> "FullMarketSnapshot":
        if len(self.records) != self.manifest.record_count:
            raise ValueError("snapshot record count does not match its manifest")
        if not self.manifest.quality_report.passed:
            raise ValueError("an official snapshot must pass quality validation")
        if any(record.provider != self.manifest.provider for record in self.records):
            raise ValueError("record provider must match snapshot provider")
        return self
