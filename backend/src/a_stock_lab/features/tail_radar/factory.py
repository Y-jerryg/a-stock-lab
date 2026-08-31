from pathlib import Path

from a_stock_lab.core.config import Settings
from a_stock_lab.database.session import SessionFactory
from a_stock_lab.features.tail_radar.adapters.openai_research import OpenAIResearchProvider
from a_stock_lab.features.tail_radar.adapters.postgres import PostgresTailRadarRepository
from a_stock_lab.features.tail_radar.application.intraday_service import (
    TailRadarIntradayAnalysisService,
)
from a_stock_lab.features.tail_radar.application.orchestration_service import (
    TailRadarApplicationService,
)
from a_stock_lab.features.tail_radar.application.queries import TailRadarQueryService
from a_stock_lab.features.tail_radar.application.research_service import TailRadarResearchService
from a_stock_lab.features.tail_radar.application.service import TailRadarScreeningService
from a_stock_lab.features.tail_radar.domain.errors import TailRadarResearchConfigurationError
from a_stock_lab.features.tail_radar.domain.intraday import IntradayFeatureEngine
from a_stock_lab.features.tail_radar.domain.screening import TailRadarScreeningRule
from a_stock_lab.shared.market_data.adapters.factory import build_market_data_provider
from a_stock_lab.shared.market_data.adapters.parquet import ParquetMarketSnapshotReader
from a_stock_lab.shared.market_data.execution_factory import build_snapshot_execution_engine


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


def build_tail_radar_intraday_analysis_service(
    settings: Settings,
) -> TailRadarIntradayAnalysisService:
    return TailRadarIntradayAnalysisService(
        provider=build_market_data_provider(settings),
        repository=build_tail_radar_repository(),
        engine=IntradayFeatureEngine(),
    )


def build_tail_radar_research_service(settings: Settings) -> TailRadarResearchService:
    api_key = (
        None
        if settings.openai_api_key is None
        else settings.openai_api_key.get_secret_value().strip()
    )
    if not api_key:
        raise TailRadarResearchConfigurationError(
            "OPENAI_API_KEY is required only for the explicit web-research diagnostic"
        )
    provider = OpenAIResearchProvider(
        api_key=api_key,
        model=settings.openai_research_model,
        timeout_seconds=settings.openai_research_timeout_seconds,
        max_output_tokens=settings.openai_research_max_output_tokens,
        max_web_search_calls=settings.openai_research_max_web_search_calls,
        search_context_size=settings.openai_research_search_context_size,
    )
    return TailRadarResearchService(
        provider=provider,
        repository=build_tail_radar_repository(),
    )


def build_tail_radar_application_service(settings: Settings) -> TailRadarApplicationService:
    repository = build_tail_radar_repository()
    return TailRadarApplicationService(
        snapshot_execution=build_snapshot_execution_engine(settings),
        screening=build_tail_radar_screening_service(settings),
        intraday=build_tail_radar_intraday_analysis_service(settings),
        research=build_tail_radar_research_service(settings),
        tail_radar_repository=repository,
        workflow_repository=repository,
    )
