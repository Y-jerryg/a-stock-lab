from pathlib import Path

from pydantic import SecretStr

from a_stock_lab.core.config import Settings
from a_stock_lab.database.session import SessionFactory
from a_stock_lab.features.tail_radar.adapters.openai_research import (
    OPENAI_RESEARCH_PROVIDER_ID,
    OpenAIResearchProvider,
)
from a_stock_lab.features.tail_radar.adapters.postgres import PostgresTailRadarRepository
from a_stock_lab.features.tail_radar.adapters.schedule_postgres import (
    PostgresTailRadarScheduleRepository,
)
from a_stock_lab.features.tail_radar.adapters.unavailable_research import (
    UnavailableResearchProvider,
)
from a_stock_lab.features.tail_radar.adapters.worker_heartbeat import JsonWorkerHeartbeatStore
from a_stock_lab.features.tail_radar.application.contracts import TailRadarResearchProvider
from a_stock_lab.features.tail_radar.application.intraday_service import (
    TailRadarIntradayAnalysisService,
)
from a_stock_lab.features.tail_radar.application.on_demand_research_service import (
    TailRadarOnDemandResearchService,
)
from a_stock_lab.features.tail_radar.application.orchestration_service import (
    TailRadarApplicationService,
)
from a_stock_lab.features.tail_radar.application.queries import TailRadarQueryService
from a_stock_lab.features.tail_radar.application.research_service import TailRadarResearchService
from a_stock_lab.features.tail_radar.application.scheduling_service import (
    TailRadarScheduledExecutionService,
)
from a_stock_lab.features.tail_radar.application.service import TailRadarScreeningService
from a_stock_lab.features.tail_radar.application.worker import TailRadarWorker
from a_stock_lab.features.tail_radar.domain.errors import TailRadarResearchConfigurationError
from a_stock_lab.features.tail_radar.domain.intraday import IntradayFeatureEngine
from a_stock_lab.features.tail_radar.domain.screening import TailRadarScreeningRule
from a_stock_lab.shared.market_data.adapters.factory import (
    build_market_data_provider,
    build_trading_calendar,
)
from a_stock_lab.shared.market_data.adapters.parquet import ParquetMarketSnapshotReader
from a_stock_lab.shared.market_data.contracts import MarketDataProvider, TradingCalendar
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
    *,
    provider: MarketDataProvider | None = None,
) -> TailRadarIntradayAnalysisService:
    return TailRadarIntradayAnalysisService(
        provider=provider or build_market_data_provider(settings),
        repository=build_tail_radar_repository(),
        engine=IntradayFeatureEngine(),
    )


def build_tail_radar_research_service(
    settings: Settings,
    *,
    api_key: SecretStr | None = None,
    allow_unconfigured: bool = False,
) -> TailRadarResearchService:
    secret = api_key if api_key is not None else settings.openai_api_key
    configured_api_key = None if secret is None else secret.get_secret_value().strip()
    if not configured_api_key:
        if not allow_unconfigured:
            raise TailRadarResearchConfigurationError(
                "OPENAI_API_KEY is required only for the explicit web-research diagnostic"
            )
        provider: TailRadarResearchProvider = UnavailableResearchProvider(
            provider_id=OPENAI_RESEARCH_PROVIDER_ID,
            model_id=settings.openai_research_model,
            reason="OPENAI_API_KEY is not configured in the backend environment",
        )
    else:
        provider = OpenAIResearchProvider(
            api_key=configured_api_key,
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


def build_tail_radar_application_service(
    settings: Settings,
    *,
    market_data_provider: MarketDataProvider | None = None,
    trading_calendar: TradingCalendar | None = None,
) -> TailRadarApplicationService:
    repository = build_tail_radar_repository()
    provider = market_data_provider or build_market_data_provider(settings)
    calendar = trading_calendar or build_trading_calendar()
    return TailRadarApplicationService(
        snapshot_execution=build_snapshot_execution_engine(
            settings,
            provider=provider,
            trading_calendar=calendar,
        ),
        screening=build_tail_radar_screening_service(settings),
        intraday=build_tail_radar_intraday_analysis_service(settings, provider=provider),
        tail_radar_repository=repository,
        workflow_repository=repository,
        intraday_workers=settings.tail_radar_intraday_workers,
    )


def build_tail_radar_on_demand_research_service(
    settings: Settings,
    *,
    user_api_key: SecretStr,
) -> TailRadarOnDemandResearchService:
    repository = build_tail_radar_repository()
    return TailRadarOnDemandResearchService(
        research=build_tail_radar_research_service(settings, api_key=user_api_key),
        repository=repository,
    )


def build_tail_radar_scheduler(settings: Settings) -> TailRadarScheduledExecutionService:
    repository = build_tail_radar_repository()
    schedule_repository = PostgresTailRadarScheduleRepository(SessionFactory)
    provider = build_market_data_provider(settings)
    calendar = build_trading_calendar()
    application = build_tail_radar_application_service(
        settings,
        market_data_provider=provider,
        trading_calendar=calendar,
    )
    api_key = (
        None
        if settings.openai_api_key is None
        else settings.openai_api_key.get_secret_value().strip()
    )
    return TailRadarScheduledExecutionService(
        trading_calendar=calendar,
        market_data_provider=provider,
        schedule_repository=schedule_repository,
        workflow_repository=repository,
        application_factory=lambda: application,
        openai_configured=bool(api_key or settings.tail_radar_on_demand_research_enabled),
        preflight_lead=settings.tail_radar_worker_preflight_lead,
        maximum_start_delay=settings.tail_radar_worker_maximum_start_delay,
    )


def build_tail_radar_worker(settings: Settings) -> TailRadarWorker:
    heartbeat_path = Path(settings.runtime_data_dir) / "worker" / "tail-radar-heartbeat.json"
    return TailRadarWorker(
        scheduler=build_tail_radar_scheduler(settings),
        heartbeat_store=JsonWorkerHeartbeatStore(heartbeat_path),
        poll_interval_seconds=settings.tail_radar_worker_poll_interval_seconds,
    )


def build_tail_radar_heartbeat_store(settings: Settings) -> JsonWorkerHeartbeatStore:
    return JsonWorkerHeartbeatStore(
        Path(settings.runtime_data_dir) / "worker" / "tail-radar-heartbeat.json"
    )
