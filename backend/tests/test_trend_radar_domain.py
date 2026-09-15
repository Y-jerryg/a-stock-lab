from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from a_stock_lab.features.trend_radar.config import TrendSettings
from a_stock_lab.features.trend_radar.domain.detector import analyze_volume, detect_trend
from a_stock_lab.features.trend_radar.domain.models import Bar, TrendError


def bars_for(prices: list[float], *, baseline: int = 20, volume: float = 50) -> list[Bar]:
    return [
        Bar(
            symbol="600000",
            trade_date=date(2026, 1, 1) + timedelta(days=i),
            open=price,
            high=price,
            low=price,
            close=price,
            volume=100 if i < baseline else volume,
            amount=1000 if i < baseline else 300,
            fetched_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        for i, price in enumerate([110.0] * baseline + prices)
    ]


@pytest.mark.parametrize(
    ("prices", "expected", "pullbacks"),
    [
        ([100, 99, 98, 97, 96, 95, 94, 93, 92], 9, 0),
        ([100, 98, 99, 97, 96, 95, 94, 93, 92], 9, 1),
        ([100, 98.5, 97.3, 98, 96.8, 95.7, 96.4, 94.8, 93.5], 9, 2),
        ([100, 98, 99, 97, 98, 96, 97, 95, 94], 7, 2),
        ([90, 100, 99, 98, 97, 96, 95, 94, 93], 8, 0),
        ([90, 92, 100, 99, 98, 97, 96, 95, 94], 7, 0),
    ],
)
def test_longest_valid_window(prices: list[float], expected: int, pullbacks: int) -> None:
    result = detect_trend(bars_for(prices, baseline=0), TrendSettings(_env_file=None))
    assert result and result.trend_days == expected and result.pullback_days == pullbacks
    assert result.trend_slope < 0 and result.trend_return_pct < 0


@pytest.mark.parametrize(
    "prices",
    [
        [100, 101, 102, 103, 104, 105, 106, 107, 108],
        [100] * 9,
        [100, 99, 98, 97, 96, 95, 94, 98, 97],
        # Final close falls from yesterday, but is above an earlier close.
        [100, 99, 98, 97, 96, 95, 94, 95, 94.5],
        # Matching an earlier low is not a new closing low.
        [100, 99, 98, 97, 96, 95, 94, 95, 94],
        # Flat closes do not count as declining days or rising rebounds.
        [100, 99, 98, 97, 97, 96, 95, 94, 93],
    ],
)
def test_no_valid_latest_window(prices: list[float]) -> None:
    assert detect_trend(bars_for(prices, baseline=0), TrendSettings(_env_file=None)) is None


def test_three_pullbacks_fail_nine_day_window() -> None:
    config = TrendSettings(_env_file=None, trend_min_days=9)
    assert detect_trend(bars_for([100, 98, 99, 97, 98, 96, 97, 95, 94], baseline=0), config) is None


def test_negative_slope_and_final_decline_independent_requirements() -> None:
    config = TrendSettings(
        _env_file=None,
        trend_min_days=9,
        trend_max_single_pullback_pct=100,
    )
    # Last < first, but most observations form an upward path.
    assert detect_trend(bars_for([100, 10, 20, 30, 40, 50, 60, 70, 99], baseline=0), config) is None
    # Negative slope, but last is higher than first.
    assert detect_trend(bars_for([10, 100, 90, 80, 70, 60, 50, 40, 11], baseline=0), config) is None


def test_threshold_and_noise() -> None:
    bars = bars_for([100, 98, 99.47, 97, 96.5, 96, 95, 94, 93], baseline=0)
    result = detect_trend(bars, TrendSettings(_env_file=None))
    assert result and result.trend_days == 9 and result.pullback_days == 1
    assert (
        detect_trend(
            bars, TrendSettings(_env_file=None, trend_min_days=9, trend_max_single_pullback_pct=1.4)
        )
        is None
    )


def test_two_rebounds_can_exceed_old_amplitude_cap() -> None:
    bars = bars_for([100, 98, 96, 98, 97, 98, 96, 95, 94], baseline=0)
    result = detect_trend(bars, TrendSettings(_env_file=None))
    assert result and result.trend_days == 9 and result.pullback_days == 2
    assert result.max_pullback_pct > 1.5
    assert (
        detect_trend(
            bars, TrendSettings(_env_file=None, trend_min_days=9, trend_max_single_pullback_pct=1.5)
        )
        is None
    )


def test_latest_bar_must_be_the_unique_low_not_an_older_matching_window() -> None:
    bars = bars_for([100, 99, 98, 97, 96, 95, 94, 93, 92, 93], baseline=0)
    assert detect_trend(bars, TrendSettings(_env_file=None)) is None


def test_compose_null_cap_is_parsed_as_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_MAX_SINGLE_PULLBACK_PCT", "null")
    assert TrendSettings(_env_file=None).trend_max_single_pullback_pct is None


@pytest.mark.parametrize("days", [7, 8, 9])
@pytest.mark.parametrize(("volume", "strong"), [(55, True), (55.01, False), (50, True)])
def test_volume_uses_exact_trend_and_preceding_baseline(
    days: int, volume: float, strong: bool
) -> None:
    config = TrendSettings(_env_file=None, trend_max_days=days)
    bars = bars_for([100 - i for i in range(days)], volume=volume)
    trend = detect_trend(bars, config)
    assert trend and trend.trend_days == days
    result = analyze_volume(bars, trend, config)
    assert result.volume_ratio == pytest.approx(volume / 100)
    assert result.amount_ratio == pytest.approx(0.3)
    assert result.is_strong_volume_contraction is strong


def test_insufficient_and_zero_baseline() -> None:
    config = TrendSettings(_env_file=None)
    bars = bars_for([100 - i for i in range(9)], baseline=19)
    trend = detect_trend(bars, config)
    assert trend
    with pytest.raises(TrendError, match="insufficient_history"):
        analyze_volume(bars, trend, config)
    bars = bars_for([100 - i for i in range(9)])
    bars[:20] = [bar.model_copy(update={"volume": 0}) for bar in bars[:20]]
    with pytest.raises(TrendError, match="invalid_baseline_volume"):
        analyze_volume(bars, detect_trend(bars, config), config)  # type: ignore[arg-type]


def test_suspension_and_duplicate_dates() -> None:
    bars = bars_for([100 - i for i in range(9)], baseline=0)
    bars[-1] = bars[-1].model_copy(update={"volume": 0})
    assert detect_trend(bars, TrendSettings(_env_file=None)) is None
    with pytest.raises(TrendError, match="invalid_bar_sequence"):
        detect_trend(bars + bars[-1:], TrendSettings(_env_file=None))


@pytest.mark.parametrize(
    "values",
    [
        {"trend_top_n": 0},
        {"trend_min_days": 9, "trend_max_days": 7},
        {"trend_max_single_pullback_pct": -1},
        {"trend_max_pullback_days": 3},
        {"trend_strong_volume_ratio": 0},
        {"trend_schedule_poll_seconds": 0},
        {"trend_timezone": "Asia/Tokyo"},
        {"trend_schedule_time": "12:00"},
        {"trend_strong_volume_ratio": float("nan")},
    ],
)
def test_invalid_config(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TrendSettings(_env_file=None, **values)
