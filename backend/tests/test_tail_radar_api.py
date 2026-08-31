from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from a_stock_lab.api.v1.services.tail_radar import get_tail_radar_query_service
from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.application.intraday_models import (
    TailRadarIntradayAnalysisData,
    TailRadarIntradayAnalysisPayload,
)
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateData,
    TailRadarCandidatePage,
    TailRadarCandidatePayload,
    TailRadarRunData,
    TailRadarRunPage,
)
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TAIL_RADAR_WORKFLOW_VERSION,
    TailRadarWorkflowData,
    TailRadarWorkflowLifecycle,
)
from a_stock_lab.features.tail_radar.application.queries import TailRadarQueryService
from a_stock_lab.features.tail_radar.application.query_models import (
    TailRadarCandidateOverviewData,
    TailRadarCandidateOverviewPage,
)
from a_stock_lab.features.tail_radar.application.research_models import (
    ResearchTokenUsage,
    TailRadarResearchData,
    TailRadarResearchPayload,
    TailRadarResearchStatus,
)
from a_stock_lab.features.tail_radar.domain.intraday import (
    INTRADAY_CALCULATION_VERSION,
    IntradayFeatureConfiguration,
    IntradayFeatureEngine,
)
from a_stock_lab.features.tail_radar.domain.research import ResearchEvidenceQuality
from a_stock_lab.features.tail_radar.domain.screening import (
    TAIL_RADAR_SCREENING_RULE_VERSION,
    TailRadarDecisionOutcome,
    TailRadarDecisionReason,
    TailRadarScreeningConfiguration,
    TailRadarScreeningDecision,
    TailRadarSnapshotEvidence,
)
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.models import (
    AShareExchange,
    IntradayBar,
    IntradayBarRequest,
    MarketSnapshotRecord,
    ProviderIntradayBarBatch,
    SnapshotManifestStatus,
    SnapshotQualityReport,
    SnapshotQualityThresholds,
)
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest

INTENDED = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
FETCH_STARTED = INTENDED + timedelta(seconds=1)
FETCH_FINISHED = INTENDED + timedelta(seconds=2)
SCREEN_STARTED = INTENDED + timedelta(minutes=1)
SCREEN_FINISHED = SCREEN_STARTED + timedelta(seconds=1)
RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
SNAPSHOT_ID = UUID("22222222-2222-2222-2222-222222222222")
SNAPSHOT_RUN_ID = UUID("33333333-3333-3333-3333-333333333333")
CANDIDATE_ID = UUID("44444444-4444-4444-4444-444444444444")
ANALYSIS_ID = UUID("55555555-5555-5555-5555-555555555555")
ANALYSIS_AS_OF = datetime(2026, 8, 28, 14, 35, tzinfo=MARKET_TIME_ZONE)


def run_data() -> TailRadarRunData:
    return TailRadarRunData(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        trade_date=INTENDED.date(),
        intended_snapshot_time=INTENDED,
        actual_started_at=SCREEN_STARTED,
        actual_finished_at=SCREEN_FINISHED,
        status=RunStatus.SUCCEEDED,
        screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
        is_official=True,
        rule_configuration=TailRadarScreeningConfiguration(),
        evaluated_record_count=5_000,
        invalid_record_count=2,
        candidate_count=1,
        created_at=SCREEN_STARTED,
        updated_at=SCREEN_FINISHED,
    )


def candidate_data() -> TailRadarCandidateData:
    record = MarketSnapshotRecord(
        symbol="600000",
        exchange=AShareExchange.SHANGHAI,
        name="浦发银行",
        price=10.25,
        pct_change=2.5,
        amount=100_000_000,
        provider="fixture",
        fetched_at=FETCH_FINISHED,
    )
    evidence = TailRadarSnapshotEvidence(
        snapshot_id=SNAPSHOT_ID,
        snapshot_run_id=SNAPSHOT_RUN_ID,
        trade_date=INTENDED.date(),
        intended_snapshot_time=INTENDED,
        actual_fetch_started_at=FETCH_STARTED,
        actual_fetch_finished_at=FETCH_FINISHED,
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
        as_of=FETCH_FINISHED,
        payload=TailRadarCandidatePayload(
            screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
            rule_configuration=TailRadarScreeningConfiguration(),
            snapshot_evidence=evidence,
            snapshot_record=record,
            decision=TailRadarScreeningDecision(
                outcome=TailRadarDecisionOutcome.INCLUDED,
                reason=TailRadarDecisionReason.PCT_CHANGE_IN_RANGE,
                observed_pct_change=2.5,
                observed_price=10.25,
            ),
        ),
        created_at=SCREEN_FINISHED,
    )


