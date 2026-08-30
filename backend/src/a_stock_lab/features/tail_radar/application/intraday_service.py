from collections.abc import Callable
from datetime import datetime, time
from uuid import UUID, uuid4

from a_stock_lab.core.time import MARKET_TIME_ZONE, as_market_timezone, now_in_market_timezone
from a_stock_lab.features.tail_radar.application.contracts import TailRadarRepository
from a_stock_lab.features.tail_radar.application.intraday_models import (
    IntradayAnalysisDisposition,
    TailRadarIntradayAnalysisCreate,
    TailRadarIntradayAnalysisPayload,
    TailRadarIntradayAnalysisResult,
)
from a_stock_lab.features.tail_radar.domain.errors import (
    TailRadarCandidateNotFoundError,
    TailRadarIntradayAnalysisError,
    TailRadarIntradayAnalysisTimeError,
)
from a_stock_lab.features.tail_radar.domain.intraday import IntradayFeatureEngine
from a_stock_lab.shared.market_data.contracts import MarketDataProvider
from a_stock_lab.shared.market_data.models import (
    IntradayBarRequest,
    MarketDataCapability,
)


class TailRadarIntradayAnalysisService:
    """Fetch, point-in-time filter, calculate, and persist one candidate analysis."""

    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        repository: TailRadarRepository,
        engine: IntradayFeatureEngine,
        clock: Callable[[], datetime] = now_in_market_timezone,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._engine = engine
        self._clock = clock

    def execute(
        self,
        *,
        candidate_id: UUID,
        analysis_as_of: datetime,
    ) -> TailRadarIntradayAnalysisResult:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise TailRadarCandidateNotFoundError("Tail Radar candidate was not found")
        try:
            as_of = as_market_timezone(analysis_as_of)
        except ValueError as exc:
            raise TailRadarIntradayAnalysisTimeError(
                "analysis_as_of must include an explicit UTC offset"
            ) from exc
        now = as_market_timezone(self._clock())
        if as_of > now:
            raise TailRadarIntradayAnalysisTimeError("analysis_as_of cannot be in the future")
        if as_of.date() != candidate.trade_date:
            raise TailRadarIntradayAnalysisTimeError(
                "analysis_as_of must be on the candidate trade date"
            )
        if as_of < candidate.as_of:
            raise TailRadarIntradayAnalysisTimeError(
                "analysis_as_of cannot precede candidate snapshot evidence"
            )
        existing = self._repository.get_intraday_analysis(
            candidate_id=candidate_id,
            analysis_as_of=as_of,
            calculation_version=self._engine.version,
        )
        if existing is not None:
            return TailRadarIntradayAnalysisResult(
                disposition=IntradayAnalysisDisposition.IDEMPOTENT_REPLAY,
                analysis=existing,
            )
        if MarketDataCapability.INTRADAY_BARS not in self._provider.capabilities:
            raise TailRadarIntradayAnalysisError(
                "configured market provider does not support intraday bars"
            )

        request = IntradayBarRequest(
            symbol=candidate.symbol,
            start_at=datetime.combine(candidate.trade_date, time(9, 30), tzinfo=MARKET_TIME_ZONE),
            end_at=as_of,
        )
        batch = self._provider.fetch_intraday_bars(request)
        if batch.request != request or batch.provider != self._provider.provider_id:
            raise TailRadarIntradayAnalysisError(
                "intraday provider response does not match the requested analysis"
            )
        computation = self._engine.calculate(batch=batch, analysis_as_of=as_of)
        payload = TailRadarIntradayAnalysisPayload.from_computation(
            symbol=candidate.symbol,
            candidate_id=candidate.candidate_id,
            source_run_id=candidate.run_id,
            source_snapshot_id=candidate.snapshot_id,
            source_candidate_as_of=candidate.as_of,
            provider=batch.provider,
            provider_version=batch.provider_version,
            provider_metadata=batch.provider_metadata,
            provider_fetched_at=batch.fetched_at,
            intraday_request=request,
            configuration=self._engine.configuration,
            computation=computation,
        )
        analysis, created = self._repository.save_intraday_analysis(
            TailRadarIntradayAnalysisCreate(
                analysis_id=uuid4(),
                candidate_id=candidate.candidate_id,
                run_id=candidate.run_id,
                snapshot_id=candidate.snapshot_id,
                symbol=candidate.symbol,
                trade_date=candidate.trade_date,
                analysis_as_of=as_of,
                payload=payload,
            )
        )
        return TailRadarIntradayAnalysisResult(
            disposition=(
                IntradayAnalysisDisposition.CREATED
                if created
                else IntradayAnalysisDisposition.IDEMPOTENT_REPLAY
            ),
            analysis=analysis,
        )
