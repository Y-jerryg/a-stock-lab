from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.execution.schemas import ExecutionRunData
from a_stock_lab.shared.market_data.errors import (
    FutureIntendedSnapshotError,
    HistoricalLiveSnapshotError,
    MarketDataQualityError,
    NonTradingDayError,
    ProviderUnavailableError,
    SnapshotExecutionPersistenceError,
    SnapshotManifestCommitUncertainError,
    SnapshotPersistenceError,
)
from a_stock_lab.shared.market_data.execution_models import (
    SnapshotExecutionDisposition,
    SnapshotManifestCreate,
    SnapshotRunClaim,
    SnapshotRunKey,
)
from a_stock_lab.shared.market_data.execution_service import FullMarketSnapshotExecutionEngine
from a_stock_lab.shared.market_data.models import (
    FullMarketSnapshot,
    IntradayBarRequest,
    MarketDataCapability,
    MarketSnapshotRecord,
    ProviderIntradayBarBatch,
    ProviderSnapshotBatch,
    SnapshotQualityThresholds,
)
from a_stock_lab.shared.market_data.persistence_schemas import (
    PersistedSnapshotManifest,
    SnapshotStorageResult,
)
from a_stock_lab.shared.market_data.service import FullMarketSnapshotService
from a_stock_lab.shared.market_data.trading_calendar import TradingDay

INTENDED_UTC = datetime(2026, 8, 28, 6, 30, tzinfo=UTC)
FETCH_STARTED_UTC = datetime(2026, 8, 28, 6, 31, tzinfo=UTC)
FETCH_FINISHED_UTC = datetime(2026, 8, 28, 6, 31, 2, tzinfo=UTC)
PERSISTED_SHANGHAI = datetime(2026, 8, 28, 14, 31, 3, tzinfo=MARKET_TIME_ZONE)


class FakeProvider:
    provider_id = "fake"
    capabilities = frozenset({MarketDataCapability.FULL_MARKET_SNAPSHOT})

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = 0

    def fetch_full_market_snapshot(self) -> ProviderSnapshotBatch:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return ProviderSnapshotBatch(
            provider=self.provider_id,
            provider_version="fake-1",
            raw_record_count=1,
            records=(
                MarketSnapshotRecord(
                    symbol="600000",
                    name="Test",
                    price=10,
                    provider=self.provider_id,
                    fetched_at=FETCH_FINISHED_UTC,
                ),
            ),
            provider_metadata={"source": "fixture"},
        )

    def fetch_intraday_bars(self, request: IntradayBarRequest) -> ProviderIntradayBarBatch:
        raise AssertionError(f"unexpected intraday request: {request}")


class FakeCalendar:
    provider_id = "calendar-fixture"

    def __init__(self, *, is_trading_day: bool = True) -> None:
        self.is_trading_day = is_trading_day
        self.calls = 0

    def resolve(self, trade_date: date) -> TradingDay:
        self.calls += 1
        return TradingDay(
            trade_date=trade_date,
            is_trading_day=self.is_trading_day,
            provider=self.provider_id,
            provider_metadata={"fixture": True},
        )


class FakeStorage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.writes = 0
        self.deleted: list[str] = []

    def write(self, snapshot: FullMarketSnapshot) -> SnapshotStorageResult:
        self.writes += 1
        if self.fail:
            raise SnapshotPersistenceError(target=Path("snapshot.parquet"))
        snapshot_id = snapshot.manifest.snapshot_id
        return SnapshotStorageResult(
            storage_key=f"market-data/2026-08-28/full-market-{snapshot_id}.parquet",
            checksum_sha256="a" * 64,
            size_bytes=123,
        )

    def delete(self, storage_key: str) -> None:
        self.deleted.append(storage_key)