def intraday_analysis_data() -> TailRadarIntradayAnalysisData:
    candidate = candidate_data()
    request = IntradayBarRequest(
        symbol=candidate.symbol,
        start_at=datetime(2026, 8, 28, 9, 30, tzinfo=MARKET_TIME_ZONE),
        end_at=ANALYSIS_AS_OF,
    )
    bar = IntradayBar(
        symbol=candidate.symbol,
        ended_at=ANALYSIS_AS_OF,
        open=10.2,
        high=10.3,
        low=10.2,
        close=10.25,
        volume=10_000,
        amount=102_500,
        provider="fixture-intraday",
        fetched_at=ANALYSIS_AS_OF + timedelta(seconds=1),
    )
    batch = ProviderIntradayBarBatch(
        provider="fixture-intraday",
        request=request,
        bars=(bar,),
        raw_record_count=1,
        provider_version="fixture-1",
        fetched_at=ANALYSIS_AS_OF + timedelta(seconds=1),
    )
    engine = IntradayFeatureEngine()
    computation = engine.calculate(batch=batch, analysis_as_of=ANALYSIS_AS_OF)
    return TailRadarIntradayAnalysisData(
        analysis_id=ANALYSIS_ID,
        candidate_id=candidate.candidate_id,
        run_id=candidate.run_id,
        snapshot_id=candidate.snapshot_id,
        symbol=candidate.symbol,
        trade_date=candidate.trade_date,
        analysis_as_of=ANALYSIS_AS_OF,
        payload=TailRadarIntradayAnalysisPayload.from_computation(
            symbol=candidate.symbol,
            candidate_id=candidate.candidate_id,
            source_run_id=candidate.run_id,
            source_snapshot_id=candidate.snapshot_id,
            source_candidate_as_of=candidate.as_of,
            provider=batch.provider,
            provider_version=batch.provider_version,
            provider_metadata={},
            provider_fetched_at=batch.fetched_at,
            intraday_request=request,
            configuration=IntradayFeatureConfiguration(),
            computation=computation,
        ),
        created_at=ANALYSIS_AS_OF + timedelta(seconds=2),
    )


def research_data() -> TailRadarResearchData:
    candidate = candidate_data()
    payload = TailRadarResearchPayload(
        concise_summary="No useful web evidence was verified at the requested cutoff.",
        verified_facts=(),
        likely_drivers=(),
        company_context=(),
        sector_context=(),
        market_context=(),
        positive_factors=(),
        risk_factors=(),
        unresolved_questions=("Publication timing remains unresolved.",),
        evidence_quality=ResearchEvidenceQuality.INSUFFICIENT,
        confidence=0,
        symbol=candidate.symbol,
        candidate_id=candidate.candidate_id,
        source_run_id=candidate.run_id,
        source_snapshot_id=candidate.snapshot_id,
        source_candidate_as_of=candidate.as_of,
        analysis_as_of=ANALYSIS_AS_OF,
        provider="fixture-research",
        requested_model="fixture-model",
        model_identifier="fixture-model-snapshot",
        provider_response_id="resp_fixture",
        prompt_sha256="b" * 64,
        source_references=(),
        token_usage=ResearchTokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        provider_metadata={"api": "responses"},
    )
    return TailRadarResearchData(
        research_id=UUID("66666666-6666-4666-8666-666666666666"),
        artifact_id=UUID("77777777-7777-4777-8777-777777777777"),
        candidate_id=candidate.candidate_id,
        run_id=candidate.run_id,
        snapshot_id=candidate.snapshot_id,
        symbol=candidate.symbol,
        trade_date=candidate.trade_date,
        analysis_as_of=ANALYSIS_AS_OF,
        prompt_version=payload.prompt_version,
        prompt_sha256=payload.prompt_sha256,
        provider=payload.provider,
        requested_model=payload.requested_model,
        actual_model=payload.model_identifier,
        provider_response_id=payload.provider_response_id,
        status=TailRadarResearchStatus.NO_EVIDENCE,
        is_forced=False,
        base_research_id=None,
        token_usage=payload.token_usage,
        error_code=None,
        actual_started_at=ANALYSIS_AS_OF + timedelta(seconds=1),
        actual_finished_at=ANALYSIS_AS_OF + timedelta(seconds=2),
        created_at=ANALYSIS_AS_OF + timedelta(seconds=2),
        updated_at=ANALYSIS_AS_OF + timedelta(seconds=2),
        payload=payload,
        sources=(),
    )


