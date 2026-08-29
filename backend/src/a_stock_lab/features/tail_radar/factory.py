from pathlib import Path

from a_stock_lab.core.config import Settings
from a_stock_lab.database.session import SessionFactory
from a_stock_lab.features.tail_radar.adapters.postgres import PostgresTailRadarRepository
from a_stock_lab.features.tail_radar.application.queries import TailRadarQueryService
from a_stock_lab.features.tail_radar.application.service import TailRadarScreeningService
from a_stock_lab.features.tail_radar.domain.screening import TailRadarScreeningRule
from a_stock_lab.shared.market_data.adapters.parquet import ParquetMarketSnapshotReader


def build_tail_radar_repository() -> PostgresTailRadarRepository:
    return PostgresTailRadarRepository(SessionFactory)


def build_tail_radar_screening_service(settings: Settings) -> TailRadarScreeningService:
    return TailRadarScreeningService(
        rule=TailRadarScreeningRule(),
        reader=ParquetMarketSnapshotReader(Path(settings.runtime_data_dir)),
        repository=build_tail_radar_repository(),
    )


def build_tail_radar_query_service() -> TailRadarQueryService:
    return TailRadarQueryService(build_tail_radar_repository())
