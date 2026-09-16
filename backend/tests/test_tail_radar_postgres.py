import os
from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.adapters.persistence_models import (
    TailRadarCandidateRecord,
    TailRadarIntradayAnalysisRecord,
    TailRadarResearchRecord,
    TailRadarResearchSourceRecord,
    TailRadarRunRecord,
)
from a_stock_lab.features.tail_radar.adapters.postgres import PostgresTailRadarRepository
from a_stock_lab.features.tail_radar.application.intraday_models import (
    TailRadarIntradayAnalysisCreate,
    TailRadarIntradayAnalysisPayload,
)
from a_stock_lab.features.tail_radar.application.models import (
    TAIL_RADAR_CANDIDATE_ARTIFACT_TYPE,
    TailRadarCandidateCreate,
    TailRadarCandidatePayload,
)
from a_stock_lab.features.tail_radar.application.research_models import (
    ResearchTokenUsage,
    TailRadarResearchClaimRequest,
    TailRadarResearchCompletion,
    TailRadarResearchPayload,
    TailRadarResearchSourceCreate,
    TailRadarResearchSourceReference,
    TailRadarResearchStatus,
)
from a_stock_lab.features.tail_radar.domain.errors import (
    TailRadarCommitUncertainError,
    TailRadarPersistenceError,
)
from a_stock_lab.features.tail_radar.domain.intraday import (
    INTRADAY_CALCULATION_VERSION,
    IntradayFeatureConfiguration,
    IntradayFeatureEngine,
)
from a_stock_lab.features.tail_radar.domain.research import (
    PublicationTimestampStatus,
    ResearchClaimClassification,
    ResearchEvidenceQuality,
    SourceAvailabilityAtAsOf,
    TailRadarResearchClaim,
)
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
    IntradayBar,
    IntradayBarRequest,
    MarketSnapshotRecord,
    ProviderIntradayBarBatch,
    SnapshotManifestStatus,
    SnapshotQualityReport,
    SnapshotQualityThresholds,
)
from a_stock_lab.shared.market_data.persistence_models import MarketSnapshotManifestRecord

pytestmark = pytest.mark.postgres


