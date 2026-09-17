"""Supplementary historical quotes, never evidence used by the saved research."""

from datetime import UTC, date, datetime, timedelta
from threading import Lock
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel

from a_stock_lab.features.trend_radar.application.contracts import MarketDataProvider
from a_stock_lab.features.trend_radar.domain.models import Bar


class DailyChart(BaseModel):
    symbol: str
    cutoff: date
    fetched_at: AwareDatetime
    purpose: Literal["reference_only"] = "reference_only"
    bars: list[Bar]


class ChartStore(Protocol):
    def read(self, symbol: str, cutoff: date) -> DailyChart | None: ...
    def write(self, chart: DailyChart) -> None: ...


class ChartBusyError(Exception):
    pass


class DailyChartService:
    def __init__(self, provider: MarketDataProvider, store: ChartStore) -> None:
        self.provider = provider
        self.store = store
        self.lock = Lock()

    def read(self, symbol: str, as_of: datetime) -> DailyChart:
        # A tail snapshot is intraday: exclude its entire unfinished daily candle.
        cutoff = as_of.astimezone(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
        cached = self.store.read(symbol, cutoff)
        if cached is not None:
            return cached
        # Do not allow public GET traffic to queue unlimited expensive provider requests.
        if not self.lock.acquire(timeout=0.1):
            raise ChartBusyError()
        try:
            cached = self.store.read(symbol, cutoff)
            if cached is not None:
                return cached
            start = cutoff - timedelta(days=240)
            try:
                fetched = self.provider.fetch_bars(symbol, start, cutoff)
            finally:
                self.provider.close()
            bars = sorted(
                {
                    bar.trade_date: bar
                    for bar in fetched
                    if bar.symbol == symbol and start <= bar.trade_date <= cutoff
                }.values(),
                key=lambda bar: bar.trade_date,
            )[-120:]
            result = DailyChart(
                symbol=symbol, cutoff=cutoff, fetched_at=datetime.now(UTC), bars=bars
            )
            self.store.write(result)
            return result
        finally:
            self.lock.release()
