from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import Select

from a_stock_lab.features.tail_radar.adapters.persistence_models import (
    TailRadarCandidateRecord,
    TailRadarRunRecord,
)
from a_stock_lab.features.tail_radar.application.models import (
    TAIL_RADAR_CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    TAIL_RADAR_CANDIDATE_ARTIFACT_TYPE,
    TAIL_RADAR_JOB_TYPE,
    TailRadarCandidateCreate,
    TailRadarCandidateData,
    TailRadarCandidatePage,
    TailRadarCandidatePayload,
    TailRadarRunClaim,
    TailRadarRunData,
    TailRadarRunPage,
    tail_radar_execution_version,
)
from a_stock_lab.features.tail_radar.domain.errors import (
    TailRadarCommitUncertainError,
    TailRadarPersistenceError,
)
from a_stock_lab.features.tail_radar.domain.screening import TailRadarScreeningConfiguration
from a_stock_lab.shared.artifacts.models import ResearchArtifact
from a_stock_lab.shared.execution.models import ExecutionRun, RunStatus
from a_stock_lab.shared.market_data.execution_models import FULL_MARKET_SNAPSHOT_JOB_TYPE
from a_stock_lab.shared.market_data.models import SnapshotManifestStatus
from a_stock_lab.shared.market_data.persistence_models import MarketSnapshotManifestRecord
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest


class PostgresTailRadarRepository:
    """PostgreSQL adapter for Tail Radar execution, candidates, and public reads."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_official_snapshot(self, snapshot_id: UUID) -> PersistedSnapshotManifest | None:
        with self._session_factory() as session:
            try:
                record = session.scalar(
                    select(MarketSnapshotManifestRecord)
                    .join(ExecutionRun, ExecutionRun.run_id == MarketSnapshotManifestRecord.run_id)
                    .where(
                        MarketSnapshotManifestRecord.snapshot_id == snapshot_id,
                        MarketSnapshotManifestRecord.status == SnapshotManifestStatus.AVAILABLE,
                        ExecutionRun.status == RunStatus.SUCCEEDED,
                        ExecutionRun.is_official.is_(True),
                        ExecutionRun.job_type == FULL_MARKET_SNAPSHOT_JOB_TYPE,
                    )
                )
                return None if record is None else self._manifest_data(record)
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError(
                    "official market snapshot could not be read"
                ) from exc

    def claim_run(
        self,
        *,
        snapshot: PersistedSnapshotManifest,
        screening_rule_version: str,
        rule_configuration: TailRadarScreeningConfiguration,
        started_at: datetime,
    ) -> TailRadarRunClaim:
        with self._session_factory() as session:
            try:
                registered = session.scalar(
                    select(MarketSnapshotManifestRecord)
                    .join(ExecutionRun, ExecutionRun.run_id == MarketSnapshotManifestRecord.run_id)
                    .where(
                        MarketSnapshotManifestRecord.snapshot_id == snapshot.snapshot_id,
                        MarketSnapshotManifestRecord.status == SnapshotManifestStatus.AVAILABLE,
                        ExecutionRun.status == RunStatus.SUCCEEDED,
                        ExecutionRun.is_official.is_(True),
                        ExecutionRun.job_type == FULL_MARKET_SNAPSHOT_JOB_TYPE,
                    )
                )
                if registered is None or self._manifest_data(registered) != snapshot:
                    raise TailRadarPersistenceError(
                        "Tail Radar source snapshot is no longer a matching official manifest"
                    )
                existing = self._find_run_for_snapshot_rule(
                    session,
                    snapshot_id=snapshot.snapshot_id,
                    screening_rule_version=screening_rule_version,
                )
                if existing is not None:
                    run, feature_run = existing
                    return TailRadarRunClaim(
                        run=self._run_data(run, feature_run),
                        created=False,
                    )

                run = ExecutionRun(
                    job_type=TAIL_RADAR_JOB_TYPE,
                    trade_date=snapshot.trade_date,
                    intended_execution_time=snapshot.intended_snapshot_time,
                    actual_started_at=started_at,
                    status=RunStatus.RUNNING,
                    provider=None,
                    implementation_version=tail_radar_execution_version(
                        screening_rule_version=screening_rule_version,
                        snapshot_id=snapshot.snapshot_id,
                    ),
                    is_official=True,
                    run_metadata={},
                )
                session.add(run)
                session.flush()
                feature_run = TailRadarRunRecord(
                    run_id=run.run_id,
                    snapshot_id=snapshot.snapshot_id,
                    screening_rule_version=screening_rule_version,
                    rule_configuration=rule_configuration.model_dump(mode="json"),
                )
                session.add(feature_run)
                session.flush()
                run_data = self._run_data(run, feature_run)
                session.commit()
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except IntegrityError as exc:
                session.rollback()
                try:
                    existing = self._find_run_for_snapshot_rule(
                        session,
                        snapshot_id=snapshot.snapshot_id,
                        screening_rule_version=screening_rule_version,
                    )
                except SQLAlchemyError as lookup_error:
                    raise TailRadarPersistenceError(
                        "conflicting Tail Radar run could not be read"
                    ) from lookup_error
                if existing is None:
                    raise TailRadarPersistenceError("Tail Radar run could not be claimed") from exc
                run, feature_run = existing
                return TailRadarRunClaim(
                    run=self._run_data(run, feature_run),
                    created=False,
                )
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError("Tail Radar run could not be claimed") from exc
            return TailRadarRunClaim(run=run_data, created=True)

    def complete_run(
        self,
        *,
        run_id: UUID,
        candidates: Sequence[TailRadarCandidateCreate],
        evaluated_record_count: int,
        invalid_record_count: int,
        finished_at: datetime,
    ) -> TailRadarRunData:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    select(ExecutionRun, TailRadarRunRecord)
                    .join(TailRadarRunRecord, TailRadarRunRecord.run_id == ExecutionRun.run_id)
                    .where(ExecutionRun.run_id == run_id)
                    .with_for_update()
                ).one_or_none()
                if row is None:
                    raise TailRadarPersistenceError("Tail Radar run was not found for completion")
                run, feature_run = row._tuple()
                if run.status is not RunStatus.RUNNING:
                    raise TailRadarPersistenceError(
                        "Tail Radar run is not available for completion"
                    )
                if run.actual_started_at is None or finished_at < run.actual_started_at:
                    raise TailRadarPersistenceError("Tail Radar run has invalid completion timing")
                if invalid_record_count < 0 or evaluated_record_count < 0:
                    raise TailRadarPersistenceError("Tail Radar counts cannot be negative")
                if invalid_record_count + len(candidates) > evaluated_record_count:
                    raise TailRadarPersistenceError(
                        "Tail Radar candidate and invalid counts exceed evaluated records"
                    )
                symbols = {candidate.symbol for candidate in candidates}
                if len(symbols) != len(candidates):
                    raise TailRadarPersistenceError(
                        "Tail Radar candidates contain duplicate symbols"
                    )
                artifacts: list[ResearchArtifact] = []
                candidate_records: list[TailRadarCandidateRecord] = []
                for candidate in candidates:
                    if (
                        candidate.run_id != run_id
                        or candidate.snapshot_id != feature_run.snapshot_id
                        or candidate.payload.screening_rule_version
                        != feature_run.screening_rule_version
                        or run.implementation_version
                        != tail_radar_execution_version(
                            screening_rule_version=feature_run.screening_rule_version,
                            snapshot_id=feature_run.snapshot_id,
                        )
                        or candidate.as_of > finished_at
                    ):
                        raise TailRadarPersistenceError(
                            "Tail Radar candidate does not match its claimed run"
                        )
                    artifacts.append(
                        ResearchArtifact(
                            artifact_id=candidate.candidate_id,
                            module="tail_radar",
                            artifact_type=TAIL_RADAR_CANDIDATE_ARTIFACT_TYPE,
                            symbol=candidate.symbol,
                            trade_date=candidate.trade_date,
                            as_of=candidate.as_of,
                            schema_version=TAIL_RADAR_CANDIDATE_ARTIFACT_SCHEMA_VERSION,
                            payload=candidate.payload.model_dump(mode="json"),
                        )
                    )
                    candidate_records.append(
                        TailRadarCandidateRecord(
                            candidate_id=candidate.candidate_id,
                            run_id=run_id,
                            snapshot_id=candidate.snapshot_id,
                            symbol=candidate.symbol,
                        )
                    )

                session.add_all(artifacts)
                session.flush()
                session.add_all(candidate_records)

                feature_run.evaluated_record_count = evaluated_record_count
                feature_run.invalid_record_count = invalid_record_count
                feature_run.candidate_count = len(candidates)
                run.status = RunStatus.SUCCEEDED
                run.actual_finished_at = finished_at
                run.error_code = None
                run.error_message = None
                run.error_details = None
                session.flush()
                run_data = self._run_data(run, feature_run)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar candidates could not be prepared for commit"
                ) from exc
            try:
                session.commit()
            except SQLAlchemyError as exc:
                raise TailRadarCommitUncertainError(
                    "Tail Radar candidate commit outcome is uncertain"
                ) from exc
            return run_data

    def fail_run(
        self,
        *,
        run_id: UUID,
        finished_at: datetime,
        error_code: str,
    ) -> TailRadarRunData:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    select(ExecutionRun, TailRadarRunRecord)
                    .join(TailRadarRunRecord, TailRadarRunRecord.run_id == ExecutionRun.run_id)
                    .where(ExecutionRun.run_id == run_id)
                    .with_for_update()
                ).one_or_none()
                if row is None:
                    raise TailRadarPersistenceError("Tail Radar run was not found for failure")
                run, feature_run = row._tuple()
                if run.status is not RunStatus.RUNNING:
                    raise TailRadarPersistenceError("Tail Radar run is not available for failure")
                run.status = RunStatus.FAILED
                run.actual_finished_at = finished_at
                run.error_code = error_code[:128]
                run.error_message = "Tail Radar screening failed"
                run.error_details = None
                session.flush()
                run_data = self._run_data(run, feature_run)
                session.commit()
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError("Tail Radar failure could not be recorded") from exc
            return run_data

    def get_latest_run(self) -> TailRadarRunData | None:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    self._run_select()
                    .order_by(
                        ExecutionRun.intended_execution_time.desc(),
                        ExecutionRun.created_at.desc(),
                    )
                    .limit(1)
                ).one_or_none()
                return None if row is None else self._run_data(*row._tuple())
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError("latest Tail Radar run could not be read") from exc

    def list_runs(self, *, offset: int, limit: int) -> TailRadarRunPage:
        with self._session_factory() as session:
            try:
                total = session.scalar(select(func.count()).select_from(TailRadarRunRecord)) or 0
                rows = session.execute(
                    self._run_select()
                    .order_by(
                        ExecutionRun.intended_execution_time.desc(),
                        ExecutionRun.created_at.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                ).all()
                items = tuple(self._run_data(*row._tuple()) for row in rows)
                return TailRadarRunPage(items=items, total=total, offset=offset, limit=limit)
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError("Tail Radar runs could not be listed") from exc

    def get_run(self, run_id: UUID) -> TailRadarRunData | None:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    self._run_select().where(ExecutionRun.run_id == run_id)
                ).one_or_none()
                return None if row is None else self._run_data(*row._tuple())
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError("Tail Radar run could not be read") from exc

    def list_candidates(self, *, run_id: UUID, offset: int, limit: int) -> TailRadarCandidatePage:
        with self._session_factory() as session:
            try:
                total = (
                    session.scalar(
                        select(func.count())
                        .select_from(TailRadarCandidateRecord)
                        .where(TailRadarCandidateRecord.run_id == run_id)
                    )
                    or 0
                )
                rows = session.execute(
                    self._candidate_select()
                    .where(TailRadarCandidateRecord.run_id == run_id)
                    .order_by(TailRadarCandidateRecord.symbol)
                    .offset(offset)
                    .limit(limit)
                ).all()
                items = tuple(self._candidate_data(*row._tuple()) for row in rows)
                return TailRadarCandidatePage(
                    items=items,
                    total=total,
                    offset=offset,
                    limit=limit,
                )
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError(
                    "Tail Radar candidates could not be listed"
                ) from exc

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    self._candidate_select().where(
                        TailRadarCandidateRecord.candidate_id == candidate_id
                    )
                ).one_or_none()
                return None if row is None else self._candidate_data(*row._tuple())
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError("Tail Radar candidate could not be read") from exc

    @staticmethod
    def _find_run_for_snapshot_rule(
        session: Session,
        *,
        snapshot_id: UUID,
        screening_rule_version: str,
    ) -> tuple[ExecutionRun, TailRadarRunRecord] | None:
        row = session.execute(
            select(ExecutionRun, TailRadarRunRecord)
            .join(TailRadarRunRecord, TailRadarRunRecord.run_id == ExecutionRun.run_id)
            .where(
                TailRadarRunRecord.snapshot_id == snapshot_id,
                TailRadarRunRecord.screening_rule_version == screening_rule_version,
            )
        ).one_or_none()
        return None if row is None else row._tuple()

    @staticmethod
    def _run_select() -> Select[tuple[ExecutionRun, TailRadarRunRecord]]:
        return select(ExecutionRun, TailRadarRunRecord).join(
            TailRadarRunRecord,
            TailRadarRunRecord.run_id == ExecutionRun.run_id,
        )

    @staticmethod
    def _candidate_select() -> Select[
        tuple[
            TailRadarCandidateRecord,
            ResearchArtifact,
            ExecutionRun,
            TailRadarRunRecord,
        ]
    ]:
        return (
            select(
                TailRadarCandidateRecord,
                ResearchArtifact,
                ExecutionRun,
                TailRadarRunRecord,
            )
            .join(
                ResearchArtifact,
                ResearchArtifact.artifact_id == TailRadarCandidateRecord.candidate_id,
            )
            .join(ExecutionRun, ExecutionRun.run_id == TailRadarCandidateRecord.run_id)
            .join(TailRadarRunRecord, TailRadarRunRecord.run_id == ExecutionRun.run_id)
        )

    @staticmethod
    def _manifest_data(record: MarketSnapshotManifestRecord) -> PersistedSnapshotManifest:
        try:
            return PersistedSnapshotManifest.model_validate(record)
        except ValidationError as exc:
            raise TailRadarPersistenceError("stored market snapshot manifest is invalid") from exc

    @staticmethod
    def _run_data(run: ExecutionRun, feature_run: TailRadarRunRecord) -> TailRadarRunData:
        if run.actual_started_at is None:
            raise TailRadarPersistenceError("stored Tail Radar run has no start timestamp")
        if (
            run.job_type != TAIL_RADAR_JOB_TYPE
            or run.implementation_version
            != tail_radar_execution_version(
                screening_rule_version=feature_run.screening_rule_version,
                snapshot_id=feature_run.snapshot_id,
            )
        ):
            raise TailRadarPersistenceError("stored Tail Radar run metadata is inconsistent")
        try:
            configuration = TailRadarScreeningConfiguration.model_validate(
                feature_run.rule_configuration
            )
            return TailRadarRunData(
                run_id=run.run_id,
                snapshot_id=feature_run.snapshot_id,
                trade_date=run.trade_date,
                intended_snapshot_time=run.intended_execution_time,
                actual_started_at=run.actual_started_at,
                actual_finished_at=run.actual_finished_at,
                status=run.status,
                screening_rule_version=feature_run.screening_rule_version,
                is_official=run.is_official,
                rule_configuration=configuration,
                evaluated_record_count=feature_run.evaluated_record_count,
                invalid_record_count=feature_run.invalid_record_count,
                candidate_count=feature_run.candidate_count,
                error_code=run.error_code,
                created_at=run.created_at,
                updated_at=run.updated_at,
            )
        except ValidationError as exc:
            raise TailRadarPersistenceError("stored Tail Radar run is invalid") from exc

    @staticmethod
    def _candidate_data(
        candidate: TailRadarCandidateRecord,
        artifact: ResearchArtifact,
        run: ExecutionRun,
        feature_run: TailRadarRunRecord,
    ) -> TailRadarCandidateData:
        try:
            payload = TailRadarCandidatePayload.model_validate(artifact.payload)
            data = TailRadarCandidateData(
                candidate_id=candidate.candidate_id,
                run_id=candidate.run_id,
                snapshot_id=candidate.snapshot_id,
                symbol=candidate.symbol,
                trade_date=artifact.trade_date,
                as_of=artifact.as_of,
                payload=payload,
                created_at=artifact.created_at,
            )
        except ValidationError as exc:
            raise TailRadarPersistenceError("stored Tail Radar candidate is invalid") from exc
        if (
            artifact.artifact_id != candidate.candidate_id
            or artifact.module != "tail_radar"
            or artifact.artifact_type != TAIL_RADAR_CANDIDATE_ARTIFACT_TYPE
            or artifact.schema_version != TAIL_RADAR_CANDIDATE_ARTIFACT_SCHEMA_VERSION
            or artifact.symbol != candidate.symbol
            or feature_run.snapshot_id != candidate.snapshot_id
            or payload.screening_rule_version != feature_run.screening_rule_version
            or run.implementation_version
            != tail_radar_execution_version(
                screening_rule_version=feature_run.screening_rule_version,
                snapshot_id=feature_run.snapshot_id,
            )
        ):
            raise TailRadarPersistenceError("stored Tail Radar candidate metadata is inconsistent")
        return data
