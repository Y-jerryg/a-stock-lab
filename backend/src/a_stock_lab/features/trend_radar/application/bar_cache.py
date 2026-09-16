"""Reuse completed sessions, checking overlap before mixing qfq vintages."""

import logging
from datetime import date, datetime, timedelta
from typing import Literal

from a_stock_lab.features.trend_radar.application.contracts import MarketDataProvider
from a_stock_lab.features.trend_radar.domain.models import Bar, TrendError

logger = logging.getLogger(__name__)
CacheMode = Literal["hit", "incremental", "full"]


def validate_bars(bars: list[Bar], symbol: str, end: date) -> None:
    dates = [bar.trade_date for bar in bars]
    if (
        dates != sorted(set(dates))
        or any(bar.symbol != symbol or bar.trade_date > end for bar in bars)
        or len({bar.source for bar in bars}) > 1
    ):
        raise TrendError("invalid_market_sequence")


def resolve_bars(
    market: MarketDataProvider,
    symbol: str,
    sessions: list[date],
    cached: list[Bar] | None,
    now: datetime,
    refresh_days: int = 7,
) -> tuple[list[Bar], CacheMode]:
    start, end = sessions[0], sessions[-1]

    def full() -> tuple[list[Bar], CacheMode]:
        rows = market.fetch_bars(symbol, start, end)
        validate_bars(rows, symbol, end)
        return [row for row in rows if row.trade_date >= start], "full"

    if not cached:
        return full()
    validate_bars(cached, symbol, end)
    rows = [row for row in cached if start <= row.trade_date <= end]
    if not rows or now - min(row.fetched_at for row in rows) >= timedelta(days=refresh_days):
        return full()
    known = {row.trade_date: row for row in rows}
    missing = [day for day in sessions if day not in known]
    if not missing:
        return rows, "hit"
    # Re-read three known sessions to detect corrections, source changes and qfq changes.
    overlap_start = rows[max(0, len(rows) - 3)].trade_date
    fetched = market.fetch_bars(symbol, min(missing[0], overlap_start), end)
    validate_bars(fetched, symbol, end)
    fresh = {row.trade_date: row for row in fetched}
    overlap = [row for row in rows if row.trade_date >= min(missing[0], overlap_start)]
    fields = {"fetched_at"}
    if not overlap or any(
        row.trade_date not in fresh
        or row.model_dump(exclude=fields) != fresh[row.trade_date].model_dump(exclude=fields)
        for row in overlap
    ):
        logger.info("trend_cache_overlap_changed", extra={"symbol": symbol})
        return full()
    known.update(fresh)
    return [known[day] for day in sorted(known) if start <= day <= end], "incremental"
