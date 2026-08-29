from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.application.contracts import TailRadarRepository
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateCreate,
    TailRadarCandidateData,
    TailRadarCandidatePage,
    TailRadarCandidatePayload,
    TailRadarExecutionDisposition,
    TailRadarRunClaim,
    TailRadarRunData,
    TailRadarRunPage,
)
from a_stock_lab.features.tail_radar.application.service import TailRadarScreeningService
from a_stock_lab.features.tail_radar.domain.errors import (
    TailRadarCommitUncertainError,
    TailRadarSnapshotIntegrityError,
    TailRadarSourceSnapshotNotFoundError,
)
from a_stock_lab.features.tail_radar.domain.screening import (
    TAIL_RADAR_SCREENING_RULE_VERSION,
    TailRadarDecisionOutcome,
    TailRadarDecisionReason,
    TailRadarScreeningConfiguration,
    TailRadarScreeningDecision,
    TailRadarScreeningInput,
    TailRadarScreeningRule,
    TailRadarSnapshotEvidence,
)
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.models import (
    FullMarketSnapshot,
    MarketSnapshotRecord,
    SnapshotManifest,
    SnapshotManifestStatus,
    SnapshotQualityReport,
    SnapshotQualityThresholds,
)
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest

INTENDED = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
FETCH_STARTED = INTENDED + timedelta(seconds=1)
FETCH_FINISHED = INTENDED + timedelta(seconds=2)
PERSISTED = INTENDED + timedelta(seconds=3)
SCREEN_STARTED = INTENDED + timedelta(minutes=1)
SCREEN_FINISHED = SCREEN_STARTED + timedelta(seconds=1)
SNAPSHOT_ID = UUID("11111111-1111-1111-1111-111111111111")
SNAPSHOT_RUN_ID = UUID("22222222-2222-2222-2222-222222222222")


