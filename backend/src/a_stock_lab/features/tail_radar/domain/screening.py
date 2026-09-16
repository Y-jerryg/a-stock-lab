import math
import re
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
from a_stock_lab.shared.market_data.models import AShareExchange, MarketSnapshotRecord

TAIL_RADAR_SCREENING_RULE_VERSION = "tail-radar-screen-v2"
LEGACY_TAIL_RADAR_SCREENING_RULE_VERSION = "tail-radar-screen-v1"
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")


class TailRadarScreeningConfiguration(BaseModel):
    """Current criterion, with the original range retained for historical reads."""

    model_config = ConfigDict(frozen=True)

    pct_change_min: float = 3.0
    pct_change_max: float = 5.0
    exclude_st: bool = False
    minimum_amount: float | None = Field(default=None, ge=0)
    minimum_float_market_cap: float | None = Field(default=None, ge=0)
    maximum_float_market_cap: float | None = Field(default=None, ge=0)
    allowed_exchanges: frozenset[AShareExchange] | None = None
    allowed_boards: frozenset[str] | None = None

    @model_validator(mode="after")
    def require_versioned_configuration(self) -> "TailRadarScreeningConfiguration":
        if (self.pct_change_min, self.pct_change_max) not in {(2.0, 3.0), (3.0, 5.0)}:
            raise ValueError("screening requires inclusive 3.00 to 5.00 (legacy: 2.00 to 3.00)")
        if (
            self.exclude_st
            or self.minimum_amount is not None
            or self.minimum_float_market_cap is not None
            or self.maximum_float_market_cap is not None
            or self.allowed_exchanges is not None
            or self.allowed_boards is not None
        ):
            raise ValueError("optional Tail Radar filters are disabled")
        return self

    @property
    def rule_version(self) -> str:
        return (
            LEGACY_TAIL_RADAR_SCREENING_RULE_VERSION
            if self.pct_change_min == 2.0
            else TAIL_RADAR_SCREENING_RULE_VERSION
        )


class TailRadarSnapshotEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: UUID
    snapshot_run_id: UUID
    trade_date: date
    intended_snapshot_time: AwareDatetime
    actual_fetch_started_at: AwareDatetime
    actual_fetch_finished_at: AwareDatetime
    provider: str = Field(min_length=1, max_length=128)
    provider_timestamp: AwareDatetime | None = None
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_schema_version: int = Field(gt=0)

    @field_validator(
        "intended_snapshot_time",
        "actual_fetch_started_at",
        "actual_fetch_finished_at",
        "provider_timestamp",
    )
    @classmethod
    def normalize_market_timestamps(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @model_validator(mode="after")
    def validate_point_in_time_evidence(self) -> "TailRadarSnapshotEvidence":
        if self.trade_date != self.intended_snapshot_time.date():
            raise ValueError("trade date must match intended snapshot time in Asia/Shanghai")
        if self.actual_fetch_started_at < self.intended_snapshot_time:
            raise ValueError("snapshot fetch cannot precede its intended snapshot time")
        if self.actual_fetch_finished_at < self.actual_fetch_started_at:
            raise ValueError("snapshot fetch finish cannot precede its start")
        return self

    @property
    def as_of(self) -> AwareDatetime:
        """Return the latest evidence observation time, preventing look-ahead ambiguity."""
        return self.actual_fetch_finished_at


class TailRadarScreeningInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    record: MarketSnapshotRecord
    snapshot_evidence: TailRadarSnapshotEvidence | None


class TailRadarDecisionOutcome(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    INVALID = "invalid"


class TailRadarDecisionReason(StrEnum):
    PCT_CHANGE_IN_RANGE = "pct_change_in_inclusive_range"
    PCT_CHANGE_OUT_OF_RANGE = "pct_change_outside_inclusive_range"
    MISSING_SNAPSHOT_EVIDENCE = "missing_snapshot_evidence"
    INVALID_SYMBOL = "invalid_symbol"
    INVALID_PCT_CHANGE = "invalid_pct_change"
    INVALID_PRICE = "invalid_price"


class TailRadarScreeningDecision(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    outcome: TailRadarDecisionOutcome
    reason: TailRadarDecisionReason
    observed_pct_change: float | None
    observed_price: float | None
    inclusive_min: float = 3.0
    inclusive_max: float = 5.0

    @model_validator(mode="after")
    def validate_decision_coherence(self) -> "TailRadarScreeningDecision":
        if self.inclusive_min > self.inclusive_max:
            raise ValueError("screening decision range is invalid")

        has_valid_price = self.observed_price is not None and self.observed_price > 0
        observed_pct_change = self.observed_pct_change
        has_pct_change = observed_pct_change is not None
        pct_change_in_range = (
            observed_pct_change is not None
            and self.inclusive_min <= observed_pct_change <= self.inclusive_max
        )
        if self.outcome is TailRadarDecisionOutcome.INCLUDED:
            if (
                self.reason is not TailRadarDecisionReason.PCT_CHANGE_IN_RANGE
                or not has_valid_price
                or not pct_change_in_range
            ):
                raise ValueError("included decision must contain valid in-range evidence")
        elif self.outcome is TailRadarDecisionOutcome.EXCLUDED:
            if (
                self.reason is not TailRadarDecisionReason.PCT_CHANGE_OUT_OF_RANGE
                or not has_valid_price
                or not has_pct_change
                or pct_change_in_range
            ):
                raise ValueError("excluded decision must contain valid out-of-range evidence")
        elif self.reason in {
            TailRadarDecisionReason.PCT_CHANGE_IN_RANGE,
            TailRadarDecisionReason.PCT_CHANGE_OUT_OF_RANGE,
        }:
            raise ValueError("invalid decision cannot use a valid screening reason")
        return self

    @property
    def included(self) -> bool:
        return self.outcome is TailRadarDecisionOutcome.INCLUDED


class TailRadarScreeningRule:
    """Evaluate one normalized record from one point-in-time official snapshot."""

    version = TAIL_RADAR_SCREENING_RULE_VERSION

    def __init__(self, configuration: TailRadarScreeningConfiguration | None = None) -> None:
        self.configuration = configuration or TailRadarScreeningConfiguration()
        self.version = self.configuration.rule_version

    def evaluate(self, screening_input: TailRadarScreeningInput) -> TailRadarScreeningDecision:
        record = screening_input.record
        common = {
            "observed_pct_change": record.pct_change,
            "observed_price": record.price,
            "inclusive_min": self.configuration.pct_change_min,
            "inclusive_max": self.configuration.pct_change_max,
        }
        if screening_input.snapshot_evidence is None:
            return TailRadarScreeningDecision(
                outcome=TailRadarDecisionOutcome.INVALID,
                reason=TailRadarDecisionReason.MISSING_SNAPSHOT_EVIDENCE,
                **common,
            )
        if _SYMBOL_PATTERN.fullmatch(record.symbol) is None:
            return TailRadarScreeningDecision(
                outcome=TailRadarDecisionOutcome.INVALID,
                reason=TailRadarDecisionReason.INVALID_SYMBOL,
                **common,
            )
        if record.pct_change is None or not math.isfinite(record.pct_change):
            return TailRadarScreeningDecision(
                outcome=TailRadarDecisionOutcome.INVALID,
                reason=TailRadarDecisionReason.INVALID_PCT_CHANGE,
                **common,
            )
        if record.price is None or not math.isfinite(record.price) or record.price <= 0:
            return TailRadarScreeningDecision(
                outcome=TailRadarDecisionOutcome.INVALID,
                reason=TailRadarDecisionReason.INVALID_PRICE,
                **common,
            )
        if (
            self.configuration.pct_change_min
            <= record.pct_change
            <= self.configuration.pct_change_max
        ):
            return TailRadarScreeningDecision(
                outcome=TailRadarDecisionOutcome.INCLUDED,
                reason=TailRadarDecisionReason.PCT_CHANGE_IN_RANGE,
                **common,
            )
        return TailRadarScreeningDecision(
            outcome=TailRadarDecisionOutcome.EXCLUDED,
            reason=TailRadarDecisionReason.PCT_CHANGE_OUT_OF_RANGE,
            **common,
        )
