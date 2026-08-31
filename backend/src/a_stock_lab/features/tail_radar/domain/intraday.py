from datetime import date, datetime, time, timedelta
from enum import StrEnum
from itertools import pairwise

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from a_stock_lab.core.time import MARKET_TIME_ZONE, as_market_timezone
from a_stock_lab.shared.market_data.models import IntradayBar, ProviderIntradayBarBatch

INTRADAY_FEATURE_SCHEMA_VERSION = 2
INTRADAY_CALCULATION_VERSION = "tail-radar-intraday-v2"
LEGACY_INTRADAY_FEATURE_SCHEMA_VERSION = 1
LEGACY_INTRADAY_CALCULATION_VERSION = "tail-radar-intraday-v1"
_BAR_INTERVAL = timedelta(minutes=5)
_MORNING_FIRST_END = time(9, 35)
_MORNING_LAST_END = time(11, 30)
_AFTERNOON_FIRST_END = time(13, 5)
_AFTERNOON_LAST_END = time(15, 0)


class IntradayQualityStatus(StrEnum):
    GOOD = "good"
    DEGRADED = "degraded"
    INVALID = "invalid"


class IntradayQualityIssue(StrEnum):
    NO_ELIGIBLE_BARS = "no_eligible_bars"
    FUTURE_BARS_EXCLUDED = "future_bars_excluded"
    DUPLICATE_BAR_TIMESTAMPS = "duplicate_bar_timestamps"
    OUT_OF_ORDER_BARS = "out_of_order_bars"
    MISSING_EXPECTED_BARS = "missing_expected_bars"
    MALFORMED_PROVIDER_ROWS = "malformed_provider_rows"
    OFF_SESSION_BARS = "off_session_bars"


class IntradayFeatureConfiguration(BaseModel):
    """Explicit descriptive thresholds for calculation version one."""

    model_config = ConfigDict(frozen=True)

    steady_min_return_since_open_pct: float = 0.5
    steady_max_drawdown_pct: float = 0.3
    late_acceleration_min_recent_15m_pct: float = 0.5
    late_acceleration_min_improvement_pct: float = 0.3
    early_spike_window_minutes: int = 30
    early_spike_min_rise_pct: float = 1.0
    early_spike_pullback_min_drawdown_pct: float = 1.0
    recovery_min_weakness_pct: float = 0.5
    recovery_min_rebound_pct: float = 0.8
    recovery_min_intraday_position: float = 0.6
    materially_below_peak_min_drawdown_pct: float = 1.0

    @model_validator(mode="after")
    def require_v1_thresholds(self) -> "IntradayFeatureConfiguration":
        if (
            self.steady_min_return_since_open_pct,
            self.steady_max_drawdown_pct,
            self.late_acceleration_min_recent_15m_pct,
            self.late_acceleration_min_improvement_pct,
            self.early_spike_window_minutes,
            self.early_spike_min_rise_pct,
            self.early_spike_pullback_min_drawdown_pct,
            self.recovery_min_weakness_pct,
            self.recovery_min_rebound_pct,
            self.recovery_min_intraday_position,
            self.materially_below_peak_min_drawdown_pct,
        ) != (0.5, 0.3, 0.5, 0.3, 30, 1.0, 1.0, 0.5, 0.8, 0.6, 1.0):
            raise ValueError(
                "Tail Radar intraday thresholds are immutable; create a new version to change them"
            )
        return self


class IntradayDataQualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: IntradayQualityStatus
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
    issues: tuple[IntradayQualityIssue, ...]

    @model_validator(mode="after")
    def validate_quality_state(self) -> "IntradayDataQualityReport":
        if self.used_bar_count > self.eligible_bar_count:
            raise ValueError("used intraday bars cannot exceed eligible bars")
        if self.status is IntradayQualityStatus.GOOD and self.issues:
            raise ValueError("good intraday quality cannot contain issues")
        if self.status is IntradayQualityStatus.INVALID and self.used_bar_count:
            raise ValueError("invalid intraday data cannot claim used bars")
        return self


