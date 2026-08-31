from datetime import datetime, timedelta

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.domain.intraday import (
    IntradayFeatureEngine,
    IntradayQualityIssue,
    IntradayQualityStatus,
)
from a_stock_lab.shared.market_data.models import (
    IntradayBar,
    IntradayBarRequest,
    ProviderIntradayBarBatch,
)

TRADE_DATE = datetime(2026, 8, 28, tzinfo=MARKET_TIME_ZONE).date()
FETCHED_AT = datetime(2026, 8, 28, 15, 5, tzinfo=MARKET_TIME_ZONE)
SYMBOL = "600000"


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 28, hour, minute, tzinfo=MARKET_TIME_ZONE)


def bars_from_closes(closes: list[float]) -> tuple[IntradayBar, ...]:
    bars: list[IntradayBar] = []
    previous = closes[0]
    for index, close in enumerate(closes):
        ended_at = at(9, 35) + timedelta(minutes=5 * index)
        open_price = previous if index else closes[0]
        volume = 1_000 + index * 100
        bars.append(
            IntradayBar(
                symbol=SYMBOL,
                ended_at=ended_at,
                open=open_price,
                high=max(open_price, close) + 0.01,
                low=min(open_price, close) - 0.01,
                close=close,
                volume=volume,
                amount=volume * ((open_price + close) / 2),
                provider="fixture",
                fetched_at=FETCHED_AT,
            )
        )
        previous = close
    return tuple(bars)


def batch(
    bars: tuple[IntradayBar, ...],
    *,
    as_of: datetime,
    normalization_issue_count: int = 0,
) -> ProviderIntradayBarBatch:
    return ProviderIntradayBarBatch(
        provider="fixture",
        request=IntradayBarRequest(
            symbol=SYMBOL,
            start_at=at(9, 30),
            end_at=as_of,
        ),
        bars=bars,
        raw_record_count=len(bars) + normalization_issue_count,
        normalization_issue_count=normalization_issue_count,
        fetched_at=FETCHED_AT,
    )


def test_steady_rise_calculates_required_price_volume_and_path_features() -> None:
    as_of = at(10, 10)
    bars = bars_from_closes([10.0, 10.02, 10.04, 10.06, 10.08, 10.10, 10.12, 10.14])

    result = IntradayFeatureEngine().calculate(batch=batch(bars, as_of=as_of), analysis_as_of=as_of)

    assert result.data_quality.status is IntradayQualityStatus.GOOD
    assert result.latest_bar_used == bars[-1]
    assert result.price.previous_5m_return_pct == pytest.approx((10.14 / 10.12 - 1) * 100)
    assert result.price.previous_15m_return_pct == pytest.approx((10.14 / 10.08 - 1) * 100)
    assert result.price.previous_30m_return_pct == pytest.approx((10.14 / 10.02 - 1) * 100)
    assert result.price.return_since_open_pct == pytest.approx(1.4)
    assert result.price.normalized_intraday_position is not None
    assert result.volume.recent_5m_volume == bars[-1].volume
    assert result.volume.previous_comparable_5m_volume == bars[-2].volume
    assert result.volume.recent_volume_acceleration_ratio == pytest.approx(
        bars[-1].volume / bars[-2].volume
    )
    assert result.volume.vwap is not None
    assert result.path.steady_strengthening is True


def test_early_spike_then_pullback_is_described_without_a_trading_label() -> None:
    as_of = at(10, 10)
    bars = bars_from_closes([10.0, 10.15, 10.3, 10.25, 10.2, 10.15, 10.1, 10.05])

    result = IntradayFeatureEngine().calculate(batch=batch(bars, as_of=as_of), analysis_as_of=as_of)

    assert result.path.early_spike_followed_by_pullback is True
    assert result.path.materially_below_earlier_intraday_peak is True
    assert result.path.steady_strengthening is False


def test_late_acceleration_and_flat_path_are_distinguished() -> None:
    as_of = at(10, 10)
    accelerated = bars_from_closes([10.0, 10.0, 10.0, 10.0, 10.0, 10.03, 10.08, 10.15])
    flat = bars_from_closes([10.0] * 8)

    accelerated_result = IntradayFeatureEngine().calculate(
        batch=batch(accelerated, as_of=as_of), analysis_as_of=as_of
    )
    flat_result = IntradayFeatureEngine().calculate(
        batch=batch(flat, as_of=as_of), analysis_as_of=as_of
    )

    assert accelerated_result.path.late_acceleration is True
    assert flat_result.path.late_acceleration is False
    assert flat_result.path.steady_strengthening is False
    assert flat_result.path.early_spike_followed_by_pullback is False
    assert flat_result.path.recovery_from_intraday_weakness is False
    assert flat_result.path.materially_below_earlier_intraday_peak is False
    assert flat_result.price.normalized_intraday_position is not None