def snapshot_evidence() -> TailRadarSnapshotEvidence:
    return TailRadarSnapshotEvidence(
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


def record(
    *, symbol: str = "600000", pct_change: float | None, price: float | None = 10
) -> MarketSnapshotRecord:
    return MarketSnapshotRecord(
        symbol=symbol,
        name="*ST Fixture",
        price=price,
        pct_change=pct_change,
        provider="fixture",
        fetched_at=FETCH_FINISHED,
    )


@pytest.mark.parametrize(
    ("pct_change", "expected"),
    [
        (1.99, False),
        (2.00, True),
        (2.50, True),
        (3.00, True),
        (3.01, False),
    ],
)
def test_tail_radar_v1_exact_inclusive_boundaries(
    pct_change: float,
    expected: bool,
) -> None:
    rule = TailRadarScreeningRule()

    decision = rule.evaluate(
        TailRadarScreeningInput(
            record=record(pct_change=pct_change),
            snapshot_evidence=snapshot_evidence(),
        )
    )

    assert decision.included is expected
    assert decision.outcome is (
        TailRadarDecisionOutcome.INCLUDED if expected else TailRadarDecisionOutcome.EXCLUDED
    )


def test_v1_requires_snapshot_pct_change_and_positive_price_evidence() -> None:
    rule = TailRadarScreeningRule()

    missing_snapshot = rule.evaluate(
        TailRadarScreeningInput(record=record(pct_change=2.5), snapshot_evidence=None)
    )
    missing_pct = rule.evaluate(
        TailRadarScreeningInput(
            record=record(pct_change=None),
            snapshot_evidence=snapshot_evidence(),
        )
    )
    invalid_price = rule.evaluate(
        TailRadarScreeningInput(
            record=record(pct_change=2.5, price=0),
            snapshot_evidence=snapshot_evidence(),
        )
    )

    assert missing_snapshot.reason is TailRadarDecisionReason.MISSING_SNAPSHOT_EVIDENCE
    assert missing_pct.reason is TailRadarDecisionReason.INVALID_PCT_CHANGE
    assert invalid_price.reason is TailRadarDecisionReason.INVALID_PRICE
    assert {missing_snapshot.outcome, missing_pct.outcome, invalid_price.outcome} == {
        TailRadarDecisionOutcome.INVALID
    }
    with pytest.raises(ValidationError):
        record(symbol="not-a-symbol", pct_change=2.5)


def test_v1_does_not_silently_apply_future_optional_filters() -> None:
    decision = TailRadarScreeningRule().evaluate(
        TailRadarScreeningInput(
            record=record(pct_change=2.5),
            snapshot_evidence=snapshot_evidence(),
        )
    )

    assert decision.included is True
    with pytest.raises(ValidationError, match="optional Tail Radar filters are disabled"):
        TailRadarScreeningConfiguration(exclude_st=True)
    with pytest.raises(ValidationError, match=r"inclusive 2\.00 to 3\.00"):
        TailRadarScreeningConfiguration(pct_change_min=1.5)


def test_persisted_included_decision_must_be_coherent_with_the_rule_range() -> None:
    with pytest.raises(ValidationError, match="valid in-range evidence"):
        TailRadarScreeningDecision(
            outcome=TailRadarDecisionOutcome.INCLUDED,
            reason=TailRadarDecisionReason.PCT_CHANGE_IN_RANGE,
            observed_pct_change=3.01,
            observed_price=10,
        )


def test_candidate_payload_rejects_cross_provider_snapshot_evidence() -> None:
    decision = TailRadarScreeningRule().evaluate(
        TailRadarScreeningInput(
            record=record(pct_change=2.5),
            snapshot_evidence=snapshot_evidence(),
        )
    )
    mismatched_record = record(pct_change=2.5).model_copy(update={"provider": "other"})

    with pytest.raises(ValidationError, match="provider must match"):
        TailRadarCandidatePayload(
            screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
            rule_configuration=TailRadarScreeningConfiguration(),
            snapshot_evidence=snapshot_evidence(),
            snapshot_record=mismatched_record,
            decision=decision,
        )


def source_manifest(*, record_count: int) -> PersistedSnapshotManifest:
    quality = quality_report(record_count)
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
        storage_key=f"market-data/2026-08-28/full-market-{SNAPSHOT_ID}.parquet",
        checksum_sha256="a" * 64,
        row_count=record_count,
        latency_ms=1_000,
        quality_report=quality,
        schema_version=2,
        status=SnapshotManifestStatus.AVAILABLE,
        persisted_at=PERSISTED,
    )


def quality_report(record_count: int) -> SnapshotQualityReport:
    return SnapshotQualityReport(
        passed=True,
        raw_record_count=record_count,
        normalized_record_count=record_count,
        duplicate_symbol_count=0,
        missing_symbol_count=0,
        invalid_price_count=0,
        invalid_pct_change_count=0,
        malformed_row_count=0,
        missing_symbol_ratio=0,
        invalid_price_ratio=0,
        invalid_pct_change_ratio=0,
        malformed_row_ratio=0,
        thresholds=SnapshotQualityThresholds(min_record_count=1),
    )


def market_snapshot(records: tuple[MarketSnapshotRecord, ...]) -> FullMarketSnapshot:
    return FullMarketSnapshot(
        manifest=SnapshotManifest(
            snapshot_id=SNAPSHOT_ID,
            provider="fixture",
            provider_version="fixture-1",
            actual_fetch_started_at=FETCH_STARTED,
            actual_fetch_finished_at=FETCH_FINISHED,
            latency_ms=1_000,
            record_count=len(records),
            schema_version=2,
            provider_metadata={},
            quality_report=quality_report(len(records)),
        ),
        records=records,
    )