class IntradayPriceFeatures(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    previous_5m_return_pct: float | None = None
    previous_15m_return_pct: float | None = None
    previous_30m_return_pct: float | None = None
    return_since_open_pct: float | None = None
    distance_from_intraday_high_pct: float | None = None
    distance_from_intraday_low_pct: float | None = None
    normalized_intraday_position: float | None = Field(default=None, ge=0, le=1)
    drawdown_from_intraday_high_pct: float | None = Field(default=None, ge=0)


class IntradayVolumeFeatures(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    recent_5m_volume: float | None = Field(default=None, ge=0)
    previous_comparable_5m_volume: float | None = Field(default=None, ge=0)
    recent_volume_acceleration_ratio: float | None = Field(default=None, ge=0)
    recent_turnover_amount: float | None = Field(default=None, ge=0)
    vwap: float | None = Field(default=None, gt=0)
    distance_from_vwap_pct: float | None = None


class IntradayPathCharacteristics(BaseModel):
    model_config = ConfigDict(frozen=True)

    steady_strengthening: bool | None
    late_acceleration: bool | None
    early_spike_followed_by_pullback: bool | None
    recovery_from_intraday_weakness: bool | None
    materially_below_earlier_intraday_peak: bool | None


class IntradayFeatureComputation(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_as_of: AwareDatetime
    used_bars: tuple[IntradayBar, ...]
    latest_bar_used: IntradayBar | None
    price: IntradayPriceFeatures
    volume: IntradayVolumeFeatures
    path: IntradayPathCharacteristics
    data_quality: IntradayDataQualityReport

    @field_validator("analysis_as_of")
    @classmethod
    def normalize_as_of(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)

    @model_validator(mode="after")
    def enforce_point_in_time_boundary(self) -> "IntradayFeatureComputation":
        if any(bar.ended_at > self.analysis_as_of for bar in self.used_bars):
            raise ValueError("used bars cannot be later than analysis_as_of")
        if tuple(sorted(self.used_bars, key=lambda bar: bar.ended_at)) != self.used_bars:
            raise ValueError("used bars must be ordered")
        if len({bar.ended_at for bar in self.used_bars}) != len(self.used_bars):
            raise ValueError("used bars must have unique timestamps")
        expected_latest = None if not self.used_bars else self.used_bars[-1]
        if self.latest_bar_used != expected_latest:
            raise ValueError("latest bar must agree with the persisted used-bar series")
        if self.data_quality.used_bar_count != len(self.used_bars):
            raise ValueError("used-bar series must agree with the quality report")
        return self


class IntradayFeatureEngine:
    """Calculate descriptive, point-in-time features from normalized five-minute bars."""

    version = INTRADAY_CALCULATION_VERSION

    def __init__(self, configuration: IntradayFeatureConfiguration | None = None) -> None:
        self.configuration = configuration or IntradayFeatureConfiguration()

    def calculate(
        self,
        *,
        batch: ProviderIntradayBarBatch,
        analysis_as_of: datetime,
    ) -> IntradayFeatureComputation:
        as_of = as_market_timezone(analysis_as_of)
        expected = _expected_bar_ends(as_of.date(), as_of)
        expected_set = set(expected)
        future = [bar for bar in batch.bars if bar.ended_at > as_of]
        not_future = [bar for bar in batch.bars if bar.ended_at <= as_of]
        off_session = [
            bar
            for bar in not_future
            if bar.ended_at.date() != as_of.date() or bar.ended_at not in expected_set
        ]
        eligible = [bar for bar in not_future if bar.ended_at in expected_set]
        was_out_of_order = any(
            current.ended_at < previous.ended_at for previous, current in pairwise(eligible)
        )
        timestamp_counts: dict[datetime, int] = {}
        for bar in eligible:
            timestamp_counts[bar.ended_at] = timestamp_counts.get(bar.ended_at, 0) + 1
        duplicate_count = sum(count - 1 for count in timestamp_counts.values())
        unique_by_time = {bar.ended_at: bar for bar in eligible}
        missing_count = len(expected_set - unique_by_time.keys())

        issues: list[IntradayQualityIssue] = []
        if future:
            issues.append(IntradayQualityIssue.FUTURE_BARS_EXCLUDED)
        if duplicate_count:
            issues.append(IntradayQualityIssue.DUPLICATE_BAR_TIMESTAMPS)
        if was_out_of_order:
            issues.append(IntradayQualityIssue.OUT_OF_ORDER_BARS)
        if missing_count:
            issues.append(IntradayQualityIssue.MISSING_EXPECTED_BARS)
        if batch.normalization_issue_count:
            issues.append(IntradayQualityIssue.MALFORMED_PROVIDER_ROWS)
        if off_session:
            issues.append(IntradayQualityIssue.OFF_SESSION_BARS)
        if not eligible:
            issues.append(IntradayQualityIssue.NO_ELIGIBLE_BARS)

        invalid = not eligible or duplicate_count > 0
        ordered = () if invalid else tuple(unique_by_time[key] for key in sorted(unique_by_time))
        complete = bool(expected) and not missing_count and not invalid
        status = (
            IntradayQualityStatus.INVALID
            if invalid
            else IntradayQualityStatus.DEGRADED
            if issues
            else IntradayQualityStatus.GOOD
        )
        quality = IntradayDataQualityReport(
            status=status,
            raw_bar_count=batch.raw_record_count,
            eligible_bar_count=len(eligible),
            used_bar_count=len(ordered),
            future_bar_count=len(future),
            duplicate_timestamp_count=duplicate_count,
            missing_expected_bar_count=missing_count,
            off_session_bar_count=len(off_session),
            normalization_issue_count=batch.normalization_issue_count,
            was_out_of_order=was_out_of_order,
            complete_from_market_open=complete,
            issues=tuple(issues),
        )
        if not ordered:
            return IntradayFeatureComputation(
                analysis_as_of=as_of,
                used_bars=(),
                latest_bar_used=None,
                price=IntradayPriceFeatures(),
                volume=IntradayVolumeFeatures(),
                path=_unevaluable_path(),
                data_quality=quality,
            )

        latest = ordered[-1]
        bar_by_time = {bar.ended_at: bar for bar in ordered}
        price = self._price_features(
            latest=latest,
            bar_by_time=bar_by_time,
            expected=expected,
            complete=complete,
        )
        volume = self._volume_features(
            latest=latest,
            ordered=ordered,
            bar_by_time=bar_by_time,
            expected=expected,
            complete=complete,
        )
        path = self._path_characteristics(
            latest=latest,
            ordered=ordered,
            bar_by_time=bar_by_time,
            expected=expected,
            complete=complete,
            price=price,
        )
        return IntradayFeatureComputation(
            analysis_as_of=as_of,
            used_bars=ordered,
            latest_bar_used=latest,
            price=price,
            volume=volume,
            path=path,
            data_quality=quality,
        )

    def _price_features(
        self,
        *,
        latest: IntradayBar,
        bar_by_time: dict[datetime, IntradayBar],
        expected: tuple[datetime, ...],
        complete: bool,
    ) -> IntradayPriceFeatures:
        return_since_open = None
        high = low = None
        if expected and expected[0] in bar_by_time:
            return_since_open = _return_pct(latest.close, bar_by_time[expected[0]].open)
        if complete:
            high = max(bar.high for bar in bar_by_time.values())
            low = min(bar.low for bar in bar_by_time.values())
        position = (
            None
            if high is None or low is None or high == low
            else (latest.close - low) / (high - low)
        )
        return IntradayPriceFeatures(
            previous_5m_return_pct=_window_return(latest, bar_by_time, expected, 1),
            previous_15m_return_pct=_window_return(latest, bar_by_time, expected, 3),
            previous_30m_return_pct=_window_return(latest, bar_by_time, expected, 6),
            return_since_open_pct=return_since_open,
            distance_from_intraday_high_pct=(
                None if high is None else _return_pct(latest.close, high)
            ),
            distance_from_intraday_low_pct=(
                None if low is None else _return_pct(latest.close, low)
            ),
            normalized_intraday_position=position,
            drawdown_from_intraday_high_pct=(
                None if high is None else _drawdown_pct(high, latest.close)
            ),
        )

    def _volume_features(
        self,
        *,
        latest: IntradayBar,
        ordered: tuple[IntradayBar, ...],
        bar_by_time: dict[datetime, IntradayBar],
        expected: tuple[datetime, ...],
        complete: bool,
    ) -> IntradayVolumeFeatures:
        previous = _prior_bar(latest, bar_by_time, expected, 1)
        acceleration = (
            None if previous is None or previous.volume <= 0 else latest.volume / previous.volume
        )
        total_volume = sum(bar.volume for bar in ordered) if complete else 0
        total_amount = sum(bar.amount for bar in ordered) if complete else 0
        vwap = total_amount / total_volume if total_amount > 0 and total_volume > 0 else None
        return IntradayVolumeFeatures(
            recent_5m_volume=latest.volume,
            previous_comparable_5m_volume=None if previous is None else previous.volume,
            recent_volume_acceleration_ratio=acceleration,
            recent_turnover_amount=latest.amount,
            vwap=vwap,
            distance_from_vwap_pct=None if vwap is None else _return_pct(latest.close, vwap),
        )

    def _path_characteristics(
        self,
        *,
        latest: IntradayBar,
        ordered: tuple[IntradayBar, ...],
        bar_by_time: dict[datetime, IntradayBar],
        expected: tuple[datetime, ...],
        complete: bool,
        price: IntradayPriceFeatures,
    ) -> IntradayPathCharacteristics:
        config = self.configuration
        recent_seven = ordered[-7:]
        steady = None
        if complete and len(recent_seven) == 7:
            monotonic = all(
                current.close >= previous.close for previous, current in pairwise(recent_seven)
            )
            steady = bool(
                monotonic
                and price.return_since_open_pct is not None
                and price.return_since_open_pct >= config.steady_min_return_since_open_pct
                and price.drawdown_from_intraday_high_pct is not None
                and price.drawdown_from_intraday_high_pct <= config.steady_max_drawdown_pct
            )

        recent_15 = _window_return(latest, bar_by_time, expected, 3)
        previous_15_end = _prior_bar(latest, bar_by_time, expected, 3)
        previous_15 = (
            None
            if previous_15_end is None
            else _window_return(previous_15_end, bar_by_time, expected, 3)
        )
        late_acceleration = (
            None
            if recent_15 is None or previous_15 is None
            else recent_15 >= config.late_acceleration_min_recent_15m_pct
            and recent_15 - previous_15 >= config.late_acceleration_min_improvement_pct
        )

        early_spike_pullback = recovery = below_peak = None
        if complete and expected:
            opening_price = bar_by_time[expected[0]].open
            early_count = config.early_spike_window_minutes // 5
            if len(ordered) >= early_count:
                early_high = max(bar.high for bar in ordered[:early_count])
                early_spike_pullback = bool(
                    _return_pct(early_high, opening_price) >= config.early_spike_min_rise_pct
                    and _drawdown_pct(early_high, latest.close)
                    >= config.early_spike_pullback_min_drawdown_pct
                )
            intraday_low = min(bar.low for bar in ordered)
            position = price.normalized_intraday_position
            recovery = bool(
                _drawdown_pct(opening_price, intraday_low) >= config.recovery_min_weakness_pct
                and _return_pct(latest.close, intraday_low) >= config.recovery_min_rebound_pct
                and position is not None
                and position >= config.recovery_min_intraday_position
            )
            below_peak = bool(
                price.drawdown_from_intraday_high_pct is not None
                and price.drawdown_from_intraday_high_pct
                >= config.materially_below_peak_min_drawdown_pct
            )
        return IntradayPathCharacteristics(
            steady_strengthening=steady,
            late_acceleration=late_acceleration,
            early_spike_followed_by_pullback=early_spike_pullback,
            recovery_from_intraday_weakness=recovery,
            materially_below_earlier_intraday_peak=below_peak,
        )


def _expected_bar_ends(trade_date: date, as_of: datetime) -> tuple[datetime, ...]:
    normalized = as_market_timezone(as_of)
    periods: list[datetime] = []
    for first, last in (
        (_MORNING_FIRST_END, _MORNING_LAST_END),
        (_AFTERNOON_FIRST_END, _AFTERNOON_LAST_END),
    ):
        current = datetime.combine(trade_date, first, tzinfo=MARKET_TIME_ZONE)
        finish = datetime.combine(trade_date, last, tzinfo=MARKET_TIME_ZONE)
        while current <= finish and current <= normalized:
            periods.append(current)
            current += _BAR_INTERVAL
    return tuple(periods)


def _prior_bar(
    latest: IntradayBar,
    bar_by_time: dict[datetime, IntradayBar],
    expected: tuple[datetime, ...],
    periods: int,
) -> IntradayBar | None:
    try:
        index = expected.index(latest.ended_at)
    except ValueError:
        return None
    if index < periods:
        return None
    required = expected[index - periods : index + 1]
    if any(timestamp not in bar_by_time for timestamp in required):
        return None
    return bar_by_time[expected[index - periods]]


def _window_return(
    latest: IntradayBar,
    bar_by_time: dict[datetime, IntradayBar],
    expected: tuple[datetime, ...],
    periods: int,
) -> float | None:
    previous = _prior_bar(latest, bar_by_time, expected, periods)
    return None if previous is None else _return_pct(latest.close, previous.close)


def _return_pct(current: float, previous: float) -> float:
    return (current / previous - 1) * 100


def _drawdown_pct(peak: float, current: float) -> float:
    return (peak - current) / peak * 100


def _unevaluable_path() -> IntradayPathCharacteristics:
    return IntradayPathCharacteristics(
        steady_strengthening=None,
        late_acceleration=None,
        early_spike_followed_by_pullback=None,
        recovery_from_intraday_weakness=None,
        materially_below_earlier_intraday_peak=None,
    )
