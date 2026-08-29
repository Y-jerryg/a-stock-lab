from a_stock_lab.core.config import Settings
from a_stock_lab.shared.market_data.contracts import MarketDataProvider, TradingCalendar
from a_stock_lab.shared.market_data.models import (
    ProviderRetryPolicy,
    SnapshotQualityThresholds,
)

from .akshare import AkShareMarketDataProvider
from .akshare_calendar import AkShareTradingCalendar


def build_market_data_provider(settings: Settings) -> MarketDataProvider:
    """Compose the selected concrete provider at the outer adapter boundary."""
    return AkShareMarketDataProvider(
        retry_policy=ProviderRetryPolicy(
            max_attempts=settings.market_data_retry_attempts,
            delay_seconds=settings.market_data_retry_delay_seconds,
        )
    )


def build_trading_calendar() -> TradingCalendar:
    """Compose the concrete calendar only at the outer adapter boundary."""
    return AkShareTradingCalendar()


def build_snapshot_quality_thresholds(settings: Settings) -> SnapshotQualityThresholds:
    return SnapshotQualityThresholds(
        min_record_count=settings.market_snapshot_min_records,
        max_duplicate_symbols=settings.market_snapshot_max_duplicate_symbols,
        max_missing_symbol_ratio=settings.market_snapshot_max_missing_symbol_ratio,
        max_invalid_price_ratio=settings.market_snapshot_max_invalid_price_ratio,
        max_invalid_pct_change_ratio=settings.market_snapshot_max_invalid_pct_change_ratio,
        max_malformed_row_ratio=settings.market_snapshot_max_malformed_row_ratio,
        max_abs_pct_change=settings.market_snapshot_max_abs_pct_change,
    )