def test_recovery_from_intraday_weakness_is_explicitly_detected() -> None:
    as_of = at(10, 10)
    bars = bars_from_closes([10.0, 9.9, 9.8, 9.85, 9.9, 9.95, 10.0, 10.05])

    result = IntradayFeatureEngine().calculate(batch=batch(bars, as_of=as_of), analysis_as_of=as_of)

    assert result.path.recovery_from_intraday_weakness is True


def test_missing_duplicate_and_out_of_order_bars_have_deterministic_quality_behavior() -> None:
    as_of = at(10, 10)
    ordered = bars_from_closes([10.0, 10.02, 10.04, 10.06, 10.08, 10.10, 10.12, 10.14])
    missing = ordered[:3] + ordered[4:]
    duplicate = (*ordered, ordered[-1])
    out_of_order = (ordered[1], ordered[0], *ordered[2:])

    missing_result = IntradayFeatureEngine().calculate(
        batch=batch(missing, as_of=as_of), analysis_as_of=as_of
    )
    duplicate_result = IntradayFeatureEngine().calculate(
        batch=batch(duplicate, as_of=as_of), analysis_as_of=as_of
    )
    out_of_order_result = IntradayFeatureEngine().calculate(
        batch=batch(out_of_order, as_of=as_of), analysis_as_of=as_of
    )

    assert missing_result.data_quality.status is IntradayQualityStatus.DEGRADED
    assert missing_result.data_quality.missing_expected_bar_count == 1
    assert missing_result.volume.vwap is None
    assert duplicate_result.data_quality.status is IntradayQualityStatus.INVALID
    assert duplicate_result.latest_bar_used is None
    assert duplicate_result.data_quality.duplicate_timestamp_count == 1
    assert out_of_order_result.data_quality.status is IntradayQualityStatus.DEGRADED
    assert out_of_order_result.data_quality.was_out_of_order is True
    assert out_of_order_result.latest_bar_used == ordered[-1]


def test_future_bars_are_excluded_before_any_feature_calculation() -> None:
    as_of = at(10, 10)
    eligible = bars_from_closes([10.0, 10.02, 10.04, 10.06, 10.08, 10.10, 10.12, 10.14])
    future = IntradayBar(
        symbol=SYMBOL,
        ended_at=at(10, 15),
        open=10.14,
        high=99.0,
        low=10.14,
        close=99.0,
        volume=9_999_999,
        amount=999_999_999,
        provider="fixture",
        fetched_at=FETCHED_AT,
    )

    result = IntradayFeatureEngine().calculate(
        batch=batch((*eligible, future), as_of=as_of),
        analysis_as_of=as_of,
    )

    assert result.latest_bar_used == eligible[-1]
    assert result.latest_bar_used.ended_at <= as_of
    assert result.used_bars == eligible
    assert all(bar.ended_at <= as_of for bar in result.used_bars)
    assert result.data_quality.future_bar_count == 1
    assert IntradayQualityIssue.FUTURE_BARS_EXCLUDED in result.data_quality.issues
    assert result.price.distance_from_intraday_high_pct != pytest.approx((10.14 / 99 - 1) * 100)


def test_bar_cannot_claim_it_was_fetched_before_its_completed_end() -> None:
    with pytest.raises(ValueError, match="cannot end after it was fetched"):
        IntradayBar(
            symbol=SYMBOL,
            ended_at=at(10, 10),
            open=10.0,
            high=10.1,
            low=9.9,
            close=10.0,
            volume=1_000,
            amount=10_000,
            provider="fixture",
            fetched_at=at(10, 9),
        )


def test_no_bars_produces_an_explicit_invalid_quality_result_with_null_features() -> None:
    as_of = at(10, 10)

    result = IntradayFeatureEngine().calculate(
        batch=batch((), as_of=as_of),
        analysis_as_of=as_of,
    )

    assert result.data_quality.status is IntradayQualityStatus.INVALID
    assert IntradayQualityIssue.NO_ELIGIBLE_BARS in result.data_quality.issues
    assert result.latest_bar_used is None
    assert result.price.previous_5m_return_pct is None
    assert result.volume.vwap is None
    assert result.path.steady_strengthening is None
