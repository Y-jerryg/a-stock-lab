from functools import lru_cache

from a_stock_lab.core.config import get_settings
from a_stock_lab.features.tail_radar.adapters.daily_chart import FileChartStore
from a_stock_lab.features.tail_radar.application.daily_chart import DailyChartService
from a_stock_lab.features.tail_radar.application.queries import TailRadarQueryService
from a_stock_lab.features.tail_radar.factory import build_tail_radar_query_service
from a_stock_lab.features.trend_radar.adapters.akshare import AkShareTrendProvider
from a_stock_lab.features.trend_radar.config import TrendSettings


def get_tail_radar_query_service() -> TailRadarQueryService:
    return build_tail_radar_query_service()


@lru_cache(maxsize=1)
def get_daily_chart_service() -> DailyChartService:
    settings = get_settings()
    return DailyChartService(
        AkShareTrendProvider(
            TrendSettings(
                trend_fetch_workers=1,
                trend_provider_attempts=2,
                trend_provider_timeout_seconds=12,
            )
        ),
        FileChartStore(settings.runtime_data_dir),
    )
