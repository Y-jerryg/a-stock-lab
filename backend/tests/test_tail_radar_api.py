from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from a_stock_lab.api.v1.services.tail_radar import get_tail_radar_query_service
from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateData,
    TailRadarCandidatePage,
    TailRadarCandidatePayload,
    TailRadarRunData,
    TailRadarRunPage,
)
from a_stock_lab.features.tail_radar.application.queries import TailRadarQueryService
from a_stock_lab.features.tail_radar.domain.screening import (
    TAIL_RADAR_SCREENING_RULE_VERSION,
    TailRadarDecisionOutcome,
    TailRadarDecisionReason,
    TailRadarScreeningConfiguration,
    TailRadarScreeningDecision,
    TailRadarSnapshotEvidence,
)
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.models import AShareExchange, MarketSnapshotRecord

INTENDED = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
FETCH_STARTED = INTENDED + timedelta(seconds=1)
FETCH_FINISHED = INTENDED + timedelta(seconds=2)
SCREEN_STARTED = INTENDED + timedelta(minutes=1)
SCREEN_FINISHED = SCREEN_STARTED + timedelta(seconds=1)
RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
SNAPSHOT_ID = UUID("22222222-2222-2222-2222-222222222222")
SNAPSHOT_RUN_ID = UUID("33333333-3333-3333-3333-333333333333")
CANDIDATE_ID = UUID("44444444-4444-4444-4444-444444444444")


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

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None:
        return candidate_data() if candidate_id == CANDIDATE_ID else None


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

    assert latest.status_code == 200
    assert latest.json()["screening_rule_version"] == TAIL_RADAR_SCREENING_RULE_VERSION
    assert latest.json()["intended_snapshot_time"].endswith("+08:00")
    assert history.status_code == 200
    assert history.json()["page"] == 2
    assert history.json()["page_size"] == 20
    assert history.json()["total"] == 21
    assert detail.status_code == 200
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
