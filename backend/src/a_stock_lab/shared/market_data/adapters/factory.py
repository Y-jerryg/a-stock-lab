from a_stock_lab.core.config import Settings
from a_stock_lab.shared.market_data.contracts import MarketDataProvider
from a_stock_lab.shared.market_data.models import ProviderRetryPolicy

from .akshare import AkShareMarketDataProvider


def build_market_data_provider(settings: Settings) -> MarketDataProvider:
    """Compose the selected concrete provider at the outer adapter boundary."""
    return AkShareMarketDataProvider(
        retry_policy=ProviderRetryPolicy(
            max_attempts=settings.market_data_retry_attempts,
            delay_seconds=settings.market_data_retry_delay_seconds,
        )
    )
