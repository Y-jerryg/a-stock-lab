import os
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.adapters.persistence_models import (
    TailRadarCandidateRecord,
    TailRadarIntradayAnalysisRecord,
    TailRadarRunRecord,
    TailRadarWorkflowCandidateRecord,
    TailRadarWorkflowRecord,
)
from a_stock_lab.features.tail_radar.adapters.postgres import PostgresTailRadarRepository
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateCreate,
    TailRadarCandidatePayload,
)
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TAIL_RADAR_WORKFLOW_VERSION,
    TailRadarCandidateStageStatus,
    TailRadarWorkflowLifecycle,
)
from a_stock_lab.features.tail_radar.domain.errors import TailRadarPersistenceError
from a_stock_lab.features.tail_radar.domain.screening import (
    TAIL_RADAR_SCREENING_RULE_VERSION,
    TailRadarDecisionOutcome,
    TailRadarDecisionReason,
    TailRadarScreeningConfiguration,
    TailRadarScreeningDecision,
    TailRadarSnapshotEvidence,
)
from a_stock_lab.shared.artifacts.models import ResearchArtifact
from a_stock_lab.shared.execution.models import ExecutionRun, RunStatus
from a_stock_lab.shared.market_data.adapters.postgres import (
    PostgresSnapshotExecutionRepository,
)
from a_stock_lab.shared.market_data.execution_models import (
    FULL_MARKET_SNAPSHOT_JOB_TYPE,
    SnapshotManifestCreate,
    SnapshotRunKey,
)
from a_stock_lab.shared.market_data.models import (
    MarketSnapshotRecord,
    SnapshotManifestStatus,
    SnapshotQualityReport,
    SnapshotQualityThresholds,
)
from a_stock_lab.shared.market_data.persistence_models import MarketSnapshotManifestRecord

pytestmark = pytest.mark.postgres


