from sqlalchemy import create_engine

from a_stock_lab.core.config import get_settings
from a_stock_lab.features.trend_radar.adapters.akshare import AkShareTrendProvider
from a_stock_lab.features.trend_radar.adapters.heartbeat import LocalWorkerHeartbeat
from a_stock_lab.features.trend_radar.adapters.postgres import PostgresTrendRepository
from a_stock_lab.features.trend_radar.adapters.static_publication import StaticResultPublisher
from a_stock_lab.features.trend_radar.application.service import TrendRadarScanService
from a_stock_lab.features.trend_radar.config import TrendSettings


def create_repository() -> PostgresTrendRepository:
    return PostgresTrendRepository(
        create_engine(get_settings().resolved_database_url, pool_pre_ping=True)
    )


def create_heartbeat() -> LocalWorkerHeartbeat:
    return LocalWorkerHeartbeat(
        get_settings().runtime_data_dir / "worker/trend-radar-heartbeat.json"
    )


def create_service() -> TrendRadarScanService:
    config = TrendSettings()
    provider = AkShareTrendProvider(config)
    repository = create_repository()
    return TrendRadarScanService(
        config=config,
        universe=provider,
        heat=provider,
        market=provider,
        calendar=provider,
        local=repository,
        publisher=StaticResultPublisher(
            repository, get_settings().runtime_data_dir / "public/trend-radar"
        ),
    )