class FakeRepository:
    def __init__(self) -> None:
        self.runs: dict[UUID, ExecutionRunData] = {}
        self.official: dict[tuple[object, ...], UUID] = {}
        self.manifests: dict[UUID, PersistedSnapshotManifest] = {}

    def claim_run(
        self,
        *,
        key: SnapshotRunKey,
        provider: str,
        started_at: datetime,
        force: bool,
    ) -> SnapshotRunClaim:
        logical_key = (
            key.job_type,
            key.trade_date,
            key.intended_snapshot_time,
            key.execution_version,
        )
        official_id = self.official.get(logical_key)
        if not force and official_id is not None:
            return SnapshotRunClaim(run=self.runs[official_id], created=False)
        run_id = uuid4()
        now = started_at
        run = ExecutionRunData(
            run_id=run_id,
            job_type=key.job_type,
            trade_date=key.trade_date,
            intended_execution_time=key.intended_snapshot_time,
            actual_started_at=started_at,
            status=RunStatus.RUNNING,
            provider=provider,
            implementation_version=key.execution_version,
            is_official=not force,
            rerun_of_run_id=official_id if force else None,
            run_metadata={},
            created_at=now,
            updated_at=now,
        )
        self.runs[run_id] = run
        if not force:
            self.official[logical_key] = run_id
        return SnapshotRunClaim(run=run, created=True)

    def complete_run(
        self,
        *,
        manifest: SnapshotManifestCreate,
        run_metadata: dict[str, object],
        finished_at: datetime,
    ) -> tuple[ExecutionRunData, PersistedSnapshotManifest]:
        run = self.runs[manifest.run_id].model_copy(
            update={
                "status": RunStatus.SUCCEEDED,
                "actual_finished_at": finished_at,
                "run_metadata": run_metadata,
                "updated_at": finished_at,
            }
        )
        persisted = PersistedSnapshotManifest.model_validate(manifest.model_dump(mode="python"))
        self.runs[run.run_id] = run
        self.manifests[persisted.snapshot_id] = persisted
        return run, persisted

    def fail_run(
        self,
        *,
        run_id: UUID,
        finished_at: datetime,
        error_code: str,
        error_message: str,
        error_details: dict[str, object] | None,
    ) -> ExecutionRunData:
        run = self.runs[run_id].model_copy(
            update={
                "status": RunStatus.FAILED,
                "actual_finished_at": finished_at,
                "error_code": error_code,
                "error_message": error_message,
                "error_details": error_details,
                "updated_at": finished_at,
            }
        )
        self.runs[run_id] = run
        return run

    def get_run(self, run_id: UUID) -> ExecutionRunData | None:
        return self.runs.get(run_id)

    def get_manifest(self, snapshot_id: UUID) -> PersistedSnapshotManifest | None:
        return self.manifests.get(snapshot_id)

    def get_manifest_for_run(self, run_id: UUID) -> PersistedSnapshotManifest | None:
        return next(
            (manifest for manifest in self.manifests.values() if manifest.run_id == run_id),
            None,
        )


def build_engine(
    *,
    provider: FakeProvider | None = None,
    calendar: FakeCalendar | None = None,
    storage: FakeStorage | None = None,
    repository: FakeRepository | None = None,
    minimum_records: int = 1,
) -> tuple[
    FullMarketSnapshotExecutionEngine,
    FakeProvider,
    FakeCalendar,
    FakeStorage,
    FakeRepository,
]:
    provider = provider or FakeProvider()
    calendar = calendar or FakeCalendar()
    storage = storage or FakeStorage()
    repository = repository or FakeRepository()
    service = FullMarketSnapshotService(
        provider=provider,
        thresholds=SnapshotQualityThresholds(min_record_count=minimum_records),
        clock=iter((FETCH_STARTED_UTC, FETCH_FINISHED_UTC) * 10).__next__,
        timer=iter((10.0, 10.25) * 10).__next__,
    )
    engine_clock = iter(
        (
            datetime(2026, 8, 28, 14, 31, tzinfo=MARKET_TIME_ZONE),
            PERSISTED_SHANGHAI,
        )
        * 10
    ).__next__
    return (
        FullMarketSnapshotExecutionEngine(
            snapshot_service=service,
            trading_calendar=calendar,
            storage=storage,
            repository=repository,
            clock=engine_clock,
        ),
        provider,
        calendar,
        storage,
        repository,
    )


def test_execution_preserves_all_point_in_time_timestamps_in_asia_shanghai() -> None:
    engine, _, _, _, _ = build_engine()

    result = engine.execute(intended_snapshot_time=INTENDED_UTC)

    assert result.manifest is not None
    assert result.manifest.intended_snapshot_time.isoformat() == "2026-08-28T14:30:00+08:00"
    assert result.manifest.actual_fetch_started_at.isoformat() == "2026-08-28T14:31:00+08:00"
    assert result.manifest.actual_fetch_finished_at.isoformat() == ("2026-08-28T14:31:02+08:00")
    assert result.manifest.provider_timestamp is None
    assert result.manifest.persisted_at == PERSISTED_SHANGHAI


def test_official_execution_is_idempotent_without_repeating_external_calls() -> None:
    engine, provider, calendar, storage, _ = build_engine()

    first = engine.execute(intended_snapshot_time=INTENDED_UTC)
    second = engine.execute(intended_snapshot_time=INTENDED_UTC)

    assert first.disposition is SnapshotExecutionDisposition.CREATED
    assert second.disposition is SnapshotExecutionDisposition.IDEMPOTENT_REPLAY
    assert second.run.run_id == first.run.run_id
    assert second.manifest == first.manifest
    assert provider.calls == 1
    assert calendar.calls == 1
    assert storage.writes == 1


def test_succeeded_duplicate_with_missing_manifest_is_reported_as_corruption() -> None:
    engine, provider, calendar, storage, repository = build_engine()
    first = engine.execute(intended_snapshot_time=INTENDED_UTC)
    assert first.manifest is not None
    repository.manifests.clear()

    with pytest.raises(
        SnapshotExecutionPersistenceError,
        match="succeeded snapshot run has no persisted manifest",
    ):
        engine.execute(intended_snapshot_time=INTENDED_UTC)

    assert provider.calls == calendar.calls == storage.writes == 1


