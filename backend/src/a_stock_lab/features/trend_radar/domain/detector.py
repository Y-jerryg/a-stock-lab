import itertools
from collections.abc import Sequence
from statistics import fmean

from a_stock_lab.features.trend_radar.config import TrendSettings
from a_stock_lab.features.trend_radar.domain.models import Bar, Contraction, Trend, TrendError

EPSILON_PCT = 1e-8


def detect_trend(bars: Sequence[Bar], config: TrendSettings) -> Trend | None:
    """N closing observations imply N-1 within-window returns; longest window wins."""
    dates = [bar.trade_date for bar in bars]
    if dates != sorted(set(dates)) or len({bar.symbol for bar in bars}) > 1:
        raise TrendError("invalid_bar_sequence")
    for days in range(config.trend_max_days, config.trend_min_days - 1, -1):
        if len(bars) < days:
            continue
        window = bars[-days:]
        if any(bar.volume <= 0 for bar in window):
            continue
        closes = [bar.close for bar in window]
        returns = [(right / left - 1) * 100 for left, right in itertools.pairwise(closes)]
        pullbacks = [value for value in returns if value > EPSILON_PCT]
        mean_x = (days - 1) / 2
        mean_y = fmean(closes)
        slope = sum((i - mean_x) * (price - mean_y) for i, price in enumerate(closes)) / sum(
            (i - mean_x) ** 2 for i in range(days)
        )
        if (
            closes[-1] >= closes[0]
            or slope >= 0
            or len(pullbacks) > config.trend_max_pullback_days
            or max(pullbacks, default=0) > config.trend_max_single_pullback_pct + EPSILON_PCT
        ):
            continue
        return Trend(
            trend_days=days,
            trend_start_date=window[0].trade_date,
            trend_end_date=window[-1].trade_date,
            trend_start_close=closes[0],
            trend_end_close=closes[-1],
            trend_return_pct=(closes[-1] / closes[0] - 1) * 100,
            pullback_days=len(pullbacks),
            max_pullback_pct=max(pullbacks, default=0),
            trend_slope=slope,
        )
    return None


def analyze_volume(bars: Sequence[Bar], trend: Trend, config: TrendSettings) -> Contraction:
    days = trend.trend_days
    baseline_days = config.trend_baseline_volume_days
    if len(bars) < days + baseline_days:
        raise TrendError("insufficient_history")
    window = bars[-days:]
    if (
        window[0].trade_date != trend.trend_start_date
        or window[-1].trade_date != trend.trend_end_date
    ):
        raise TrendError("invalid_trend_window")
    baseline = bars[-days - baseline_days : -days]
    baseline_volume = fmean(bar.volume for bar in baseline)
    if baseline_volume <= 0:
        raise TrendError("invalid_baseline_volume")
    volume = fmean(bar.volume for bar in window)
    amount = fmean(bar.amount for bar in window)
    baseline_amount = fmean(bar.amount for bar in baseline)
    ratio = volume / baseline_volume
    strong = ratio <= config.trend_strong_volume_ratio
    return Contraction(
        trend_volume_avg=volume,
        baseline_volume_avg=baseline_volume,
        volume_ratio=ratio,
        trend_amount_avg=amount,
        baseline_amount_avg=baseline_amount,
        amount_ratio=amount / baseline_amount if baseline_amount > 0 else None,
        is_strong_volume_contraction=strong,
        highlight_level="strong" if strong else "normal",
    )
