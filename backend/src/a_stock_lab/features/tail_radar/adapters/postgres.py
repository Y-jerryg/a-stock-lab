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
    TailRadarIntradayAnalysisRecord,
    TailRadarResearchRecord,
    TailRadarResearchSourceRecord,
    TailRadarRunRecord,
    TailRadarWorkflowCandidateRecord,
    TailRadarWorkflowRecord,
)
from a_stock_lab.features.tail_radar.application.intraday_models import (
    TAIL_RADAR_INTRADAY_ARTIFACT_TYPE,
    TailRadarIntradayAnalysisCreate,
    TailRadarIntradayAnalysisData,
    TailRadarIntradayAnalysisPayload,
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
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TAIL_RADAR_WORKFLOW_JOB_TYPE,
    TailRadarCandidateStageStatus,
    TailRadarWorkflowCandidateState,
    TailRadarWorkflowClaim,
    TailRadarWorkflowData,
    TailRadarWorkflowLifecycle,
)
from a_stock_lab.features.tail_radar.application.research_models import (
    TAIL_RADAR_RESEARCH_ARTIFACT_TYPE,
    ResearchTokenUsage,
    TailRadarResearchClaimRequest,
    TailRadarResearchClaimResult,
    TailRadarResearchCompletion,
    TailRadarResearchData,
    TailRadarResearchPayload,
    TailRadarResearchSourceData,
    TailRadarResearchStatus,
)
from a_stock_lab.features.tail_radar.domain.errors import (
    TailRadarCommitUncertainError,
    TailRadarPersistenceError,
)
from a_stock_lab.features.tail_radar.domain.intraday import INTRADAY_FEATURE_SCHEMA_VERSION
from a_stock_lab.features.tail_radar.domain.research import TAIL_RADAR_RESEARCH_SCHEMA_VERSION
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

    def get_intraday_analysis(
        self,
        *,
        candidate_id: UUID,
        analysis_as_of: datetime,
        calculation_version: str,
    ) -> TailRadarIntradayAnalysisData | None:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    self._intraday_select().where(
                        TailRadarIntradayAnalysisRecord.candidate_id == candidate_id,
                        TailRadarIntradayAnalysisRecord.analysis_as_of == analysis_as_of,
                        TailRadarIntradayAnalysisRecord.calculation_version == calculation_version,
                    )
                ).one_or_none()
                return None if row is None else self._intraday_data(*row._tuple())
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError(
                    "Tail Radar intraday analysis could not be read"
                ) from exc

    def get_latest_intraday_analysis(
        self, candidate_id: UUID
    ) -> TailRadarIntradayAnalysisData | None:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    self._intraday_select()
                    .where(TailRadarIntradayAnalysisRecord.candidate_id == candidate_id)
                    .order_by(
                        TailRadarIntradayAnalysisRecord.analysis_as_of.desc(),
                        ResearchArtifact.created_at.desc(),
                    )
                    .limit(1)
                ).one_or_none()
                return None if row is None else self._intraday_data(*row._tuple())
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError(
                    "latest Tail Radar intraday analysis could not be read"
                ) from exc

    def get_latest_intraday_analyses(
        self, candidate_ids: Sequence[UUID]
    ) -> dict[UUID, TailRadarIntradayAnalysisData]:
        if not candidate_ids:
            return {}
        with self._session_factory() as session:
            try:
                rows = session.execute(
                    self._intraday_select()
                    .where(TailRadarIntradayAnalysisRecord.candidate_id.in_(candidate_ids))
                    .distinct(TailRadarIntradayAnalysisRecord.candidate_id)
                    .order_by(
                        TailRadarIntradayAnalysisRecord.candidate_id,
                        TailRadarIntradayAnalysisRecord.analysis_as_of.desc(),
                        ResearchArtifact.created_at.desc(),
                    )
                ).all()
                return {row[0].candidate_id: self._intraday_data(*row._tuple()) for row in rows}
            except (SQLAlchemyError, ValidationError) as exc:
                raise TailRadarPersistenceError(
                    "latest Tail Radar intraday analyses could not be read"
                ) from exc

    def get_intraday_analysis_at_or_before(
        self, *, candidate_id: UUID, analysis_as_of: datetime
    ) -> TailRadarIntradayAnalysisData | None:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    self._intraday_select()
                    .where(
                        TailRadarIntradayAnalysisRecord.candidate_id == candidate_id,
                        TailRadarIntradayAnalysisRecord.analysis_as_of <= analysis_as_of,
                    )
                    .order_by(
                        TailRadarIntradayAnalysisRecord.analysis_as_of.desc(),
                        ResearchArtifact.created_at.desc(),
                    )
                    .limit(1)
                ).one_or_none()
                return None if row is None else self._intraday_data(*row._tuple())
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError(
                    "point-in-time Tail Radar intraday analysis could not be read"
                ) from exc

    def save_intraday_analysis(
        self, analysis: TailRadarIntradayAnalysisCreate
    ) -> tuple[TailRadarIntradayAnalysisData, bool]:
        with self._session_factory() as session:
            try:
                source_row = session.execute(
                    self._candidate_select().where(
                        TailRadarCandidateRecord.candidate_id == analysis.candidate_id
                    )
                ).one_or_none()
                if source_row is None:
                    raise TailRadarPersistenceError(
                        "Tail Radar candidate was not found for intraday analysis"
                    )
                source = self._candidate_data(*source_row._tuple())
                if (
                    source.run_id != analysis.run_id
                    or source.snapshot_id != analysis.snapshot_id
                    or source.symbol != analysis.symbol
                    or source.trade_date != analysis.trade_date
                    or source.as_of != analysis.payload.source_candidate_as_of
                ):
                    raise TailRadarPersistenceError(
                        "Tail Radar intraday analysis does not match its candidate"
                    )
                artifact = ResearchArtifact(
                    artifact_id=analysis.analysis_id,
                    module="tail_radar",
                    artifact_type=TAIL_RADAR_INTRADAY_ARTIFACT_TYPE,
                    symbol=analysis.symbol,
                    trade_date=analysis.trade_date,
                    as_of=analysis.analysis_as_of,
                    schema_version=INTRADAY_FEATURE_SCHEMA_VERSION,
                    payload=analysis.payload.model_dump(mode="json"),
                )
                record = TailRadarIntradayAnalysisRecord(
                    analysis_id=analysis.analysis_id,
                    candidate_id=analysis.candidate_id,
                    run_id=analysis.run_id,
                    snapshot_id=analysis.snapshot_id,
                    symbol=analysis.symbol,
                    analysis_as_of=analysis.analysis_as_of,
                    calculation_version=analysis.payload.calculation_version,
                )
                session.add(artifact)
                session.flush()
                session.add(record)
                session.flush()
                data = self._intraday_data(record, artifact)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except IntegrityError as exc:
                session.rollback()
                try:
                    existing = session.execute(
                        self._intraday_select().where(
                            TailRadarIntradayAnalysisRecord.candidate_id == analysis.candidate_id,
                            TailRadarIntradayAnalysisRecord.analysis_as_of
                            == analysis.analysis_as_of,
                            TailRadarIntradayAnalysisRecord.calculation_version
                            == analysis.payload.calculation_version,
                        )
                    ).one_or_none()
                except SQLAlchemyError as lookup_error:
                    raise TailRadarPersistenceError(
                        "conflicting Tail Radar intraday analysis could not be read"
                    ) from lookup_error
                if existing is None:
                    raise TailRadarPersistenceError(
                        "Tail Radar intraday analysis could not be persisted"
                    ) from exc
                return self._intraday_data(*existing._tuple()), False
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar intraday analysis could not be prepared for commit"
                ) from exc
            try:
                session.commit()
            except SQLAlchemyError as exc:
                raise TailRadarCommitUncertainError(
                    "Tail Radar intraday analysis commit outcome is uncertain"
                ) from exc
            return data, True

    def claim_research(
        self, request: TailRadarResearchClaimRequest
    ) -> TailRadarResearchClaimResult:
        with self._session_factory() as session:
            try:
                source_row = session.execute(
                    self._candidate_select().where(
                        TailRadarCandidateRecord.candidate_id == request.candidate_id
                    )
                ).one_or_none()
                if source_row is None:
                    raise TailRadarPersistenceError(
                        "Tail Radar candidate was not found for web research"
                    )
                source = self._candidate_data(*source_row._tuple())
                if (
                    source.run_id != request.run_id
                    or source.snapshot_id != request.snapshot_id
                    or source.symbol != request.symbol
                    or source.trade_date != request.trade_date
                ):
                    raise TailRadarPersistenceError(
                        "Tail Radar web research does not match its candidate"
                    )
                cached = self._find_cached_research(session, request)
                if cached is not None and not request.force:
                    return TailRadarResearchClaimResult(
                        research=self._research_data(session, *cached),
                        created=False,
                    )
                record = TailRadarResearchRecord(
                    research_id=request.research_id,
                    artifact_id=None,
                    candidate_id=request.candidate_id,
                    run_id=request.run_id,
                    snapshot_id=request.snapshot_id,
                    symbol=request.symbol,
                    trade_date=request.trade_date,
                    analysis_as_of=request.analysis_as_of,
                    prompt_version=request.prompt_version,
                    prompt_sha256=request.prompt_sha256,
                    provider=request.provider,
                    requested_model=request.requested_model,
                    actual_model=None,
                    provider_response_id=None,
                    status=TailRadarResearchStatus.RUNNING.value,
                    is_forced=request.force,
                    base_research_id=(None if cached is None else cached[0].research_id),
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    error_code=None,
                    actual_started_at=request.started_at,
                    actual_finished_at=None,
                )
                session.add(record)
                session.flush()
                data = self._research_data(session, record, None)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except IntegrityError as exc:
                session.rollback()
                if request.force:
                    raise TailRadarPersistenceError(
                        "forced Tail Radar web research could not be claimed"
                    ) from exc
                try:
                    cached = self._find_cached_research(session, request)
                except SQLAlchemyError as lookup_error:
                    raise TailRadarPersistenceError(
                        "conflicting Tail Radar web research could not be read"
                    ) from lookup_error
                if cached is None:
                    raise TailRadarPersistenceError(
                        "Tail Radar web research could not be claimed"
                    ) from exc
                return TailRadarResearchClaimResult(
                    research=self._research_data(session, *cached),
                    created=False,
                )
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar web research could not be prepared for claim"
                ) from exc
            try:
                session.commit()
            except SQLAlchemyError as exc:
                raise TailRadarCommitUncertainError(
                    "Tail Radar web-research claim commit outcome is uncertain"
                ) from exc
            return TailRadarResearchClaimResult(research=data, created=True)

    def complete_research(self, completion: TailRadarResearchCompletion) -> TailRadarResearchData:
        with self._session_factory() as session:
            try:
                record = session.scalar(
                    select(TailRadarResearchRecord)
                    .where(TailRadarResearchRecord.research_id == completion.research_id)
                    .with_for_update()
                )
                if record is None:
                    raise TailRadarPersistenceError(
                        "Tail Radar web research was not found for completion"
                    )
                if record.status != TailRadarResearchStatus.RUNNING.value:
                    raise TailRadarPersistenceError(
                        "Tail Radar web research is not available for completion"
                    )
                payload = completion.payload
                if (
                    payload.candidate_id != record.candidate_id
                    or payload.source_run_id != record.run_id
                    or payload.source_snapshot_id != record.snapshot_id
                    or payload.symbol != record.symbol
                    or payload.analysis_as_of != record.analysis_as_of
                    or payload.prompt_version != record.prompt_version
                    or payload.prompt_sha256 != record.prompt_sha256
                    or payload.provider != record.provider
                    or payload.requested_model != record.requested_model
                    or payload.model_identifier != completion.actual_model
                    or payload.provider_response_id != completion.provider_response_id
                    or completion.finished_at < record.actual_started_at
                ):
                    raise TailRadarPersistenceError(
                        "Tail Radar web-research completion metadata is inconsistent"
                    )
                source_ids = {source.source_id for source in completion.sources}
                reference_ids = {source.source_id for source in payload.source_references}
                if source_ids != reference_ids:
                    raise TailRadarPersistenceError(
                        "Tail Radar web-research source references are inconsistent"
                    )
                artifact = ResearchArtifact(
                    artifact_id=completion.artifact_id,
                    module="tail_radar",
                    artifact_type=TAIL_RADAR_RESEARCH_ARTIFACT_TYPE,
                    symbol=record.symbol,
                    trade_date=record.trade_date,
                    as_of=record.analysis_as_of,
                    schema_version=TAIL_RADAR_RESEARCH_SCHEMA_VERSION,
                    payload=payload.model_dump(mode="json"),
                )
                session.add(artifact)
                session.flush()
                session.add_all(
                    [
                        TailRadarResearchSourceRecord(
                            source_id=source.source_id,
                            research_id=source.research_id,
                            url=str(source.url),
                            title=source.title,
                            publisher_domain=source.publisher_domain,
                            published_at=source.published_at,
                            publication_timestamp_status=(
                                source.publication_timestamp_status.value
                            ),
                            availability_at_as_of=source.availability_at_as_of.value,
                            retrieved_at=source.retrieved_at,
                            relationship_claim_ids=list(source.relationship_claim_ids),
                        )
                        for source in completion.sources
                    ]
                )
                record.artifact_id = completion.artifact_id
                record.status = completion.status.value
                record.actual_model = completion.actual_model
                record.provider_response_id = completion.provider_response_id
                record.input_tokens = completion.token_usage.input_tokens
                record.output_tokens = completion.token_usage.output_tokens
                record.total_tokens = completion.token_usage.total_tokens
                record.error_code = None
                record.actual_finished_at = completion.finished_at
                session.flush()
                data = self._research_data(session, record, artifact)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except (IntegrityError, SQLAlchemyError) as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar web research could not be prepared for commit"
                ) from exc
            try:
                session.commit()
            except SQLAlchemyError as exc:
                raise TailRadarCommitUncertainError(
                    "Tail Radar web-research completion commit outcome is uncertain"
                ) from exc
            return data

    def fail_research(
        self, *, research_id: UUID, finished_at: datetime, error_code: str
    ) -> TailRadarResearchData:
        with self._session_factory() as session:
            try:
                record = session.scalar(
                    select(TailRadarResearchRecord)
                    .where(TailRadarResearchRecord.research_id == research_id)
                    .with_for_update()
                )
                if record is None:
                    raise TailRadarPersistenceError(
                        "Tail Radar web research was not found for failure"
                    )
                if record.status != TailRadarResearchStatus.RUNNING.value:
                    raise TailRadarPersistenceError(
                        "Tail Radar web research is not available for failure"
                    )
                if finished_at < record.actual_started_at:
                    raise TailRadarPersistenceError(
                        "Tail Radar web research has invalid failure timing"
                    )
                record.status = TailRadarResearchStatus.FAILED.value
                record.error_code = error_code[:128]
                record.actual_finished_at = finished_at
                session.flush()
                data = self._research_data(session, record, None)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar web-research failure could not be prepared"
                ) from exc
            try:
                session.commit()
            except SQLAlchemyError as exc:
                raise TailRadarCommitUncertainError(
                    "Tail Radar web-research failure commit outcome is uncertain"
                ) from exc
            return data

    def get_latest_research(self, candidate_id: UUID) -> TailRadarResearchData | None:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    self._research_select()
                    .where(
                        TailRadarResearchRecord.candidate_id == candidate_id,
                        TailRadarResearchRecord.status.in_(
                            [
                                TailRadarResearchStatus.SUCCEEDED.value,
                                TailRadarResearchStatus.NO_EVIDENCE.value,
                            ]
                        ),
                    )
                    .order_by(
                        TailRadarResearchRecord.analysis_as_of.desc(),
                        TailRadarResearchRecord.created_at.desc(),
                    )
                    .limit(1)
                ).one_or_none()
                return None if row is None else self._research_data(session, *row._tuple())
            except SQLAlchemyError as exc:
                raise TailRadarPersistenceError(
                    "latest Tail Radar web research could not be read"
                ) from exc

    def claim_workflow(
        self,
        *,
        intended_snapshot_time: datetime,
        requested_analysis_as_of: datetime | None,
        workflow_version: str,
        started_at: datetime,
    ) -> TailRadarWorkflowClaim:
        with self._session_factory() as session:
            try:
                existing = self._find_workflow(
                    session,
                    intended_snapshot_time=intended_snapshot_time,
                    workflow_version=workflow_version,
                )
                if existing is not None:
                    run, workflow = existing
                    if (
                        requested_analysis_as_of is not None
                        and workflow.analysis_as_of != requested_analysis_as_of
                    ):
                        raise TailRadarPersistenceError(
                            "Tail Radar workflow analysis_as_of conflicts with its "
                            "official identity"
                        )
                    return TailRadarWorkflowClaim(
                        workflow=self._workflow_data(run, workflow),
                        created=False,
                    )
                run = ExecutionRun(
                    job_type=TAIL_RADAR_WORKFLOW_JOB_TYPE,
                    trade_date=intended_snapshot_time.date(),
                    intended_execution_time=intended_snapshot_time,
                    actual_started_at=started_at,
                    status=RunStatus.RUNNING,
                    provider=None,
                    implementation_version=workflow_version,
                    is_official=True,
                    run_metadata={},
                )
                session.add(run)
                session.flush()
                workflow = TailRadarWorkflowRecord(
                    workflow_run_id=run.run_id,
                    workflow_version=workflow_version,
                    lifecycle=TailRadarWorkflowLifecycle.CLAIMED.value,
                    analysis_as_of=requested_analysis_as_of,
                    candidate_count=None,
                    technical_succeeded_count=0,
                    technical_failed_count=0,
                    technical_pending_count=0,
                    research_succeeded_count=0,
                    research_no_evidence_count=0,
                    research_failed_count=0,
                    research_pending_count=0,
                )
                session.add(workflow)
                session.flush()
                data = self._workflow_data(run, workflow)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except IntegrityError as exc:
                session.rollback()
                try:
                    existing = self._find_workflow(
                        session,
                        intended_snapshot_time=intended_snapshot_time,
                        workflow_version=workflow_version,
                    )
                except SQLAlchemyError as lookup_error:
                    raise TailRadarPersistenceError(
                        "conflicting Tail Radar workflow could not be read"
                    ) from lookup_error
                if existing is None:
                    raise TailRadarPersistenceError(
                        "Tail Radar workflow could not be claimed"
                    ) from exc
                run, workflow = existing
                if (
                    requested_analysis_as_of is not None
                    and workflow.analysis_as_of != requested_analysis_as_of
                ):
                    raise TailRadarPersistenceError(
                        "Tail Radar workflow analysis_as_of conflicts with its official identity"
                    ) from exc
                return TailRadarWorkflowClaim(
                    workflow=self._workflow_data(run, workflow),
                    created=False,
                )
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError("Tail Radar workflow could not be claimed") from exc
            try:
                session.commit()
            except SQLAlchemyError as exc:
                raise TailRadarCommitUncertainError(
                    "Tail Radar workflow claim commit outcome is uncertain"
                ) from exc
            return TailRadarWorkflowClaim(workflow=data, created=True)

    def get_workflow(self, workflow_run_id: UUID) -> TailRadarWorkflowData | None:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    self._workflow_select().where(
                        TailRadarWorkflowRecord.workflow_run_id == workflow_run_id
                    )
                ).one_or_none()
                return None if row is None else self._workflow_data(*row._tuple())
            except (SQLAlchemyError, ValidationError) as exc:
                raise TailRadarPersistenceError("Tail Radar workflow could not be read") from exc

    def get_workflow_for_intended_time(
        self, *, intended_snapshot_time: datetime, workflow_version: str
    ) -> TailRadarWorkflowData | None:
        with self._session_factory() as session:
            try:
                row = self._find_workflow(
                    session,
                    intended_snapshot_time=intended_snapshot_time,
                    workflow_version=workflow_version,
                )
                return None if row is None else self._workflow_data(*row)
            except (SQLAlchemyError, ValidationError) as exc:
                raise TailRadarPersistenceError("Tail Radar workflow could not be read") from exc

    def get_workflow_for_screening_run(
        self, screening_run_id: UUID
    ) -> TailRadarWorkflowData | None:
        with self._session_factory() as session:
            try:
                row = session.execute(
                    self._workflow_select().where(
                        TailRadarWorkflowRecord.screening_run_id == screening_run_id
                    )
                ).one_or_none()
                return None if row is None else self._workflow_data(*row._tuple())
            except (SQLAlchemyError, ValidationError) as exc:
                raise TailRadarPersistenceError("Tail Radar workflow could not be read") from exc

    def set_workflow_lifecycle(
        self,
        *,
        workflow_run_id: UUID,
        lifecycle: TailRadarWorkflowLifecycle,
    ) -> TailRadarWorkflowData:
        if lifecycle in {
            TailRadarWorkflowLifecycle.SUCCEEDED,
            TailRadarWorkflowLifecycle.PARTIAL_SUCCESS,
            TailRadarWorkflowLifecycle.FAILED,
        }:
            raise TailRadarPersistenceError("terminal workflow states require explicit completion")
        with self._session_factory() as session:
            try:
                run, workflow = self._locked_workflow(session, workflow_run_id)
                run.status = RunStatus.RUNNING
                run.actual_finished_at = None
                run.error_code = None
                run.error_message = None
                run.error_details = None
                workflow.lifecycle = lifecycle.value
                workflow.error_stage = None
                workflow.error_code = None
                session.flush()
                data = self._workflow_data(run, workflow)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar workflow lifecycle could not be updated"
                ) from exc
            self._commit_workflow(session, "lifecycle")
            return data

    def attach_workflow_snapshot(
        self,
        *,
        workflow_run_id: UUID,
        snapshot_run_id: UUID,
        snapshot_id: UUID,
    ) -> TailRadarWorkflowData:
        with self._session_factory() as session:
            try:
                run, workflow = self._locked_workflow(session, workflow_run_id)
                manifest = session.scalar(
                    select(MarketSnapshotManifestRecord)
                    .join(ExecutionRun, ExecutionRun.run_id == MarketSnapshotManifestRecord.run_id)
                    .where(
                        MarketSnapshotManifestRecord.snapshot_id == snapshot_id,
                        MarketSnapshotManifestRecord.run_id == snapshot_run_id,
                        MarketSnapshotManifestRecord.status == SnapshotManifestStatus.AVAILABLE,
                        ExecutionRun.status == RunStatus.SUCCEEDED,
                        ExecutionRun.is_official.is_(True),
                        ExecutionRun.job_type == FULL_MARKET_SNAPSHOT_JOB_TYPE,
                    )
                )
                if manifest is None:
                    raise TailRadarPersistenceError(
                        "workflow snapshot is not a successful official manifest"
                    )
                if workflow.snapshot_id not in {
                    None,
                    snapshot_id,
                } or workflow.snapshot_run_id not in {
                    None,
                    snapshot_run_id,
                }:
                    raise TailRadarPersistenceError("workflow snapshot linkage is immutable")
                workflow.snapshot_run_id = snapshot_run_id
                workflow.snapshot_id = snapshot_id
                session.flush()
                data = self._workflow_data(run, workflow)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar workflow snapshot could not be attached"
                ) from exc
            self._commit_workflow(session, "snapshot linkage")
            return data

    def attach_workflow_screening(
        self,
        *,
        workflow_run_id: UUID,
        screening_run_id: UUID,
        analysis_as_of: datetime,
        candidate_ids: Sequence[UUID],
    ) -> TailRadarWorkflowData:
        if len(set(candidate_ids)) != len(candidate_ids):
            raise TailRadarPersistenceError("workflow candidate IDs must be unique")
        with self._session_factory() as session:
            try:
                run, workflow = self._locked_workflow(session, workflow_run_id)
                screening_row = session.execute(
                    select(TailRadarRunRecord, ExecutionRun)
                    .join(ExecutionRun, ExecutionRun.run_id == TailRadarRunRecord.run_id)
                    .where(TailRadarRunRecord.run_id == screening_run_id)
                ).one_or_none()
                screening = None if screening_row is None else screening_row[0]
                screening_execution = None if screening_row is None else screening_row[1]
                if (
                    screening is None
                    or screening_execution is None
                    or screening_execution.status is not RunStatus.SUCCEEDED
                    or not screening_execution.is_official
                    or screening.snapshot_id != workflow.snapshot_id
                    or screening.candidate_count != len(candidate_ids)
                ):
                    raise TailRadarPersistenceError(
                        "workflow screening is not a successful official result matching its "
                        "snapshot and candidates"
                    )
                persisted_ids = set(
                    session.scalars(
                        select(TailRadarCandidateRecord.candidate_id).where(
                            TailRadarCandidateRecord.run_id == screening_run_id
                        )
                    ).all()
                )
                if persisted_ids != set(candidate_ids):
                    raise TailRadarPersistenceError(
                        "workflow candidate set does not match persisted screening output"
                    )
                if workflow.screening_run_id not in {None, screening_run_id}:
                    raise TailRadarPersistenceError("workflow screening linkage is immutable")
                if workflow.analysis_as_of not in {None, analysis_as_of}:
                    raise TailRadarPersistenceError("workflow analysis_as_of is immutable")
                workflow.screening_run_id = screening_run_id
                workflow.analysis_as_of = analysis_as_of
                existing_ids = set(
                    session.scalars(
                        select(TailRadarWorkflowCandidateRecord.candidate_id).where(
                            TailRadarWorkflowCandidateRecord.workflow_run_id == workflow_run_id
                        )
                    ).all()
                )
                session.add_all(
                    [
                        TailRadarWorkflowCandidateRecord(
                            workflow_run_id=workflow_run_id,
                            candidate_id=candidate_id,
                            technical_status=TailRadarCandidateStageStatus.PENDING.value,
                            research_status=TailRadarCandidateStageStatus.PENDING.value,
                        )
                        for candidate_id in candidate_ids
                        if candidate_id not in existing_ids
                    ]
                )
                workflow.candidate_count = len(candidate_ids)
                workflow.technical_pending_count = len(candidate_ids)
                workflow.research_pending_count = len(candidate_ids)
                workflow.technical_succeeded_count = 0
                workflow.technical_failed_count = 0
                workflow.research_succeeded_count = 0
                workflow.research_no_evidence_count = 0
                workflow.research_failed_count = 0
                session.flush()
                self._refresh_workflow_counts(session, workflow)
                data = self._workflow_data(run, workflow)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except (IntegrityError, SQLAlchemyError) as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar workflow screening could not be attached"
                ) from exc
            self._commit_workflow(session, "screening linkage")
            return data

    def list_workflow_candidate_states(
        self, workflow_run_id: UUID
    ) -> tuple[TailRadarWorkflowCandidateState, ...]:
        with self._session_factory() as session:
            try:
                rows = session.scalars(
                    select(TailRadarWorkflowCandidateRecord)
                    .where(TailRadarWorkflowCandidateRecord.workflow_run_id == workflow_run_id)
                    .order_by(TailRadarWorkflowCandidateRecord.candidate_id)
                ).all()
                return tuple(self._workflow_candidate_data(row) for row in rows)
            except (SQLAlchemyError, ValidationError) as exc:
                raise TailRadarPersistenceError(
                    "Tail Radar workflow candidate states could not be read"
                ) from exc

    def get_candidate_workflow_state(
        self, candidate_id: UUID
    ) -> TailRadarWorkflowCandidateState | None:
        with self._session_factory() as session:
            try:
                row = session.scalar(
                    select(TailRadarWorkflowCandidateRecord)
                    .join(
                        TailRadarWorkflowRecord,
                        TailRadarWorkflowRecord.workflow_run_id
                        == TailRadarWorkflowCandidateRecord.workflow_run_id,
                    )
                    .where(TailRadarWorkflowCandidateRecord.candidate_id == candidate_id)
                    .order_by(TailRadarWorkflowRecord.created_at.desc())
                    .limit(1)
                )
                return None if row is None else self._workflow_candidate_data(row)
            except (SQLAlchemyError, ValidationError) as exc:
                raise TailRadarPersistenceError(
                    "Tail Radar candidate workflow state could not be read"
                ) from exc

    def set_candidate_technical_stage(
        self,
        *,
        workflow_run_id: UUID,
        candidate_id: UUID,
        status: TailRadarCandidateStageStatus,
        analysis_id: UUID | None = None,
        error_code: str | None = None,
    ) -> TailRadarWorkflowCandidateState:
        if status is TailRadarCandidateStageStatus.NO_EVIDENCE:
            raise TailRadarPersistenceError("technical analysis cannot use no_evidence status")
        return self._set_candidate_stage(
            workflow_run_id=workflow_run_id,
            candidate_id=candidate_id,
            stage="technical",
            status=status,
            linked_id=analysis_id,
            error_code=error_code,
        )

    def set_candidate_research_stage(
        self,
        *,
        workflow_run_id: UUID,
        candidate_id: UUID,
        status: TailRadarCandidateStageStatus,
        research_id: UUID | None = None,
        error_code: str | None = None,
    ) -> TailRadarWorkflowCandidateState:
        return self._set_candidate_stage(
            workflow_run_id=workflow_run_id,
            candidate_id=candidate_id,
            stage="research",
            status=status,
            linked_id=research_id,
            error_code=error_code,
        )

    def complete_workflow(
        self, *, workflow_run_id: UUID, finished_at: datetime
    ) -> TailRadarWorkflowData:
        with self._session_factory() as session:
            try:
                run, workflow = self._locked_workflow(session, workflow_run_id)
                self._refresh_workflow_counts(session, workflow)
                incomplete = any(
                    (
                        workflow.technical_failed_count,
                        workflow.technical_pending_count,
                    )
                )
                workflow.lifecycle = (
                    TailRadarWorkflowLifecycle.PARTIAL_SUCCESS.value
                    if incomplete
                    else TailRadarWorkflowLifecycle.SUCCEEDED.value
                )
                workflow.error_stage = None
                workflow.error_code = None
                run.status = RunStatus.SUCCEEDED
                run.actual_finished_at = finished_at
                run.error_code = None
                run.error_message = None
                run.error_details = None
                session.flush()
                data = self._workflow_data(run, workflow)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar workflow could not be completed"
                ) from exc
            self._commit_workflow(session, "completion")
            return data

    def fail_workflow(
        self,
        *,
        workflow_run_id: UUID,
        finished_at: datetime,
        error_stage: str,
        error_code: str,
    ) -> TailRadarWorkflowData:
        with self._session_factory() as session:
            try:
                run, workflow = self._locked_workflow(session, workflow_run_id)
                self._refresh_workflow_counts(session, workflow)
                workflow.lifecycle = TailRadarWorkflowLifecycle.FAILED.value
                workflow.error_stage = error_stage[:64]
                workflow.error_code = error_code[:128]
                run.status = RunStatus.FAILED
                run.actual_finished_at = finished_at
                run.error_code = error_code[:128]
                run.error_message = None
                run.error_details = {"stage": error_stage[:64]}
                session.flush()
                data = self._workflow_data(run, workflow)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar workflow failure was not recorded"
                ) from exc
            self._commit_workflow(session, "failure")
            return data

    def _set_candidate_stage(
        self,
        *,
        workflow_run_id: UUID,
        candidate_id: UUID,
        stage: str,
        status: TailRadarCandidateStageStatus,
        linked_id: UUID | None,
        error_code: str | None,
    ) -> TailRadarWorkflowCandidateState:
        success = status in {
            TailRadarCandidateStageStatus.SUCCEEDED,
            TailRadarCandidateStageStatus.NO_EVIDENCE,
        }
        if success != (linked_id is not None):
            raise TailRadarPersistenceError("successful candidate stage requires an artifact link")
        if (status is TailRadarCandidateStageStatus.FAILED) != bool(error_code):
            raise TailRadarPersistenceError("candidate failure status requires only an error code")
        with self._session_factory() as session:
            try:
                workflow = session.scalar(
                    select(TailRadarWorkflowRecord)
                    .where(TailRadarWorkflowRecord.workflow_run_id == workflow_run_id)
                    .with_for_update()
                )
                record = session.scalar(
                    select(TailRadarWorkflowCandidateRecord)
                    .where(
                        TailRadarWorkflowCandidateRecord.workflow_run_id == workflow_run_id,
                        TailRadarWorkflowCandidateRecord.candidate_id == candidate_id,
                    )
                    .with_for_update()
                )
                if workflow is None or record is None:
                    raise TailRadarPersistenceError("workflow candidate stage was not found")
                if success:
                    if linked_id is None:  # guarded above, retained for type narrowing
                        raise TailRadarPersistenceError(
                            "successful candidate stage requires an artifact link"
                        )
                    self._validate_workflow_stage_link(
                        session,
                        workflow=workflow,
                        candidate_id=candidate_id,
                        stage=stage,
                        status=status,
                        linked_id=linked_id,
                    )
                if stage == "technical":
                    record.technical_status = status.value
                    record.intraday_analysis_id = linked_id
                    record.technical_error_code = error_code[:128] if error_code else None
                else:
                    record.research_status = status.value
                    record.research_id = linked_id
                    record.research_error_code = error_code[:128] if error_code else None
                session.flush()
                self._refresh_workflow_counts(session, workflow)
                data = self._workflow_candidate_data(record)
            except TailRadarPersistenceError:
                session.rollback()
                raise
            except (IntegrityError, SQLAlchemyError) as exc:
                session.rollback()
                raise TailRadarPersistenceError(
                    "Tail Radar workflow candidate stage could not be updated"
                ) from exc
            self._commit_workflow(session, f"candidate {stage} stage")
            return data

    @staticmethod
    def _validate_workflow_stage_link(
        session: Session,
        *,
        workflow: TailRadarWorkflowRecord,
        candidate_id: UUID,
        stage: str,
        status: TailRadarCandidateStageStatus,
        linked_id: UUID,
    ) -> None:
        if workflow.screening_run_id is None or workflow.analysis_as_of is None:
            raise TailRadarPersistenceError(
                "workflow candidate artifacts require screening and analysis provenance"
            )
        if stage == "technical":
            analysis = session.get(TailRadarIntradayAnalysisRecord, linked_id)
            if (
                analysis is None
                or analysis.candidate_id != candidate_id
                or analysis.run_id != workflow.screening_run_id
                or analysis.snapshot_id != workflow.snapshot_id
                or analysis.analysis_as_of != workflow.analysis_as_of
            ):
                raise TailRadarPersistenceError(
                    "technical artifact does not match its workflow candidate provenance"
                )
            return
        research = session.get(TailRadarResearchRecord, linked_id)
        if (
            research is None
            or research.candidate_id != candidate_id
            or research.run_id != workflow.screening_run_id
            or research.snapshot_id != workflow.snapshot_id
            or research.analysis_as_of != workflow.analysis_as_of
            or research.status != status.value
        ):
            raise TailRadarPersistenceError(
                "research artifact does not match its workflow candidate provenance"
            )

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
    def _workflow_select() -> Select[tuple[ExecutionRun, TailRadarWorkflowRecord]]:
        return select(ExecutionRun, TailRadarWorkflowRecord).join(
            TailRadarWorkflowRecord,
            TailRadarWorkflowRecord.workflow_run_id == ExecutionRun.run_id,
        )

    @classmethod
    def _find_workflow(
        cls,
        session: Session,
        *,
        intended_snapshot_time: datetime,
        workflow_version: str,
    ) -> tuple[ExecutionRun, TailRadarWorkflowRecord] | None:
        row = session.execute(
            cls._workflow_select().where(
                ExecutionRun.job_type == TAIL_RADAR_WORKFLOW_JOB_TYPE,
                ExecutionRun.trade_date == intended_snapshot_time.date(),
                ExecutionRun.intended_execution_time == intended_snapshot_time,
                ExecutionRun.implementation_version == workflow_version,
                ExecutionRun.is_official.is_(True),
            )
        ).one_or_none()
        return None if row is None else row._tuple()

    @classmethod
    def _locked_workflow(
        cls, session: Session, workflow_run_id: UUID
    ) -> tuple[ExecutionRun, TailRadarWorkflowRecord]:
        row = session.execute(
            cls._workflow_select()
            .where(TailRadarWorkflowRecord.workflow_run_id == workflow_run_id)
            .with_for_update()
        ).one_or_none()
        if row is None:
            raise TailRadarPersistenceError("Tail Radar workflow was not found")
        return row._tuple()

    @staticmethod
    def _refresh_workflow_counts(session: Session, workflow: TailRadarWorkflowRecord) -> None:
        rows = session.execute(
            select(
                TailRadarWorkflowCandidateRecord.technical_status,
                TailRadarWorkflowCandidateRecord.research_status,
            ).where(TailRadarWorkflowCandidateRecord.workflow_run_id == workflow.workflow_run_id)
        ).all()
        technical = [row.technical_status for row in rows]
        research = [row.research_status for row in rows]
        workflow.candidate_count = len(rows) if workflow.screening_run_id is not None else None
        workflow.technical_succeeded_count = technical.count(
            TailRadarCandidateStageStatus.SUCCEEDED.value
        )
        workflow.technical_failed_count = technical.count(
            TailRadarCandidateStageStatus.FAILED.value
        )
        workflow.technical_pending_count = len(technical) - (
            workflow.technical_succeeded_count + workflow.technical_failed_count
        )
        workflow.research_succeeded_count = research.count(
            TailRadarCandidateStageStatus.SUCCEEDED.value
        )
        workflow.research_no_evidence_count = research.count(
            TailRadarCandidateStageStatus.NO_EVIDENCE.value
        )
        workflow.research_failed_count = research.count(TailRadarCandidateStageStatus.FAILED.value)
        workflow.research_pending_count = len(research) - (
            workflow.research_succeeded_count
            + workflow.research_no_evidence_count
            + workflow.research_failed_count
        )

    @staticmethod
    def _workflow_data(
        run: ExecutionRun, workflow: TailRadarWorkflowRecord
    ) -> TailRadarWorkflowData:
        if run.trade_date is None or run.actual_started_at is None:
            raise TailRadarPersistenceError("Tail Radar workflow execution metadata is incomplete")
        return TailRadarWorkflowData(
            workflow_run_id=workflow.workflow_run_id,
            trade_date=run.trade_date,
            intended_snapshot_time=run.intended_execution_time,
            analysis_as_of=workflow.analysis_as_of,
            workflow_version=workflow.workflow_version,
            lifecycle=TailRadarWorkflowLifecycle(workflow.lifecycle),
            execution_status=run.status,
            snapshot_run_id=workflow.snapshot_run_id,
            snapshot_id=workflow.snapshot_id,
            screening_run_id=workflow.screening_run_id,
            candidate_count=workflow.candidate_count,
            technical_succeeded_count=workflow.technical_succeeded_count,
            technical_failed_count=workflow.technical_failed_count,
            technical_pending_count=workflow.technical_pending_count,
            research_succeeded_count=workflow.research_succeeded_count,
            research_no_evidence_count=workflow.research_no_evidence_count,
            research_failed_count=workflow.research_failed_count,
            research_pending_count=workflow.research_pending_count,
            error_stage=workflow.error_stage,
            error_code=workflow.error_code,
            actual_started_at=run.actual_started_at,
            actual_finished_at=run.actual_finished_at,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
        )

    @staticmethod
    def _workflow_candidate_data(
        record: TailRadarWorkflowCandidateRecord,
    ) -> TailRadarWorkflowCandidateState:
        return TailRadarWorkflowCandidateState(
            workflow_run_id=record.workflow_run_id,
            candidate_id=record.candidate_id,
            technical_status=TailRadarCandidateStageStatus(record.technical_status),
            research_status=TailRadarCandidateStageStatus(record.research_status),
            intraday_analysis_id=record.intraday_analysis_id,
            research_id=record.research_id,
            technical_error_code=record.technical_error_code,
            research_error_code=record.research_error_code,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _commit_workflow(session: Session, operation: str) -> None:
        try:
            session.commit()
        except SQLAlchemyError as exc:
            raise TailRadarCommitUncertainError(
                f"Tail Radar workflow {operation} commit outcome is uncertain"
            ) from exc

    @classmethod
    def _find_cached_research(
        cls,
        session: Session,
        request: TailRadarResearchClaimRequest,
    ) -> tuple[TailRadarResearchRecord, ResearchArtifact | None] | None:
        row = session.execute(
            cls._research_select().where(
                TailRadarResearchRecord.candidate_id == request.candidate_id,
                TailRadarResearchRecord.run_id == request.run_id,
                TailRadarResearchRecord.analysis_as_of == request.analysis_as_of,
                TailRadarResearchRecord.prompt_version == request.prompt_version,
                TailRadarResearchRecord.provider == request.provider,
                TailRadarResearchRecord.requested_model == request.requested_model,
                TailRadarResearchRecord.is_forced.is_(False),
            )
        ).one_or_none()
        if row is None:
            return None
        cached = row._tuple()
        if cached[0].prompt_sha256 != request.prompt_sha256:
            raise TailRadarPersistenceError(
                "Tail Radar research prompt version was reused with different content"
            )
        return cached

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
    def _intraday_select() -> Select[tuple[TailRadarIntradayAnalysisRecord, ResearchArtifact]]:
        return select(TailRadarIntradayAnalysisRecord, ResearchArtifact).join(
            ResearchArtifact,
            ResearchArtifact.artifact_id == TailRadarIntradayAnalysisRecord.analysis_id,
        )

    @staticmethod
    def _research_select() -> Select[tuple[TailRadarResearchRecord, ResearchArtifact]]:
        return select(TailRadarResearchRecord, ResearchArtifact).outerjoin(
            ResearchArtifact,
            ResearchArtifact.artifact_id == TailRadarResearchRecord.artifact_id,
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

    @staticmethod
    def _intraday_data(
        record: TailRadarIntradayAnalysisRecord,
        artifact: ResearchArtifact,
    ) -> TailRadarIntradayAnalysisData:
        try:
            payload = TailRadarIntradayAnalysisPayload.model_validate(artifact.payload)
            data = TailRadarIntradayAnalysisData(
                analysis_id=record.analysis_id,
                candidate_id=record.candidate_id,
                run_id=record.run_id,
                snapshot_id=record.snapshot_id,
                symbol=record.symbol,
                trade_date=artifact.trade_date,
                analysis_as_of=record.analysis_as_of,
                payload=payload,
                created_at=artifact.created_at,
            )
        except ValidationError as exc:
            raise TailRadarPersistenceError(
                "stored Tail Radar intraday analysis is invalid"
            ) from exc
        if (
            artifact.artifact_id != record.analysis_id
            or artifact.module != "tail_radar"
            or artifact.artifact_type != TAIL_RADAR_INTRADAY_ARTIFACT_TYPE
            or artifact.schema_version != payload.feature_schema_version
            or artifact.symbol != record.symbol
            or artifact.as_of != record.analysis_as_of
            or payload.calculation_version != record.calculation_version
        ):
            raise TailRadarPersistenceError(
                "stored Tail Radar intraday analysis metadata is inconsistent"
            )
        return data

    @staticmethod
    def _research_data(
        session: Session,
        record: TailRadarResearchRecord,
        artifact: ResearchArtifact | None,
    ) -> TailRadarResearchData:
        try:
            status = TailRadarResearchStatus(record.status)
            payload = (
                None
                if artifact is None
                else TailRadarResearchPayload.model_validate(artifact.payload)
            )
            source_records = session.scalars(
                select(TailRadarResearchSourceRecord)
                .where(TailRadarResearchSourceRecord.research_id == record.research_id)
                .order_by(TailRadarResearchSourceRecord.source_id)
            ).all()
            sources = tuple(
                TailRadarResearchSourceData(
                    source_id=source.source_id,
                    research_id=source.research_id,
                    url=source.url,
                    title=source.title,
                    publisher_domain=source.publisher_domain,
                    published_at=source.published_at,
                    publication_timestamp_status=source.publication_timestamp_status,
                    availability_at_as_of=source.availability_at_as_of,
                    retrieved_at=source.retrieved_at,
                    relationship_claim_ids=tuple(source.relationship_claim_ids),
                    created_at=source.created_at,
                )
                for source in source_records
            )
            data = TailRadarResearchData(
                research_id=record.research_id,
                artifact_id=record.artifact_id,
                candidate_id=record.candidate_id,
                run_id=record.run_id,
                snapshot_id=record.snapshot_id,
                symbol=record.symbol,
                trade_date=record.trade_date,
                analysis_as_of=record.analysis_as_of,
                prompt_version=record.prompt_version,
                prompt_sha256=record.prompt_sha256,
                provider=record.provider,
                requested_model=record.requested_model,
                actual_model=record.actual_model,
                provider_response_id=record.provider_response_id,
                status=status,
                is_forced=record.is_forced,
                base_research_id=record.base_research_id,
                token_usage=ResearchTokenUsage(
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    total_tokens=record.total_tokens,
                ),
                error_code=record.error_code,
                actual_started_at=record.actual_started_at,
                actual_finished_at=record.actual_finished_at,
                created_at=record.created_at,
                updated_at=record.updated_at,
                payload=payload,
                sources=sources,
            )
        except (ValidationError, ValueError) as exc:
            raise TailRadarPersistenceError("stored Tail Radar web research is invalid") from exc
        if artifact is None:
            if record.artifact_id is not None or sources:
                raise TailRadarPersistenceError(
                    "stored Tail Radar web-research lifecycle is inconsistent"
                )
            return data
        if payload is None:  # pragma: no cover - artifact branch parsed a payload above
            raise AssertionError("web-research artifact payload was not parsed")
        if (
            artifact.artifact_id != record.artifact_id
            or artifact.module != "tail_radar"
            or artifact.artifact_type != TAIL_RADAR_RESEARCH_ARTIFACT_TYPE
            or artifact.schema_version != TAIL_RADAR_RESEARCH_SCHEMA_VERSION
            or artifact.symbol != record.symbol
            or artifact.trade_date != record.trade_date
            or artifact.as_of != record.analysis_as_of
            or payload.candidate_id != record.candidate_id
            or payload.source_run_id != record.run_id
            or payload.source_snapshot_id != record.snapshot_id
            or payload.prompt_version != record.prompt_version
            or payload.prompt_sha256 != record.prompt_sha256
            or payload.provider != record.provider
            or payload.requested_model != record.requested_model
            or payload.model_identifier != record.actual_model
            or payload.provider_response_id != record.provider_response_id
            or {source.source_id for source in sources}
            != {source.source_id for source in payload.source_references}
        ):
            raise TailRadarPersistenceError(
                "stored Tail Radar web-research metadata is inconsistent"
            )
        return data