def test_postgres_workflow_lifecycle_is_idempotent_and_preserves_partial_progress() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    snapshot_repository = PostgresSnapshotExecutionRepository(factory)
    repository = PostgresTailRadarRepository(factory)
    intended = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
    fetched_at = intended + timedelta(seconds=2)
    persisted_at = intended + timedelta(seconds=3)
    analysis_as_of = intended + timedelta(minutes=5)
    snapshot_id = uuid4()
    candidate_id = uuid4()
    snapshot_run_id: UUID | None = None
    screening_run_id: UUID | None = None
    workflow_run_id: UUID | None = None
    invalid_analysis_id: UUID | None = None
    quality = SnapshotQualityReport(
        passed=True,
        raw_record_count=1,
        normalized_record_count=1,
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
    try:
        snapshot_claim = snapshot_repository.claim_run(
            key=SnapshotRunKey(
                job_type=FULL_MARKET_SNAPSHOT_JOB_TYPE,
                trade_date=intended.date(),
                intended_snapshot_time=intended,
                execution_version=f"workflow-test-{uuid4().hex[:20]}",
            ),
            provider="fixture",
            started_at=intended,
            force=False,
        )
        snapshot_run_id = snapshot_claim.run.run_id
        _, manifest = snapshot_repository.complete_run(
            manifest=SnapshotManifestCreate(
                snapshot_id=snapshot_id,
                run_id=snapshot_run_id,
                trade_date=intended.date(),
                intended_snapshot_time=intended,
                actual_fetch_started_at=intended + timedelta(seconds=1),
                actual_fetch_finished_at=fetched_at,
                provider="fixture",
                provider_version="fixture-1",
                provider_metadata={},
                storage_key=f"market-data/2026-08-28/workflow-{snapshot_id}.parquet",
                checksum_sha256="a" * 64,
                row_count=1,
                latency_ms=1_000,
                quality_report=quality,
                schema_version=2,
                status=SnapshotManifestStatus.AVAILABLE,
                persisted_at=persisted_at,
            ),
            run_metadata={},
            finished_at=persisted_at,
        )
        screening_claim = repository.claim_run(
            snapshot=manifest,
            screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
            rule_configuration=TailRadarScreeningConfiguration(),
            started_at=intended + timedelta(minutes=1),
        )
        screening_run_id = screening_claim.run.run_id
        record = MarketSnapshotRecord(
            symbol="600000",
            name="fixture",
            price=10.25,
            pct_change=4.0,
            provider="fixture",
            fetched_at=fetched_at,
        )
        evidence = TailRadarSnapshotEvidence(
            snapshot_id=snapshot_id,
            snapshot_run_id=snapshot_run_id,
            trade_date=intended.date(),
            intended_snapshot_time=intended,
            actual_fetch_started_at=intended + timedelta(seconds=1),
            actual_fetch_finished_at=fetched_at,
            provider="fixture",
            checksum_sha256="a" * 64,
            snapshot_schema_version=2,
        )
        repository.complete_run(
            run_id=screening_run_id,
            candidates=(
                TailRadarCandidateCreate(
                    candidate_id=candidate_id,
                    run_id=screening_run_id,
                    snapshot_id=snapshot_id,
                    symbol=record.symbol,
                    trade_date=intended.date(),
                    as_of=fetched_at,
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
                ),
            ),
            evaluated_record_count=1,
            invalid_record_count=0,
            finished_at=intended + timedelta(minutes=1, seconds=1),
        )

        claim = repository.claim_workflow(
            intended_snapshot_time=intended,
            requested_analysis_as_of=analysis_as_of,
            workflow_version=TAIL_RADAR_WORKFLOW_VERSION,
            started_at=intended + timedelta(minutes=2),
        )
        workflow_run_id = claim.workflow.workflow_run_id
        replay = repository.claim_workflow(
            intended_snapshot_time=intended,
            requested_analysis_as_of=analysis_as_of,
            workflow_version=TAIL_RADAR_WORKFLOW_VERSION,
            started_at=intended + timedelta(minutes=2),
        )
        repository.attach_workflow_snapshot(
            workflow_run_id=workflow_run_id,
            snapshot_run_id=snapshot_run_id,
            snapshot_id=snapshot_id,
        )
        repository.attach_workflow_screening(
            workflow_run_id=workflow_run_id,
            screening_run_id=screening_run_id,
            analysis_as_of=analysis_as_of,
            candidate_ids=(candidate_id,),
        )
        invalid_analysis_id = uuid4()
        with factory() as session:
            session.add(
                ResearchArtifact(
                    artifact_id=invalid_analysis_id,
                    module="tail_radar",
                    artifact_type="tail_radar.intraday_features",
                    symbol=record.symbol,
                    trade_date=intended.date(),
                    as_of=analysis_as_of + timedelta(minutes=1),
                    schema_version=2,
                    payload={},
                )
            )
            session.flush()
            session.add(
                TailRadarIntradayAnalysisRecord(
                    analysis_id=invalid_analysis_id,
                    candidate_id=candidate_id,
                    run_id=screening_run_id,
                    snapshot_id=snapshot_id,
                    symbol=record.symbol,
                    analysis_as_of=analysis_as_of + timedelta(minutes=1),
                    calculation_version="fixture-invalid-as-of",
                )
            )
            session.commit()
        with pytest.raises(TailRadarPersistenceError, match="candidate provenance"):
            repository.set_candidate_technical_stage(
                workflow_run_id=workflow_run_id,
                candidate_id=candidate_id,
                status=TailRadarCandidateStageStatus.SUCCEEDED,
                analysis_id=invalid_analysis_id,
            )
        repository.set_candidate_technical_stage(
            workflow_run_id=workflow_run_id,
            candidate_id=candidate_id,
            status=TailRadarCandidateStageStatus.FAILED,
            error_code="fixture_technical_failure",
        )
        repository.set_candidate_research_stage(
            workflow_run_id=workflow_run_id,
            candidate_id=candidate_id,
            status=TailRadarCandidateStageStatus.FAILED,
            error_code="fixture_research_failure",
        )
        completed = repository.complete_workflow(
            workflow_run_id=workflow_run_id,
            finished_at=analysis_as_of + timedelta(seconds=1),
        )

        assert claim.created is True
        assert replay.created is False
        assert replay.workflow.workflow_run_id == workflow_run_id
        assert completed.lifecycle is TailRadarWorkflowLifecycle.PARTIAL_SUCCESS
        assert completed.execution_status is RunStatus.SUCCEEDED
        assert completed.technical_failed_count == 1
        assert completed.research_failed_count == 1
        assert repository.get_workflow_for_screening_run(screening_run_id) == completed
        state = repository.get_candidate_workflow_state(candidate_id)
        assert state is not None
        assert state.technical_error_code == "fixture_technical_failure"
    finally:
        with factory() as session:
            if workflow_run_id is not None:
                session.execute(
                    delete(TailRadarWorkflowCandidateRecord).where(
                        TailRadarWorkflowCandidateRecord.workflow_run_id == workflow_run_id
                    )
                )
                session.execute(
                    delete(TailRadarWorkflowRecord).where(
                        TailRadarWorkflowRecord.workflow_run_id == workflow_run_id
                    )
                )
            if screening_run_id is not None:
                if invalid_analysis_id is not None:
                    session.execute(
                        delete(TailRadarIntradayAnalysisRecord).where(
                            TailRadarIntradayAnalysisRecord.analysis_id == invalid_analysis_id
                        )
                    )
                session.execute(
                    delete(TailRadarCandidateRecord).where(
                        TailRadarCandidateRecord.run_id == screening_run_id
                    )
                )
                session.execute(
                    delete(TailRadarRunRecord).where(TailRadarRunRecord.run_id == screening_run_id)
                )
            session.execute(
                delete(ResearchArtifact).where(
                    ResearchArtifact.artifact_id.in_(
                        [
                            artifact_id
                            for artifact_id in (candidate_id, invalid_analysis_id)
                            if artifact_id is not None
                        ]
                    )
                )
            )
            session.execute(
                delete(MarketSnapshotManifestRecord).where(
                    MarketSnapshotManifestRecord.snapshot_id == snapshot_id
                )
            )
            run_ids = [
                run_id
                for run_id in (workflow_run_id, screening_run_id, snapshot_run_id)
                if run_id is not None
            ]
            if run_ids:
                session.execute(delete(ExecutionRun).where(ExecutionRun.run_id.in_(run_ids)))
            session.commit()
        engine.dispose()