class FakeReader:
    def __init__(self, snapshot: FullMarketSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def read(self, manifest: PersistedSnapshotManifest) -> FullMarketSnapshot:
        assert manifest.snapshot_id == SNAPSHOT_ID
        self.calls += 1
        return self.snapshot


class FakeRepository:
    def __init__(self, source: PersistedSnapshotManifest | None) -> None:
        self.source = source
        self.run: TailRadarRunData | None = None
        self.candidates: tuple[TailRadarCandidateCreate, ...] = ()

    def get_official_snapshot(self, snapshot_id: UUID) -> PersistedSnapshotManifest | None:
        return (
            self.source
            if self.source is not None and snapshot_id == self.source.snapshot_id
            else None
        )

    def claim_run(
        self,
        *,
        snapshot: PersistedSnapshotManifest,
        screening_rule_version: str,
        rule_configuration: TailRadarScreeningConfiguration,
        started_at: datetime,
    ) -> TailRadarRunClaim:
        if self.run is not None:
            return TailRadarRunClaim(run=self.run, created=False)
        self.run = TailRadarRunData(
            run_id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            trade_date=snapshot.trade_date,
            intended_snapshot_time=snapshot.intended_snapshot_time,
            actual_started_at=started_at,
            status=RunStatus.RUNNING,
            screening_rule_version=screening_rule_version,
            is_official=True,
            rule_configuration=rule_configuration,
            created_at=started_at,
            updated_at=started_at,
        )
        return TailRadarRunClaim(run=self.run, created=True)

    def complete_run(
        self,
        *,
        run_id: UUID,
        candidates: Sequence[TailRadarCandidateCreate],
        evaluated_record_count: int,
        invalid_record_count: int,
        finished_at: datetime,
    ) -> TailRadarRunData:
        assert self.run is not None and self.run.run_id == run_id
        self.candidates = tuple(candidates)
        self.run = self.run.model_copy(
            update={
                "status": RunStatus.SUCCEEDED,
                "actual_finished_at": finished_at,
                "evaluated_record_count": evaluated_record_count,
                "invalid_record_count": invalid_record_count,
                "candidate_count": len(candidates),
                "updated_at": finished_at,
            }
        )
        return TailRadarRunData.model_validate(self.run)

    def fail_run(
        self,
        *,
        run_id: UUID,
        finished_at: datetime,
        error_code: str,
    ) -> TailRadarRunData:
        assert self.run is not None and self.run.run_id == run_id
        self.run = self.run.model_copy(
            update={
                "status": RunStatus.FAILED,
                "actual_finished_at": finished_at,
                "error_code": error_code,
                "updated_at": finished_at,
            }
        )
        return TailRadarRunData.model_validate(self.run)

    def get_latest_run(self) -> TailRadarRunData | None:
        return self.run

    def list_runs(self, *, offset: int, limit: int) -> TailRadarRunPage:
        items = () if self.run is None else (self.run,)
        return TailRadarRunPage(items=items, total=len(items), offset=offset, limit=limit)

    def get_run(self, run_id: UUID) -> TailRadarRunData | None:
        return self.run if self.run is not None and self.run.run_id == run_id else None

    def list_candidates(self, *, run_id: UUID, offset: int, limit: int) -> TailRadarCandidatePage:
        return TailRadarCandidatePage(items=(), total=0, offset=offset, limit=limit)

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None:
        return None


def test_service_screens_one_snapshot_persists_evidence_and_is_idempotent() -> None:
    records = tuple(
        record(symbol=f"60000{index}", pct_change=pct, price=price)
        for index, (pct, price) in enumerate(
            ((1.99, 10), (2.0, 10), (2.5, 11), (3.0, 12), (3.01, 10), (2.5, 0))
        )
    )
    source = source_manifest(record_count=len(records))
    reader = FakeReader(market_snapshot(records))
    repository = FakeRepository(source)
    service = TailRadarScreeningService(
        rule=TailRadarScreeningRule(),
        reader=reader,
        repository=cast(TailRadarRepository, repository),
        clock=iter(
            (SCREEN_STARTED, SCREEN_FINISHED, SCREEN_FINISHED + timedelta(seconds=1))
        ).__next__,
    )

    first = service.execute(snapshot_id=SNAPSHOT_ID)
    second = service.execute(snapshot_id=SNAPSHOT_ID)

    assert first.disposition is TailRadarExecutionDisposition.CREATED
    assert second.disposition is TailRadarExecutionDisposition.IDEMPOTENT_REPLAY
    assert second.run.run_id == first.run.run_id
    assert first.run.evaluated_record_count == 6
    assert first.run.invalid_record_count == 1
    assert first.run.candidate_count == 3
    assert reader.calls == 1
    assert [candidate.symbol for candidate in repository.candidates] == [
        "600001",
        "600002",
        "600003",
    ]
    assert all(
        candidate.payload.screening_rule_version == TAIL_RADAR_SCREENING_RULE_VERSION
        and candidate.payload.snapshot_evidence.snapshot_id == SNAPSHOT_ID
        and candidate.payload.snapshot_record.symbol == candidate.symbol
        and candidate.as_of == FETCH_FINISHED
        for candidate in repository.candidates
    )


def test_service_rejects_non_official_or_missing_snapshot_before_claim() -> None:
    repository = FakeRepository(None)
    service = TailRadarScreeningService(
        rule=TailRadarScreeningRule(),
        reader=FakeReader(market_snapshot((record(pct_change=2.5),))),
        repository=cast(TailRadarRepository, repository),
    )

    with pytest.raises(TailRadarSourceSnapshotNotFoundError):
        service.execute(snapshot_id=SNAPSHOT_ID)

    assert repository.run is None


def test_service_records_artifact_manifest_mismatch_as_failed() -> None:
    source = source_manifest(record_count=1)
    mismatched = market_snapshot((record(pct_change=2.5),)).model_copy(
        update={
            "manifest": market_snapshot((record(pct_change=2.5),)).manifest.model_copy(
                update={"provider": "different-provider"}
            )
        }
    )
    repository = FakeRepository(source)
    service = TailRadarScreeningService(
        rule=TailRadarScreeningRule(),
        reader=FakeReader(mismatched),
        repository=cast(TailRadarRepository, repository),
        clock=iter((SCREEN_STARTED, SCREEN_FINISHED)).__next__,
    )

    with pytest.raises(TailRadarSnapshotIntegrityError):
        service.execute(snapshot_id=SNAPSHOT_ID)

    assert repository.run is not None
    assert repository.run.status is RunStatus.FAILED
    assert repository.run.error_code == "TailRadarSnapshotIntegrityError"


def test_service_does_not_overwrite_an_uncertain_candidate_commit_with_failure() -> None:
    class UncertainRepository(FakeRepository):
        def __init__(self, source: PersistedSnapshotManifest) -> None:
            super().__init__(source)
            self.fail_calls = 0

        def complete_run(
            self,
            *,
            run_id: UUID,
            candidates: Sequence[TailRadarCandidateCreate],
            evaluated_record_count: int,
            invalid_record_count: int,
            finished_at: datetime,
        ) -> TailRadarRunData:
            raise TailRadarCommitUncertainError("simulated uncertain commit")

        def fail_run(
            self,
            *,
            run_id: UUID,
            finished_at: datetime,
            error_code: str,
        ) -> TailRadarRunData:
            self.fail_calls += 1
            return super().fail_run(
                run_id=run_id,
                finished_at=finished_at,
                error_code=error_code,
            )

    source = source_manifest(record_count=1)
    repository = UncertainRepository(source)
    service = TailRadarScreeningService(
        rule=TailRadarScreeningRule(),
        reader=FakeReader(market_snapshot((record(pct_change=2.5),))),
        repository=cast(TailRadarRepository, repository),
        clock=iter((SCREEN_STARTED, SCREEN_FINISHED)).__next__,
    )

    with pytest.raises(TailRadarCommitUncertainError):
        service.execute(snapshot_id=SNAPSHOT_ID)

    assert repository.fail_calls == 0
    assert repository.run is not None
    assert repository.run.status is RunStatus.RUNNING
