from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.application.contracts import TailRadarRepository
from a_stock_lab.features.tail_radar.application.intraday_models import (
    IntradayAnalysisDisposition,
    TailRadarIntradayAnalysisCreate,
    TailRadarIntradayAnalysisData,
    TailRadarIntradayAnalysisPayload,
)
from a_stock_lab.features.tail_radar.application.intraday_service import (
    TailRadarIntradayAnalysisService,
)
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateData,
    TailRadarCandidatePayload,
)
from a_stock_lab.features.tail_radar.domain.errors import TailRadarIntradayAnalysisTimeError
from a_stock_lab.features.tail_radar.domain.intraday import (
    LEGACY_INTRADAY_CALCULATION_VERSION,
    LEGACY_INTRADAY_FEATURE_SCHEMA_VERSION,
    IntradayFeatureEngine,
)
from a_stock_lab.features.tail_radar.domain.screening import (
    TAIL_RADAR_SCREENING_RULE_VERSION,
    TailRadarDecisionOutcome,
    TailRadarDecisionReason,
    TailRadarScreeningConfiguration,
    TailRadarScreeningDecision,
    TailRadarSnapshotEvidence,
)
from a_stock_lab.shared.market_data.contracts import MarketDataProvider
from a_stock_lab.shared.market_data.models import (
    IntradayBar,
    IntradayBarRequest,
    MarketDataCapability,
    MarketSnapshotRecord,
    ProviderIntradayBarBatch,
    ProviderSnapshotBatch,
)

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
SNAPSHOT_ID = UUID("22222222-2222-2222-2222-222222222222")
SNAPSHOT_RUN_ID = UUID("33333333-3333-3333-3333-333333333333")
CANDIDATE_ID = UUID("44444444-4444-4444-4444-444444444444")
INTENDED = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
CANDIDATE_AS_OF = INTENDED + timedelta(seconds=2)
ANALYSIS_AS_OF = datetime(2026, 8, 28, 14, 35, tzinfo=MARKET_TIME_ZONE)
NOW = datetime(2026, 8, 28, 15, 5, tzinfo=MARKET_TIME_ZONE)


def candidate_data() -> TailRadarCandidateData:
    record = MarketSnapshotRecord(
        symbol="600000",
        name="fixture",
        price=10.25,
        pct_change=4.0,
        provider="fixture",
        fetched_at=CANDIDATE_AS_OF,
    )
    evidence = TailRadarSnapshotEvidence(
        snapshot_id=SNAPSHOT_ID,
        snapshot_run_id=SNAPSHOT_RUN_ID,
        trade_date=INTENDED.date(),
        intended_snapshot_time=INTENDED,
        actual_fetch_started_at=INTENDED + timedelta(seconds=1),
        actual_fetch_finished_at=CANDIDATE_AS_OF,
        provider="fixture",
        checksum_sha256="a" * 64,
        snapshot_schema_version=2,
    )
    return TailRadarCandidateData(
        candidate_id=CANDIDATE_ID,
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        symbol=record.symbol,
        trade_date=INTENDED.date(),
        as_of=CANDIDATE_AS_OF,
        payload=TailRadarCandidatePayload(
            screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
            rule_configuration=TailRadarScreeningConfiguration(),
            snapshot_evidence=evidence,
            snapshot_record=record,
            decision=TailRadarScreeningDecision(
                outcome=TailRadarDecisionOutcome.INCLUDED,
                reason=TailRadarDecisionReason.PCT_CHANGE_IN_RANGE,
                observed_pct_change=4.0,
                observed_price=10.25,
            ),
        ),
        created_at=INTENDED + timedelta(minutes=1),
    )


class FakeRepository:
    def __init__(self) -> None:
        self.analysis: TailRadarIntradayAnalysisData | None = None

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None:
        return candidate_data() if candidate_id == CANDIDATE_ID else None

    def get_intraday_analysis(
        self,
        *,
        candidate_id: UUID,
        analysis_as_of: datetime,
        calculation_version: str,
    ) -> TailRadarIntradayAnalysisData | None:
        if self.analysis is None:
            return None
        if (
            self.analysis.candidate_id == candidate_id
            and self.analysis.analysis_as_of == analysis_as_of
            and self.analysis.payload.calculation_version == calculation_version
        ):
            return self.analysis
        return None

    def save_intraday_analysis(
        self, analysis: TailRadarIntradayAnalysisCreate
    ) -> tuple[TailRadarIntradayAnalysisData, bool]:
        if self.analysis is not None:
            return self.analysis, False
        self.analysis = TailRadarIntradayAnalysisData(
            **analysis.model_dump(mode="python"),
            created_at=NOW,
        )
        return self.analysis, True


