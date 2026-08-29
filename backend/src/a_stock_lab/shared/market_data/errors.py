from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from a_stock_lab.shared.market_data.models import SnapshotQualityReport


class MarketDataError(Exception):
    """Base class for expected market-data failures."""


class ProviderError(MarketDataError):
    def __init__(self, *, provider: str, message: str) -> None:
        super().__init__(message)
        self.provider = provider


class ProviderUnavailableError(ProviderError):
    """The provider or its upstream service could not be reached."""


class ProviderTimeoutError(ProviderError):
    """The provider timed out while retrieving data."""


class ProviderInvalidResponseError(ProviderError):
    """The provider returned a response that could not be normalized safely."""


class MarketDataQualityError(MarketDataError):
    def __init__(
        self,
        *,
        provider: str,
        report: "SnapshotQualityReport",
        request_started_at: datetime,
        request_finished_at: datetime,
        latency_ms: float,
    ) -> None:
        super().__init__("full-market snapshot failed configured quality thresholds")
        self.provider = provider
        self.report = report
        self.request_started_at = request_started_at
        self.request_finished_at = request_finished_at
        self.latency_ms = latency_ms


class SnapshotPersistenceError(MarketDataError):
    def __init__(self, *, target: Path) -> None:
        super().__init__("validated snapshot could not be persisted")
        self.target = target