def test_postgres_tail_radar_is_idempotent_and_persists_versioned_candidate_evidence() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")

    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    snapshot_repository = PostgresSnapshotExecutionRepository(factory)
    repository = PostgresTailRadarRepository(factory)
    intended = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
    fetch_started = intended + timedelta(seconds=1)
    fetch_finished = intended + timedelta(seconds=2)
    persisted_at = intended + timedelta(seconds=3)
    screen_started = intended + timedelta(minutes=1)
    screen_finished = screen_started + timedelta(seconds=1)
    snapshot_id = uuid4()
    candidate_id = uuid4()
    analysis_id = uuid4()
    research_id = uuid4()
    forced_research_id = uuid4()
    other_provider_research_id = uuid4()
    research_artifact_id = uuid4()
    research_source_id = uuid4()
    second_snapshot_id = uuid4()
    wrong_job_snapshot_id = uuid4()
    source_run_id = None
    second_source_run_id = None
    wrong_job_source_run_id = None
    tail_run_id = None
    second_tail_run_id = None

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
        source_claim = snapshot_repository.claim_run(
            key=SnapshotRunKey(
                job_type=FULL_MARKET_SNAPSHOT_JOB_TYPE,
                trade_date=intended.date(),
                intended_snapshot_time=intended,
                execution_version=f"test-{uuid4().hex}",
            ),
            provider="fixture",
            started_at=intended,
            force=False,
        )
        source_run_id = source_claim.run.run_id
        _, source = snapshot_repository.complete_run(
            manifest=SnapshotManifestCreate(
                snapshot_id=snapshot_id,
                run_id=source_run_id,
                trade_date=intended.date(),
                intended_snapshot_time=intended,
                actual_fetch_started_at=fetch_started,
                actual_fetch_finished_at=fetch_finished,
                provider="fixture",
                provider_version="fixture-1",
                provider_metadata={},
                storage_key=f"market-data/2026-08-28/full-market-{snapshot_id}.parquet",
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

        configuration = TailRadarScreeningConfiguration()
        first_claim = repository.claim_run(
            snapshot=source,
            screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
            rule_configuration=configuration,
            started_at=screen_started,
        )
        tail_run_id = first_claim.run.run_id
        duplicate_claim = repository.claim_run(
            snapshot=source,
            screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
            rule_configuration=configuration,
            started_at=screen_started,
        )

        assert first_claim.created is True
        assert duplicate_claim.created is False
        assert duplicate_claim.run.run_id == tail_run_id

        record = MarketSnapshotRecord(
            symbol="600000",
            name="浦发银行",
            price=10.25,
            pct_change=4.0,
            provider="fixture",
            fetched_at=fetch_finished,
        )
        evidence = TailRadarSnapshotEvidence(
            snapshot_id=snapshot_id,
            snapshot_run_id=source_run_id,
            trade_date=intended.date(),
            intended_snapshot_time=intended,
            actual_fetch_started_at=fetch_started,
            actual_fetch_finished_at=fetch_finished,
            provider="fixture",
            checksum_sha256=source.checksum_sha256,
            snapshot_schema_version=source.schema_version,
        )
        candidate = TailRadarCandidateCreate(
            candidate_id=candidate_id,
            run_id=tail_run_id,
            snapshot_id=snapshot_id,
            symbol=record.symbol,
            trade_date=intended.date(),
            as_of=fetch_finished,
            payload=TailRadarCandidatePayload(
                screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
                rule_configuration=configuration,
                snapshot_evidence=evidence,
                snapshot_record=record,
                decision=TailRadarScreeningDecision(
                    outcome=TailRadarDecisionOutcome.INCLUDED,
                    reason=TailRadarDecisionReason.PCT_CHANGE_IN_RANGE,
                    observed_pct_change=4.0,
                    observed_price=10.25,
                ),
            ),
        )
        completed = repository.complete_run(
            run_id=tail_run_id,
            candidates=(candidate,),
            evaluated_record_count=1,
            invalid_record_count=0,
            finished_at=screen_finished,
        )

        replay = repository.claim_run(
            snapshot=source,
            screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
            rule_configuration=configuration,
            started_at=screen_finished,
        )
        page = repository.list_candidates(run_id=tail_run_id, offset=0, limit=10)
        detail = repository.get_candidate(candidate_id)

        assert completed.status is RunStatus.SUCCEEDED
        assert completed.candidate_count == 1
        assert replay.created is False
        assert replay.run.status is RunStatus.SUCCEEDED
        assert page.total == 1
        assert page.items[0].candidate_id == candidate_id
        assert detail is not None
        assert detail.payload.snapshot_record == record
        assert detail.payload.snapshot_evidence.snapshot_id == snapshot_id

        analysis_as_of = intended + timedelta(minutes=5)
        intraday_request = IntradayBarRequest(
            symbol=record.symbol,
            start_at=intended.replace(hour=9, minute=30),
            end_at=analysis_as_of,
        )
        intraday_bar = IntradayBar(
            symbol=record.symbol,
            ended_at=analysis_as_of,
            open=10.2,
            high=10.3,
            low=10.2,
            close=10.25,
            volume=10_000,
            amount=102_500,
            provider="fixture-intraday",
            fetched_at=analysis_as_of + timedelta(seconds=1),
        )
        intraday_batch = ProviderIntradayBarBatch(
            provider="fixture-intraday",
            request=intraday_request,
            bars=(intraday_bar,),
            raw_record_count=1,
            provider_version="fixture-1",
            fetched_at=analysis_as_of + timedelta(seconds=1),
        )
        feature_engine = IntradayFeatureEngine()
        computation = feature_engine.calculate(
            batch=intraday_batch,
            analysis_as_of=analysis_as_of,
        )
        analysis_create = TailRadarIntradayAnalysisCreate(
            analysis_id=analysis_id,
            candidate_id=candidate_id,
            run_id=tail_run_id,
            snapshot_id=snapshot_id,
            symbol=record.symbol,
            trade_date=intended.date(),
            analysis_as_of=analysis_as_of,
            payload=TailRadarIntradayAnalysisPayload.from_computation(
                symbol=record.symbol,
                candidate_id=candidate_id,
                source_run_id=tail_run_id,
                source_snapshot_id=snapshot_id,
                source_candidate_as_of=fetch_finished,
                provider=intraday_batch.provider,
                provider_version=intraday_batch.provider_version,
                provider_metadata={},
                provider_fetched_at=intraday_batch.fetched_at,
                intraday_request=intraday_request,
                configuration=IntradayFeatureConfiguration(),
                computation=computation,
            ),
        )

        class CommitFailingSession(Session):
            def commit(self) -> None:
                raise SQLAlchemyError("simulated uncertain commit")

        failing_factory = sessionmaker(
            bind=engine,
            expire_on_commit=False,
            class_=CommitFailingSession,
        )
        with pytest.raises(TailRadarCommitUncertainError, match="outcome is uncertain"):
            PostgresTailRadarRepository(
                cast(sessionmaker[Session], failing_factory)
            ).save_intraday_analysis(analysis_create)

        saved_analysis, created = repository.save_intraday_analysis(analysis_create)
        replayed_analysis, replay_created = repository.save_intraday_analysis(analysis_create)
        latest_analysis = repository.get_latest_intraday_analysis(candidate_id)

        assert created is True
        assert replay_created is False
        assert replayed_analysis.analysis_id == saved_analysis.analysis_id
        assert latest_analysis is not None
        assert latest_analysis.analysis_id == analysis_id
        assert latest_analysis.payload.calculation_version == INTRADAY_CALCULATION_VERSION
        assert latest_analysis.payload.latest_bar_used == intraday_bar

        research_started = analysis_as_of + timedelta(seconds=2)
        research_finished = research_started + timedelta(seconds=2)
        research_request = TailRadarResearchClaimRequest(
            research_id=research_id,
            candidate_id=candidate_id,
            run_id=tail_run_id,
            snapshot_id=snapshot_id,
            symbol=record.symbol,
            trade_date=intended.date(),
            analysis_as_of=analysis_as_of,
            prompt_sha256="d" * 64,
            provider="openai",
            requested_model="fixture-model",
            started_at=research_started,
        )
        research_claim = repository.claim_research(research_request)
        replayed_research_claim = repository.claim_research(
            research_request.model_copy(update={"research_id": uuid4()})
        )
        with pytest.raises(TailRadarPersistenceError, match="prompt version"):
            repository.claim_research(
                research_request.model_copy(
                    update={"research_id": uuid4(), "prompt_sha256": "e" * 64}
                )
            )
        other_provider_claim = repository.claim_research(
            research_request.model_copy(
                update={
                    "research_id": other_provider_research_id,
                    "provider": "replacement-provider",
                }
            )
        )
        forced_research_claim = repository.claim_research(
            research_request.model_copy(update={"research_id": forced_research_id, "force": True})
        )

        assert research_claim.created is True
        assert replayed_research_claim.created is False
        assert replayed_research_claim.research.research_id == research_id
        assert other_provider_claim.created is True
        assert other_provider_claim.research.provider == "replacement-provider"
        assert forced_research_claim.created is True
        assert forced_research_claim.research.base_research_id == research_id

        persisted_claim = TailRadarResearchClaim(
            claim_id="fact_one",
            statement="A verified fixture fact.",
            classification=ResearchClaimClassification.VERIFIED_FACT,
            source_ids=(research_source_id,),
        )
        source_reference = TailRadarResearchSourceReference(
            source_id=research_source_id,
            url="https://example.test/announcement",
            publication_timestamp_status=PublicationTimestampStatus.VERIFIED,
            availability_at_as_of=SourceAvailabilityAtAsOf.AVAILABLE,
            relationship_claim_ids=(persisted_claim.claim_id,),
        )
        token_usage = ResearchTokenUsage(
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )
        research_payload = TailRadarResearchPayload(
            symbol=record.symbol,
            candidate_id=candidate_id,
            source_run_id=tail_run_id,
            source_snapshot_id=snapshot_id,
            source_candidate_as_of=fetch_finished,
            analysis_as_of=analysis_as_of,
            concise_summary="Fixture research summary.",
            verified_facts=(persisted_claim,),
            likely_drivers=(),
            company_context=(),
            sector_context=(),
            market_context=(),
            positive_factors=(),
            risk_factors=(),
            unresolved_questions=(),
            evidence_quality=ResearchEvidenceQuality.HIGH,
            confidence=0.9,
            provider="openai",
            requested_model="fixture-model",
            model_identifier="fixture-model-2026-08-28",
            provider_response_id="resp_fixture",
            prompt_sha256="d" * 64,
            source_references=(source_reference,),
            token_usage=token_usage,
        )
        saved_research = repository.complete_research(
            TailRadarResearchCompletion(
                research_id=research_id,
                artifact_id=research_artifact_id,
                status=TailRadarResearchStatus.SUCCEEDED,
                payload=research_payload,
                sources=(
                    TailRadarResearchSourceCreate(
                        source_id=research_source_id,
                        research_id=research_id,
                        url=source_reference.url,
                        title="Fixture announcement",
                        publisher_domain="example.test",
                        published_at=intended,
                        publication_timestamp_status=(PublicationTimestampStatus.VERIFIED),
                        availability_at_as_of=SourceAvailabilityAtAsOf.AVAILABLE,
                        retrieved_at=research_finished,
                        relationship_claim_ids=(persisted_claim.claim_id,),
                    ),
                ),
                actual_model="fixture-model-2026-08-28",
                provider_response_id="resp_fixture",
                token_usage=token_usage,
                finished_at=research_finished,
            )
        )
        latest_research = repository.get_latest_research(candidate_id)

        assert saved_research.status is TailRadarResearchStatus.SUCCEEDED
        assert saved_research.artifact_id == research_artifact_id
        assert saved_research.sources[0].source_id == research_source_id
        assert latest_research is not None
        assert latest_research.research_id == research_id
        assert latest_research.payload == research_payload

        second_source_claim = snapshot_repository.claim_run(
            key=SnapshotRunKey(
                job_type=FULL_MARKET_SNAPSHOT_JOB_TYPE,
                trade_date=intended.date(),
                intended_snapshot_time=intended,
                execution_version=f"test-{uuid4().hex}",
            ),
            provider="fixture",
            started_at=intended,
            force=False,
        )
        second_source_run_id = second_source_claim.run.run_id
        _, second_source = snapshot_repository.complete_run(
            manifest=SnapshotManifestCreate(
                snapshot_id=second_snapshot_id,
                run_id=second_source_run_id,
                trade_date=intended.date(),
                intended_snapshot_time=intended,
                actual_fetch_started_at=fetch_started,
                actual_fetch_finished_at=fetch_finished,
                provider="fixture",
                provider_version="fixture-2",
                provider_metadata={},
                storage_key=(f"market-data/2026-08-28/full-market-{second_snapshot_id}.parquet"),
                checksum_sha256="b" * 64,
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
        second_tail_claim = repository.claim_run(
            snapshot=second_source,
            screening_rule_version=TAIL_RADAR_SCREENING_RULE_VERSION,
            rule_configuration=configuration,
            started_at=screen_started,
        )
        second_tail_run_id = second_tail_claim.run.run_id

        assert second_tail_claim.created is True
        assert second_tail_run_id != tail_run_id

        wrong_job_claim = snapshot_repository.claim_run(
            key=SnapshotRunKey(
                job_type=f"test.not-a-full-market-snapshot.{uuid4().hex}",
                trade_date=intended.date(),
                intended_snapshot_time=intended,
                execution_version="test-1",
            ),
            provider="fixture",
            started_at=intended,
            force=False,
        )
        wrong_job_source_run_id = wrong_job_claim.run.run_id
        snapshot_repository.complete_run(
            manifest=SnapshotManifestCreate(
                snapshot_id=wrong_job_snapshot_id,
                run_id=wrong_job_source_run_id,
                trade_date=intended.date(),
                intended_snapshot_time=intended,
                actual_fetch_started_at=fetch_started,
                actual_fetch_finished_at=fetch_finished,
                provider="fixture",
                provider_version="fixture-1",
                provider_metadata={},
                storage_key=(f"market-data/2026-08-28/full-market-{wrong_job_snapshot_id}.parquet"),
                checksum_sha256="c" * 64,
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

        assert repository.get_official_snapshot(wrong_job_snapshot_id) is None
        with factory() as session:
            artifact = session.get(ResearchArtifact, candidate_id)
            assert artifact is not None
            assert artifact.artifact_type == TAIL_RADAR_CANDIDATE_ARTIFACT_TYPE
            assert artifact.schema_version == 1
            analysis_artifact = session.get(ResearchArtifact, analysis_id)
            assert analysis_artifact is not None
            assert analysis_artifact.artifact_type == "tail_radar.intraday_features"
            research_artifact = session.get(ResearchArtifact, research_artifact_id)
            assert research_artifact is not None
            assert research_artifact.artifact_type == "tail_radar.web_research"
            source_row = session.get(TailRadarResearchSourceRecord, research_source_id)
            assert source_row is not None
            assert source_row.publisher_domain == "example.test"
    finally:
        with factory.begin() as session:
            session.execute(
                delete(TailRadarResearchSourceRecord).where(
                    TailRadarResearchSourceRecord.research_id.in_((research_id, forced_research_id))
                )
            )
            session.execute(
                delete(TailRadarResearchRecord).where(
                    TailRadarResearchRecord.research_id.in_(
                        (research_id, forced_research_id, other_provider_research_id)
                    )
                )
            )
            session.execute(
                delete(ResearchArtifact).where(ResearchArtifact.artifact_id == research_artifact_id)
            )
            session.execute(
                delete(TailRadarIntradayAnalysisRecord).where(
                    TailRadarIntradayAnalysisRecord.analysis_id == analysis_id
                )
            )
            session.execute(
                delete(ResearchArtifact).where(ResearchArtifact.artifact_id == analysis_id)
            )
            session.execute(
                delete(TailRadarCandidateRecord).where(
                    TailRadarCandidateRecord.candidate_id == candidate_id
                )
            )
            session.execute(
                delete(ResearchArtifact).where(ResearchArtifact.artifact_id == candidate_id)
            )
            if tail_run_id is not None:
                session.execute(
                    delete(TailRadarRunRecord).where(TailRadarRunRecord.run_id == tail_run_id)
                )
                session.execute(delete(ExecutionRun).where(ExecutionRun.run_id == tail_run_id))
            if second_tail_run_id is not None:
                session.execute(
                    delete(TailRadarRunRecord).where(
                        TailRadarRunRecord.run_id == second_tail_run_id
                    )
                )
                session.execute(
                    delete(ExecutionRun).where(ExecutionRun.run_id == second_tail_run_id)
                )
            session.execute(
                delete(MarketSnapshotManifestRecord).where(
                    MarketSnapshotManifestRecord.snapshot_id.in_(
                        (snapshot_id, second_snapshot_id, wrong_job_snapshot_id)
                    )
                )
            )
            if source_run_id is not None:
                session.execute(delete(ExecutionRun).where(ExecutionRun.run_id == source_run_id))
            if second_source_run_id is not None:
                session.execute(
                    delete(ExecutionRun).where(ExecutionRun.run_id == second_source_run_id)
                )
            if wrong_job_source_run_id is not None:
                session.execute(
                    delete(ExecutionRun).where(ExecutionRun.run_id == wrong_job_source_run_id)
                )
        engine.dispose()
