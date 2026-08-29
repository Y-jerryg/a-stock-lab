from collections.abc import Callable
from datetime import datetime

from a_stock_lab.core.time import as_market_timezone, now_in_market_timezone
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.contracts import MarketSnapshotStorage, TradingCalendar
from a_stock_lab.shared.market_data.errors import (
    FutureIntendedSnapshotError,
    HistoricalLiveSnapshotError,
    MarketDataQualityError,
    NonTradingDayError,
    SnapshotArtifactCleanupError,
    SnapshotExecutionPersistenceError,
    SnapshotManifestCommitUncertainError,
    SnapshotPersistenceError,
    TradingCalendarError,
)
from a_stock_lab.shared.market_data.execution_contracts import SnapshotExecutionRepository
from a_stock_lab.shared.market_data.execution_models import (
    FULL_MARKET_SNAPSHOT_JOB_TYPE,
    SNAPSHOT_EXECUTION_VERSION,
    SnapshotExecutionDisposition,
    SnapshotExecutionResult,
    SnapshotManifestCreate,
    SnapshotRunKey,
)
from a_stock_lab.shared.market_data.persistence_schemas import SnapshotStorageResult
from a_stock_lab.shared.market_data.service import FullMarketSnapshotService


class FullMarketSnapshotExecutionEngine:
    """Execute an auditable point-in-time snapshot and register its immutable artifact."""

    def __init__(
        self,
        *,
        snapshot_service: FullMarketSnapshotService,
        trading_calendar: TradingCalendar,
        storage: MarketSnapshotStorage,
        repository: SnapshotExecutionRepository,
        execution_version: str = SNAPSHOT_EXECUTION_VERSION,
        clock: Callable[[], datetime] = now_in_market_timezone,
    ) -> None:
        self._snapshot_service = snapshot_service
        self._trading_calendar = trading_calendar
        self._storage = storage
        self._repository = repository
        self._execution_version = execution_version
        self._clock = clock

    def execute(
        self,
        *,
        intended_snapshot_time: datetime,
        force: bool = False,
    ) -> SnapshotExecutionResult:
        intended = as_market_timezone(intended_snapshot_time)
        execution_started_at = as_market_timezone(self._clock())
        if intended > execution_started_at:
            raise FutureIntendedSnapshotError(
                "intended snapshot time cannot be later than execution start"
            )
        if intended.date() != execution_started_at.date():
            raise HistoricalLiveSnapshotError(
                "live full-market snapshots require the intended and execution trade dates to match"
            )
        key = SnapshotRunKey(
            job_type=FULL_MARKET_SNAPSHOT_JOB_TYPE,
            trade_date=intended.date(),
            intended_snapshot_time=intended,
            execution_version=self._execution_version,
        )
        claim = self._repository.claim_run(
            key=key,
            provider=self._snapshot_service.provider_id,
            started_at=execution_started_at,
            force=force,
        )
        if not claim.created:
            existing_manifest = self._repository.get_manifest_for_run(claim.run.run_id)
            if claim.run.status is RunStatus.SUCCEEDED and existing_manifest is None:
                raise SnapshotExecutionPersistenceError(
                    "succeeded snapshot run has no persisted manifest"
                )
            return SnapshotExecutionResult(
                disposition=SnapshotExecutionDisposition.IDEMPOTENT_REPLAY,
                run=claim.run,
                manifest=existing_manifest,
            )

        artifact: SnapshotStorageResult | None = None
        try:
            trading_day = self._trading_calendar.resolve(key.trade_date)
            if not trading_day.is_trading_day:
                raise NonTradingDayError(key.trade_date)

            snapshot = self._snapshot_service.fetch()
            artifact = self._storage.write(snapshot)
            persisted_at = as_market_timezone(self._clock())
            manifest = SnapshotManifestCreate(
                snapshot_id=snapshot.manifest.snapshot_id,
                run_id=claim.run.run_id,
                trade_date=key.trade_date,
                intended_snapshot_time=key.intended_snapshot_time,
                actual_fetch_started_at=snapshot.manifest.actual_fetch_started_at,
                actual_fetch_finished_at=snapshot.manifest.actual_fetch_finished_at,
                provider=snapshot.manifest.provider,
                provider_version=snapshot.manifest.provider_version,
                provider_timestamp=snapshot.manifest.provider_timestamp,
                provider_metadata=snapshot.manifest.provider_metadata,
                storage_key=artifact.storage_key,
                checksum_sha256=artifact.checksum_sha256,
                row_count=snapshot.manifest.record_count,
                latency_ms=snapshot.manifest.latency_ms,
                quality_report=snapshot.manifest.quality_report,
                schema_version=snapshot.manifest.schema_version,
                persisted_at=persisted_at,
            )
            run, persisted_manifest = self._repository.complete_run(
                manifest=manifest,
                run_metadata={
                    "trading_calendar": trading_day.model_dump(mode="json"),
                },
                finished_at=persisted_at,
            )
            return SnapshotExecutionResult(
                disposition=(
                    SnapshotExecutionDisposition.FORCED_RERUN
                    if force
                    else SnapshotExecutionDisposition.CREATED
                ),
                run=run,
                manifest=persisted_manifest,
            )
        except Exception as exc:
            failure = exc
            if artifact is not None and not isinstance(exc, SnapshotManifestCommitUncertainError):
                try:
                    self._storage.delete(artifact.storage_key)
                except SnapshotPersistenceError:
                    failure = SnapshotArtifactCleanupError(
                        "snapshot execution failed and its unregistered artifact "
                        "could not be removed"
                    )
            try:
                self._repository.fail_run(
                    run_id=claim.run.run_id,
                    finished_at=as_market_timezone(self._clock()),
                    error_code=type(failure).__name__,
                    error_message=str(failure),
                    error_details=_safe_error_details(
                        failure,
                        original_error=exc if failure is not exc else None,
                    ),
                )
            except SnapshotExecutionPersistenceError as recording_error:
                raise recording_error from failure
            if failure is exc:
                raise
            raise failure from exc


def _safe_error_details(
    error: Exception,
    *,
    original_error: Exception | None = None,
) -> dict[str, object]:
    details: dict[str, object] = {"error_type": type(error).__name__}
    if original_error is not None:
        details["original_error_type"] = type(original_error).__name__
    provider = getattr(error, "provider", None)
    if isinstance(provider, str):
        details["provider"] = provider
    if isinstance(error, NonTradingDayError):
        details["trade_date"] = error.trade_date.isoformat()
    if isinstance(error, MarketDataQualityError):
        details["quality_report"] = error.report.model_dump(mode="json")
    if isinstance(error, (TradingCalendarError, SnapshotPersistenceError)):
        details["stage"] = (
            "trading_calendar" if isinstance(error, TradingCalendarError) else "snapshot_storage"
        )
    elif isinstance(error, SnapshotArtifactCleanupError):
        details["stage"] = "artifact_cleanup"
    elif isinstance(error, SnapshotManifestCommitUncertainError):
        details["stage"] = "manifest_commit"
    elif isinstance(error, SnapshotExecutionPersistenceError):
        details["stage"] = "database"
    return details
