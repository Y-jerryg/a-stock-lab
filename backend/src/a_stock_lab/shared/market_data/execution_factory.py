from pathlib import Path

from a_stock_lab.core.config import Settings
from a_stock_lab.database.session import SessionFactory
from a_stock_lab.shared.market_data.adapters.factory import (
    build_market_data_provider,
    build_snapshot_quality_thresholds,
    build_trading_calendar,
)
from a_stock_lab.shared.market_data.adapters.parquet import ParquetMarketSnapshotWriter
from a_stock_lab.shared.market_data.adapters.postgres import (
    PostgresSnapshotExecutionRepository,
)
from a_stock_lab.shared.market_data.execution_service import FullMarketSnapshotExecutionEngine
from a_stock_lab.shared.market_data.service import FullMarketSnapshotService


def build_snapshot_execution_repository() -> PostgresSnapshotExecutionRepository:
    return PostgresSnapshotExecutionRepository(SessionFactory)


def build_snapshot_execution_engine(settings: Settings) -> FullMarketSnapshotExecutionEngine:
    provider = build_market_data_provider(settings)
    return FullMarketSnapshotExecutionEngine(
        snapshot_service=FullMarketSnapshotService(
            provider=provider,
            thresholds=build_snapshot_quality_thresholds(settings),
        ),
        trading_calendar=build_trading_calendar(),
        storage=ParquetMarketSnapshotWriter(Path(settings.runtime_data_dir)),
        repository=build_snapshot_execution_repository(),
    )
