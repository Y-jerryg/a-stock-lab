from pathlib import Path
from typing import Protocol, runtime_checkable

from a_stock_lab.shared.market_data.models import (
    FullMarketSnapshot,
    MarketDataCapability,
    ProviderSnapshotBatch,
)


@runtime_checkable
class MarketDataProvider(Protocol):
    """Provider-neutral market-data boundary used by application services."""

    @property
    def provider_id(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[MarketDataCapability]: ...

    def fetch_full_market_snapshot(self) -> ProviderSnapshotBatch: ...


class MarketSnapshotWriter(Protocol):
    def write(self, snapshot: FullMarketSnapshot) -> Path: ...