def workflow_data() -> TailRadarWorkflowData:
    return TailRadarWorkflowData(
        workflow_run_id=UUID("88888888-8888-4888-8888-888888888888"),
        trade_date=INTENDED.date(),
        intended_snapshot_time=INTENDED,
        analysis_as_of=ANALYSIS_AS_OF,
        workflow_version=TAIL_RADAR_WORKFLOW_VERSION,
        lifecycle=TailRadarWorkflowLifecycle.SUCCEEDED,
        execution_status=RunStatus.SUCCEEDED,
        snapshot_run_id=SNAPSHOT_RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        screening_run_id=RUN_ID,
        candidate_count=1,
        technical_succeeded_count=1,
        technical_failed_count=0,
        technical_pending_count=0,
        research_succeeded_count=0,
        research_no_evidence_count=1,
        research_failed_count=0,
        research_pending_count=0,
        error_stage=None,
        error_code=None,
        actual_started_at=SCREEN_STARTED,
        actual_finished_at=ANALYSIS_AS_OF + timedelta(seconds=2),
        created_at=SCREEN_STARTED,
        updated_at=ANALYSIS_AS_OF + timedelta(seconds=2),
    )


def snapshot_manifest() -> PersistedSnapshotManifest:
    return PersistedSnapshotManifest(
        snapshot_id=SNAPSHOT_ID,
        run_id=SNAPSHOT_RUN_ID,
        trade_date=INTENDED.date(),
        intended_snapshot_time=INTENDED,
        actual_fetch_started_at=FETCH_STARTED,
        actual_fetch_finished_at=FETCH_FINISHED,
        provider="fixture",
        provider_version="fixture-1",
        provider_metadata={},
        storage_key=f"market-data/{INTENDED.date()}/fixture.parquet",
        checksum_sha256="a" * 64,
        row_count=5_000,
        latency_ms=1_000,
        quality_report=SnapshotQualityReport(
            passed=True,
            raw_record_count=5_000,
            normalized_record_count=5_000,
            duplicate_symbol_count=0,
            missing_symbol_count=0,
            invalid_price_count=0,
            invalid_pct_change_count=0,
            malformed_row_count=0,
            missing_symbol_ratio=0,
            invalid_price_ratio=0,
            invalid_pct_change_ratio=0,
            malformed_row_ratio=0,
            thresholds=SnapshotQualityThresholds(min_record_count=4_000),
        ),
        schema_version=2,
        status=SnapshotManifestStatus.AVAILABLE,
        persisted_at=FETCH_FINISHED + timedelta(seconds=1),
    )


class FakeQueryService:
    def latest_run(self) -> TailRadarRunData | None:
        return run_data()

    def list_runs(self, *, offset: int, limit: int) -> TailRadarRunPage:
        assert (offset, limit) == (20, 20)
        return TailRadarRunPage(items=(run_data(),), total=21, offset=offset, limit=limit)

    def get_run(self, run_id: UUID) -> TailRadarRunData | None:
        return run_data() if run_id == RUN_ID else None

    def list_candidates(self, *, run_id: UUID, offset: int, limit: int) -> TailRadarCandidatePage:
        assert run_id == RUN_ID
        assert (offset, limit) == (0, 25)
        return TailRadarCandidatePage(
            items=(candidate_data(),),
            total=1,
            offset=offset,
            limit=limit,
        )

    def list_candidate_overviews(
        self, *, run_id: UUID, offset: int, limit: int
    ) -> TailRadarCandidateOverviewPage:
        page = self.list_candidates(run_id=run_id, offset=offset, limit=limit)
        return TailRadarCandidateOverviewPage(
            items=tuple(
                TailRadarCandidateOverviewData(
                    candidate=item,
                    intraday_analysis=intraday_analysis_data(),
                    workflow_state=None,
                )
                for item in page.items
            ),
            total=page.total,
            offset=page.offset,
            limit=page.limit,
        )

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None:
        return candidate_data() if candidate_id == CANDIDATE_ID else None

    def get_latest_intraday_analysis(self, candidate_id: UUID) -> TailRadarIntradayAnalysisData:
        assert candidate_id == CANDIDATE_ID
        return intraday_analysis_data()

    def get_latest_research(self, candidate_id: UUID) -> TailRadarResearchData:
        assert candidate_id == CANDIDATE_ID
        return research_data()

    def get_candidate_workflow_state(self, candidate_id: UUID) -> None:
        assert candidate_id == CANDIDATE_ID
        return None

    def get_workflow_for_run(self, run_id: UUID) -> TailRadarWorkflowData | None:
        return workflow_data() if run_id == RUN_ID else None

    def get_snapshot(self, snapshot_id: UUID) -> PersistedSnapshotManifest | None:
        return snapshot_manifest() if snapshot_id == SNAPSHOT_ID else None


