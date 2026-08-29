from datetime import date
from typing import Protocol, runtime_checkable

from a_stock_lab.shared.market_data.models import (
    FullMarketSnapshot,
    MarketDataCapability,
    ProviderSnapshotBatch,
)
from a_stock_lab.shared.market_data.persistence_schemas import SnapshotStorageResult
from a_stock_lab.shared.market_data.trading_calendar import TradingDay


@runtime_checkable
class MarketDataProvider(Protocol):
    """Provider-neutral market-data boundary used by application services."""

    @property
    def provider_id(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[MarketDataCapability]: ...

    def fetch_full_market_snapshot(self) -> ProviderSnapshotBatch: ...


class MarketSnapshotStorage(Protocol):
    def write(self, snapshot: FullMarketSnapshot) -> SnapshotStorageResult: ...

    def delete(self, storage_key: str) -> None: ...


@runtime_checkable
class TradingCalendar(Protocol):
    @property
    def provider_id(self) -> str: ...

    def resolve(self, trade_date: date) -> TradingDay: ...
