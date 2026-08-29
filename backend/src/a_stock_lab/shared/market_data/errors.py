from datetime import date, datetime
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
        actual_fetch_started_at: datetime,
        actual_fetch_finished_at: datetime,
        latency_ms: float,
    ) -> None:
        super().__init__("full-market snapshot failed configured quality thresholds")
        self.provider = provider
        self.report = report
        self.actual_fetch_started_at = actual_fetch_started_at
        self.actual_fetch_finished_at = actual_fetch_finished_at
        self.latency_ms = latency_ms


class SnapshotPersistenceError(MarketDataError):
    def __init__(self, *, target: Path) -> None:
        super().__init__("validated snapshot could not be persisted")
        self.target = target


class SnapshotArtifactIntegrityError(MarketDataError):
    """A persisted snapshot artifact failed path, checksum, schema, or manifest validation."""


class TradingCalendarError(MarketDataError):
    def __init__(self, *, provider: str, message: str) -> None:
        super().__init__(message)
        self.provider = provider


class TradingCalendarUnavailableError(TradingCalendarError):
    """The trading-calendar source could not be reached."""


class TradingCalendarInvalidResponseError(TradingCalendarError):
    """The trading-calendar source returned unreadable data."""


class TradingCalendarOutOfRangeError(TradingCalendarError):
    """The requested date is outside the provider's authoritative coverage."""


class SnapshotExecutionError(MarketDataError):
    """Base class for point-in-time execution failures."""


class SnapshotExecutionPersistenceError(SnapshotExecutionError):
    """PostgreSQL run or manifest persistence failed."""


class SnapshotManifestCommitUncertainError(SnapshotExecutionPersistenceError):
    """The client cannot safely determine whether the manifest transaction committed."""


class SnapshotArtifactCleanupError(SnapshotExecutionPersistenceError):
    """An unregistered snapshot artifact could not be removed safely."""


class NonTradingDayError(SnapshotExecutionError):
    def __init__(self, trade_date: date) -> None:
        super().__init__(f"{trade_date.isoformat()} is not an A-share trading day")
        self.trade_date = trade_date


class FutureIntendedSnapshotError(SnapshotExecutionError):
    """Execution was requested before its intended snapshot time."""


class HistoricalLiveSnapshotError(SnapshotExecutionError):
    """A live full-market feed cannot reconstruct an earlier trade date."""