def override_service(app: FastAPI) -> None:
    fake = cast(TailRadarQueryService, FakeQueryService())
    app.dependency_overrides[get_tail_radar_query_service] = lambda: fake


def test_public_tail_radar_run_reads_are_paginated_and_read_only(
    app: FastAPI,
    client: TestClient,
) -> None:
    override_service(app)

    latest = client.get("/api/v1/tail-radar/runs/latest")
    history = client.get("/api/v1/tail-radar/runs?page=2&page_size=20")
    detail = client.get(f"/api/v1/tail-radar/runs/{RUN_ID}")
    summary = client.get(f"/api/v1/tail-radar/runs/{RUN_ID}/summary")

    assert latest.status_code == 200
    assert latest.json()["screening_rule_version"] == TAIL_RADAR_SCREENING_RULE_VERSION
    assert latest.json()["intended_snapshot_time"].endswith("+08:00")
    assert history.status_code == 200
    assert history.json()["page"] == 2
    assert history.json()["page_size"] == 20
    assert history.json()["total"] == 21
    assert detail.status_code == 200
    assert summary.status_code == 200
    assert summary.json()["workflow"]["lifecycle"] == "succeeded"
    assert summary.json()["snapshot"]["row_count"] == 5_000
    assert summary.json()["snapshot"]["quality_report"]["passed"] is True
    assert client.post("/api/v1/tail-radar/runs").status_code == 405
    assert client.get("/api/v1/tail-radar/runs?page_size=101").status_code == 422


def test_public_candidate_reads_preserve_explanatory_snapshot_evidence(
    app: FastAPI,
    client: TestClient,
) -> None:
    override_service(app)

    candidates = client.get(f"/api/v1/tail-radar/runs/{RUN_ID}/candidates?page=1&page_size=25")
    detail = client.get(f"/api/v1/tail-radar/candidates/{CANDIDATE_ID}")

    assert candidates.status_code == 200
    assert candidates.json()["items"][0]["pct_change"] == 2.5
    assert candidates.json()["items"][0]["price"] == 10.25
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["snapshot_data"]["symbol"] == "600000"
    assert payload["snapshot_data"]["pct_change"] == 2.5
    assert payload["decision"] == {
        "outcome": "included",
        "reason": "pct_change_in_inclusive_range",
        "observed_pct_change": 2.5,
        "observed_price": 10.25,
        "inclusive_min": 2.0,
        "inclusive_max": 3.0,
    }
    assert payload["snapshot_evidence"]["actual_fetch_finished_at"].endswith("+08:00")
    assert "storage_key" not in payload["snapshot_evidence"]
    intraday = payload["intraday_analysis"]
    assert intraday["calculation_version"] == INTRADAY_CALCULATION_VERSION
    assert intraday["source_run_id"] == str(RUN_ID)
    assert intraday["source_snapshot_id"] == str(SNAPSHOT_ID)
    assert intraday["latest_bar_used"]["ended_at"].endswith("+08:00")
    assert intraday["latest_bar_used"]["ended_at"] <= intraday["analysis_as_of"]
    assert intraday["used_bars"][-1] == intraday["latest_bar_used"]
    assert all(bar["ended_at"] <= intraday["analysis_as_of"] for bar in intraday["used_bars"])
    research = payload["web_research"]
    assert research["status"] == "no_evidence"
    assert research["evidence_quality"] == "insufficient"
    assert research["prompt_version"] == "tail-radar-research-v1"
    assert "provider_response_id" not in research
    assert "token_usage" not in research


def test_public_intraday_schema_does_not_expose_internal_domain_models(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert "IntradayBarResponse" in schemas
    assert "IntradayDataQualityResponse" in schemas
    assert "IntradayBar" not in schemas
    assert "IntradayDataQualityReport" not in schemas
    assert "IntradayFeatureConfiguration" not in schemas


def test_public_tail_radar_reads_return_typed_not_found_errors(
    app: FastAPI,
    client: TestClient,
) -> None:
    override_service(app)
    unknown = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")

    run_response = client.get(f"/api/v1/tail-radar/runs/{unknown}")
    candidate_response = client.get(f"/api/v1/tail-radar/candidates/{unknown}")

    assert run_response.status_code == 404
    assert run_response.json()["error"]["code"] == "tail_radar_run_not_found"
    assert candidate_response.status_code == 404
    assert candidate_response.json()["error"]["code"] == "tail_radar_candidate_not_found"