class FakeProvider:
    provider_id = "fixture"
    capabilities = frozenset({MarketDataCapability.INTRADAY_BARS})

    def __init__(self) -> None:
        self.calls = 0

    def fetch_full_market_snapshot(self) -> ProviderSnapshotBatch:
        raise AssertionError("intraday analysis must not fetch a full-market snapshot")

    def fetch_intraday_bars(self, request: IntradayBarRequest) -> ProviderIntradayBarBatch:
        self.calls += 1
        eligible = IntradayBar(
            symbol=request.symbol,
            ended_at=ANALYSIS_AS_OF,
            open=10.2,
            high=10.3,
            low=10.2,
            close=10.25,
            volume=10_000,
            amount=102_500,
            provider=self.provider_id,
            fetched_at=NOW,
        )
        future = IntradayBar(
            symbol=request.symbol,
            ended_at=ANALYSIS_AS_OF + timedelta(minutes=5),
            open=10.25,
            high=99,
            low=10.25,
            close=99,
            volume=999_999,
            amount=99_999_999,
            provider=self.provider_id,
            fetched_at=NOW,
        )
        return ProviderIntradayBarBatch(
            provider=self.provider_id,
            request=request,
            bars=(eligible, future),
            raw_record_count=2,
            provider_version="fixture-1",
            provider_metadata={"source": "fixture"},
            fetched_at=NOW,
        )


def service(repository: FakeRepository, provider: FakeProvider) -> TailRadarIntradayAnalysisService:
    return TailRadarIntradayAnalysisService(
        provider=cast(MarketDataProvider, provider),
        repository=cast(TailRadarRepository, repository),
        engine=IntradayFeatureEngine(),
        clock=lambda: NOW,
    )


def test_service_persists_point_in_time_features_and_replays_idempotently() -> None:
    repository = FakeRepository()
    provider = FakeProvider()
    analysis_service = service(repository, provider)

    first = analysis_service.execute(
        candidate_id=CANDIDATE_ID,
        analysis_as_of=ANALYSIS_AS_OF,
    )
    second = analysis_service.execute(
        candidate_id=CANDIDATE_ID,
        analysis_as_of=ANALYSIS_AS_OF,
    )

    assert first.disposition is IntradayAnalysisDisposition.CREATED
    assert second.disposition is IntradayAnalysisDisposition.IDEMPOTENT_REPLAY
    assert second.analysis.analysis_id == first.analysis.analysis_id
    assert provider.calls == 1
    assert first.analysis.payload.latest_bar_used is not None
    assert first.analysis.payload.latest_bar_used.ended_at == ANALYSIS_AS_OF
    assert first.analysis.payload.data_quality.future_bar_count == 1
    assert first.analysis.run_id == RUN_ID
    assert first.analysis.snapshot_id == SNAPSHOT_ID


def test_schema_one_artifact_remains_readable_without_inventing_a_bar_series() -> None:
    result = service(FakeRepository(), FakeProvider()).execute(
        candidate_id=CANDIDATE_ID,
        analysis_as_of=ANALYSIS_AS_OF,
    )
    legacy_payload = result.analysis.payload.model_dump(mode="python")
    legacy_payload.pop("used_bars")
    legacy_payload["feature_schema_version"] = LEGACY_INTRADAY_FEATURE_SCHEMA_VERSION
    legacy_payload["calculation_version"] = LEGACY_INTRADAY_CALCULATION_VERSION

    parsed = TailRadarIntradayAnalysisPayload.model_validate(legacy_payload)

    assert parsed.used_bars is None
    assert parsed.latest_bar_used is not None
    assert parsed.data_quality.used_bar_count == 1


@pytest.mark.parametrize(
    "analysis_as_of",
    [
        datetime(2026, 8, 28, 14, 30, 1, tzinfo=MARKET_TIME_ZONE),
        datetime(2026, 8, 29, 14, 35, tzinfo=MARKET_TIME_ZONE),
        datetime(2026, 8, 28, 15, 6, tzinfo=MARKET_TIME_ZONE),
    ],
)
def test_service_rejects_analysis_before_candidate_on_another_day_or_in_future(
    analysis_as_of: datetime,
) -> None:
    provider = FakeProvider()

    with pytest.raises(TailRadarIntradayAnalysisTimeError):
        service(FakeRepository(), provider).execute(
            candidate_id=CANDIDATE_ID,
            analysis_as_of=analysis_as_of,
        )

    assert provider.calls == 0
