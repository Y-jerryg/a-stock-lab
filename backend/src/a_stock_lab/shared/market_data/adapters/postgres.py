from datetime import datetime
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from a_stock_lab.shared.execution.models import ExecutionRun, RunStatus
from a_stock_lab.shared.execution.schemas import ExecutionRunData
from a_stock_lab.shared.market_data.errors import (
    SnapshotExecutionPersistenceError,
    SnapshotManifestCommitUncertainError,
)
from a_stock_lab.shared.market_data.execution_models import (
    SnapshotManifestCreate,
    SnapshotRunClaim,
    SnapshotRunKey,
)
from a_stock_lab.shared.market_data.persistence_models import MarketSnapshotManifestRecord
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest


class PostgresSnapshotExecutionRepository:
    """PostgreSQL adapter for run claims and immutable snapshot manifests."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def claim_run(
        self,
        *,
        key: SnapshotRunKey,
        provider: str,
        started_at: datetime,
        force: bool,
    ) -> SnapshotRunClaim:
        with self._session_factory() as session:
            try:
                official = self._find_official(session, key)
            except SQLAlchemyError as exc:
                raise SnapshotExecutionPersistenceError(
                    "official snapshot run could not be checked"
                ) from exc
            if not force and official is not None:
                return SnapshotRunClaim(run=self._run_data(official), created=False)

            run = ExecutionRun(
                job_type=key.job_type,
                trade_date=key.trade_date,
                intended_execution_time=key.intended_snapshot_time,
                actual_started_at=started_at,
                status=RunStatus.RUNNING,
                provider=provider,
                implementation_version=key.execution_version,
                is_official=not force,
                rerun_of_run_id=official.run_id if force and official is not None else None,
                run_metadata={},
            )
            session.add(run)
            try:
                session.flush()
                run_data = self._run_data(run)
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if force:
                    raise SnapshotExecutionPersistenceError(
                        "forced snapshot run could not be claimed"
                    ) from exc
                try:
                    existing = self._find_official(session, key)
                except SQLAlchemyError as lookup_error:
                    raise SnapshotExecutionPersistenceError(
                        "conflicting official snapshot run could not be read"
                    ) from lookup_error
                if existing is None:
                    raise SnapshotExecutionPersistenceError(
                        "official snapshot run could not be claimed"
                    ) from exc
                return SnapshotRunClaim(
                    run=self._run_data(existing),
                    created=False,
                )
            except SQLAlchemyError as exc:
                session.rollback()
                raise SnapshotExecutionPersistenceError(
                    "snapshot run could not be claimed"
                ) from exc
            return SnapshotRunClaim(run=run_data, created=True)

    def complete_run(
        self,
        *,
        manifest: SnapshotManifestCreate,
        run_metadata: dict[str, object],
        finished_at: datetime,
    ) -> tuple[ExecutionRunData, PersistedSnapshotManifest]:
        with self._session_factory() as session:
            try:
                run = session.scalar(
                    select(ExecutionRun)
                    .where(ExecutionRun.run_id == manifest.run_id)
                    .with_for_update()
                )
                if run is None or run.status is not RunStatus.RUNNING:
                    raise SnapshotExecutionPersistenceError(
                        "snapshot run is not available for completion"
                    )
                if (
                    run.trade_date != manifest.trade_date
                    or run.intended_execution_time != manifest.intended_snapshot_time
                    or run.provider != manifest.provider
                ):
                    raise SnapshotExecutionPersistenceError(
                        "snapshot manifest does not match its claimed run"
                    )
                if finished_at < manifest.persisted_at:
                    raise SnapshotExecutionPersistenceError(
                        "snapshot run finish cannot precede artifact persistence"
                    )
                record = MarketSnapshotManifestRecord(
                    snapshot_id=manifest.snapshot_id,
                    run_id=manifest.run_id,
                    trade_date=manifest.trade_date,
                    intended_snapshot_time=manifest.intended_snapshot_time,
                    actual_fetch_started_at=manifest.actual_fetch_started_at,
                    actual_fetch_finished_at=manifest.actual_fetch_finished_at,
                    provider=manifest.provider,
                    provider_version=manifest.provider_version,
                    provider_timestamp=manifest.provider_timestamp,
                    provider_metadata=manifest.provider_metadata,
                    storage_key=manifest.storage_key,
                    checksum_sha256=manifest.checksum_sha256,
                    row_count=manifest.row_count,
                    latency_ms=manifest.latency_ms,
                    quality_report=manifest.quality_report.model_dump(mode="json"),
                    schema_version=manifest.schema_version,
                    status=manifest.status,
                    persisted_at=manifest.persisted_at,
                )
                session.add(record)
                run.status = RunStatus.SUCCEEDED
                run.actual_finished_at = finished_at
                run.run_metadata = cast(dict[str, object], dict(run_metadata))
                run.error_code = None
                run.error_message = None
                run.error_details = None
                session.flush()
                run_data = self._run_data(run)
                manifest_data = self._manifest_data(record)
            except SnapshotExecutionPersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise SnapshotExecutionPersistenceError(
                    "snapshot manifest could not be prepared for commit"
                ) from exc
            try:
                session.commit()
            except SQLAlchemyError as exc:
                raise SnapshotManifestCommitUncertainError(
                    "snapshot manifest commit outcome is uncertain"
                ) from exc
            return run_data, manifest_data

    def fail_run(
        self,
        *,
        run_id: UUID,
        finished_at: datetime,
        error_code: str,
        error_message: str,
        error_details: dict[str, object] | None,
    ) -> ExecutionRunData:
        with self._session_factory() as session:
            try:
                run = session.scalar(
                    select(ExecutionRun).where(ExecutionRun.run_id == run_id).with_for_update()
                )
                if run is None or run.status is not RunStatus.RUNNING:
                    raise SnapshotExecutionPersistenceError(
                        "snapshot run is not available for failure recording"
                    )
                run.status = RunStatus.FAILED
                run.actual_finished_at = finished_at
                run.error_code = error_code[:128]
                run.error_message = error_message
                run.error_details = error_details
                session.flush()
                run_data = self._run_data(run)
                session.commit()
            except SnapshotExecutionPersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise SnapshotExecutionPersistenceError(
                    "snapshot run failure could not be recorded"
                ) from exc
            return run_data

    def get_run(self, run_id: UUID) -> ExecutionRunData | None:
        with self._session_factory() as session:
            try:
                run = session.get(ExecutionRun, run_id)
                return None if run is None else self._run_data(run)
            except SQLAlchemyError as exc:
                raise SnapshotExecutionPersistenceError("snapshot run could not be read") from exc

    def get_manifest(self, snapshot_id: UUID) -> PersistedSnapshotManifest | None:
        with self._session_factory() as session:
            try:
                record = session.get(MarketSnapshotManifestRecord, snapshot_id)
                return None if record is None else self._manifest_data(record)
            except SQLAlchemyError as exc:
                raise SnapshotExecutionPersistenceError(
                    "snapshot manifest could not be read"
                ) from exc

    def get_manifest_for_run(self, run_id: UUID) -> PersistedSnapshotManifest | None:
        with self._session_factory() as session:
            try:
                record = session.scalar(
                    select(MarketSnapshotManifestRecord).where(
                        MarketSnapshotManifestRecord.run_id == run_id
                    )
                )
                return None if record is None else self._manifest_data(record)
            except SQLAlchemyError as exc:
                raise SnapshotExecutionPersistenceError(
                    "snapshot manifest could not be read"
                ) from exc

    @staticmethod
    def _find_official(session: Session, key: SnapshotRunKey) -> ExecutionRun | None:
        return session.scalar(
            select(ExecutionRun).where(
                ExecutionRun.job_type == key.job_type,
                ExecutionRun.trade_date == key.trade_date,
                ExecutionRun.intended_execution_time == key.intended_snapshot_time,
                ExecutionRun.implementation_version == key.execution_version,
                ExecutionRun.is_official.is_(True),
            )
        )

    @staticmethod
    def _run_data(run: ExecutionRun) -> ExecutionRunData:
        try:
            return ExecutionRunData.model_validate(run)
        except ValidationError as exc:
            raise SnapshotExecutionPersistenceError("stored snapshot run is invalid") from exc

    @staticmethod
    def _manifest_data(record: MarketSnapshotManifestRecord) -> PersistedSnapshotManifest:
        try:
            return PersistedSnapshotManifest.model_validate(record)
        except ValidationError as exc:
            raise SnapshotExecutionPersistenceError("stored snapshot manifest is invalid") from exc