def test_force_creates_a_linked_non_official_rerun() -> None:
    engine, provider, _, storage, _ = build_engine()

    official = engine.execute(intended_snapshot_time=INTENDED_UTC)
    forced = engine.execute(intended_snapshot_time=INTENDED_UTC, force=True)

    assert forced.disposition is SnapshotExecutionDisposition.FORCED_RERUN
    assert forced.run.run_id != official.run.run_id
    assert forced.run.is_official is False
    assert forced.run.rerun_of_run_id == official.run.run_id
    assert provider.calls == 2
    assert storage.writes == 2


def test_provider_failure_is_recorded_without_creating_an_artifact() -> None:
    provider = FakeProvider(
        failure=ProviderUnavailableError(provider="fake", message="provider unavailable")
    )
    engine, _, _, storage, repository = build_engine(provider=provider)

    with pytest.raises(ProviderUnavailableError):
        engine.execute(intended_snapshot_time=INTENDED_UTC)

    run = next(iter(repository.runs.values()))
    assert run.status is RunStatus.FAILED
    assert run.error_code == "ProviderUnavailableError"
    assert storage.writes == 0
    assert repository.manifests == {}


def test_quality_failure_is_recorded_and_never_persisted() -> None:
    engine, _, _, storage, repository = build_engine(minimum_records=2)

    with pytest.raises(MarketDataQualityError):
        engine.execute(intended_snapshot_time=INTENDED_UTC)

    run = next(iter(repository.runs.values()))
    assert run.status is RunStatus.FAILED
    assert run.error_details is not None
    assert "quality_report" in run.error_details
    assert storage.writes == 0


def test_non_trading_day_uses_calendar_and_never_calls_market_provider() -> None:
    calendar = FakeCalendar(is_trading_day=False)
    engine, provider, _, _, repository = build_engine(calendar=calendar)

    with pytest.raises(NonTradingDayError):
        engine.execute(intended_snapshot_time=INTENDED_UTC)

    assert provider.calls == 0
    assert next(iter(repository.runs.values())).status is RunStatus.FAILED


def test_storage_failure_is_recorded_without_a_manifest() -> None:
    storage = FakeStorage(fail=True)
    engine, _, _, _, repository = build_engine(storage=storage)

    with pytest.raises(SnapshotPersistenceError):
        engine.execute(intended_snapshot_time=INTENDED_UTC)

    assert next(iter(repository.runs.values())).status is RunStatus.FAILED
    assert repository.manifests == {}


def test_uncertain_database_commit_never_deletes_a_possibly_referenced_artifact() -> None:
    class FailingCompleteRepository(FakeRepository):
        def complete_run(
            self,
            *,
            manifest: SnapshotManifestCreate,
            run_metadata: dict[str, object],
            finished_at: datetime,
        ) -> tuple[ExecutionRunData, PersistedSnapshotManifest]:
            raise SnapshotManifestCommitUncertainError("simulated uncertain database commit")

    repository = FailingCompleteRepository()
    engine, _, _, storage, _ = build_engine(repository=repository)

    with pytest.raises(SnapshotExecutionPersistenceError):
        engine.execute(intended_snapshot_time=INTENDED_UTC)

    assert storage.writes == 1
    assert storage.deleted == []
    assert next(iter(repository.runs.values())).status is RunStatus.FAILED


def test_definite_database_registration_failure_removes_the_unregistered_artifact() -> None:
    class RejectingCompleteRepository(FakeRepository):
        def complete_run(
            self,
            *,
            manifest: SnapshotManifestCreate,
            run_metadata: dict[str, object],
            finished_at: datetime,
        ) -> tuple[ExecutionRunData, PersistedSnapshotManifest]:
            raise SnapshotExecutionPersistenceError("simulated pre-commit rejection")

    repository = RejectingCompleteRepository()
    engine, _, _, storage, _ = build_engine(repository=repository)

    with pytest.raises(SnapshotExecutionPersistenceError, match="pre-commit rejection"):
        engine.execute(intended_snapshot_time=INTENDED_UTC)

    assert storage.writes == 1
    assert len(storage.deleted) == 1
    assert next(iter(repository.runs.values())).status is RunStatus.FAILED


def test_future_intended_timestamp_is_rejected_before_claiming_a_run() -> None:
    engine, provider, calendar, storage, repository = build_engine()

    with pytest.raises(FutureIntendedSnapshotError):
        engine.execute(intended_snapshot_time=INTENDED_UTC + timedelta(days=1))

    assert repository.runs == {}
    assert provider.calls == calendar.calls == storage.writes == 0


def test_live_provider_cannot_backfill_an_earlier_intended_trade_date() -> None:
    engine, provider, calendar, storage, repository = build_engine()

    with pytest.raises(HistoricalLiveSnapshotError):
        engine.execute(intended_snapshot_time=INTENDED_UTC - timedelta(days=1))

    assert repository.runs == {}
    assert provider.calls == calendar.calls == storage.writes == 0
