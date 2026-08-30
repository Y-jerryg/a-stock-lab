from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.application.contracts import (
    TailRadarRepository,
    TailRadarResearchProvider,
)
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateData,
    TailRadarCandidatePayload,
)
from a_stock_lab.features.tail_radar.application.research_models import (
    ResearchProviderRequest,
    ResearchProviderResult,
    ResearchTokenUsage,
    TailRadarResearchClaimRequest,
    TailRadarResearchClaimResult,
    TailRadarResearchCompletion,
    TailRadarResearchData,
    TailRadarResearchSourceData,
    TailRadarResearchStatus,
)
from a_stock_lab.features.tail_radar.application.research_service import TailRadarResearchService
from a_stock_lab.features.tail_radar.domain.errors import (
    ResearchProviderInvalidResponseError,
    TailRadarResearchTimeError,
)
from a_stock_lab.features.tail_radar.domain.research import (
    ProviderResearchClaim,
    ProviderSourceAssessment,
    PublicationTimestampStatus,
    ResearchClaimClassification,
    ResearchEvidenceQuality,
    TailRadarResearchProviderOutput,
)
from a_stock_lab.features.tail_radar.domain.screening import (
    TAIL_RADAR_SCREENING_RULE_VERSION,
    TailRadarDecisionOutcome,
    TailRadarDecisionReason,
    TailRadarScreeningConfiguration,
    TailRadarScreeningDecision,
    TailRadarSnapshotEvidence,
)
from a_stock_lab.shared.market_data.models import MarketSnapshotRecord

CANDIDATE_ID = UUID("11111111-1111-4111-8111-111111111111")
RUN_ID = UUID("22222222-2222-4222-8222-222222222222")
SNAPSHOT_ID = UUID("33333333-3333-4333-8333-333333333333")
SNAPSHOT_RUN_ID = UUID("44444444-4444-4444-8444-444444444444")
INTENDED = datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
CANDIDATE_AS_OF = INTENDED + timedelta(seconds=2)
ANALYSIS_AS_OF = datetime(2026, 8, 28, 14, 35, tzinfo=MARKET_TIME_ZONE)
NOW = datetime(2026, 8, 30, 10, 0, tzinfo=MARKET_TIME_ZONE)
SOURCE_URL = "https://example.test/announcement"


def candidate_data() -> TailRadarCandidateData:
    evidence = TailRadarSnapshotEvidence(
        snapshot_id=SNAPSHOT_ID,
        snapshot_run_id=SNAPSHOT_RUN_ID,
        trade_date=INTENDED.date(),
        intended_snapshot_time=INTENDED,
        actual_fetch_started_at=INTENDED + timedelta(seconds=1),
        actual_fetch_finished_at=CANDIDATE_AS_OF,
        provider="fixture-market",
        checksum_sha256="a" * 64,
        snapshot_schema_version=1,
    )
    record = MarketSnapshotRecord(
        symbol="600000",
        name="Fixture Bank",
        price=10.25,
        pct_change=2.5,
        provider="fixture-market",
        fetched_at=CANDIDATE_AS_OF,
    )
    return TailRadarCandidateData(
        candidate_id=CANDIDATE_ID,
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        symbol=record.symbol,
        trade_date=INTENDED.date(),
        as_of=CANDIDATE_AS_OF,
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
        created_at=INTENDED + timedelta(seconds=3),
    )


def structured_output(
    *,
    published_at: datetime | None = INTENDED - timedelta(hours=1),
    timestamp_status: PublicationTimestampStatus = PublicationTimestampStatus.VERIFIED,
    include_evidence: bool = True,
) -> TailRadarResearchProviderOutput:
    claims = (
        (
            ProviderResearchClaim(
                claim_id="fact-1",
                statement="The company published a same-day announcement.",
                classification=ResearchClaimClassification.VERIFIED_FACT,
                source_urls=(SOURCE_URL,),
            ),
        )
        if include_evidence
        else ()
    )
    assessments = (
        (
            ProviderSourceAssessment(
                url=SOURCE_URL,
                published_at=published_at,
                publication_timestamp_status=timestamp_status,
                relationship_claim_ids=("fact-1",),
            ),
        )
        if include_evidence
        else ()
    )
    return TailRadarResearchProviderOutput(
        concise_summary="Point-in-time research summary.",
        verified_facts=claims,
        likely_drivers=(),
        company_context=(),
        sector_context=(),
        market_context=(),
        positive_factors=(),
        risk_factors=(),
        unresolved_questions=(),
        evidence_quality=(
            ResearchEvidenceQuality.HIGH
            if include_evidence
            else ResearchEvidenceQuality.INSUFFICIENT
        ),
        confidence=0.8 if include_evidence else 0,
        source_assessments=assessments,
    )


class FakeProvider:
    provider_id = "fixture-research"
    model_id = "fixture-model-v1"

    def __init__(
        self, output: TailRadarResearchProviderOutput, *, include_source: bool = True
    ) -> None:
        self.output = output
        self.include_source = include_source
        self.calls = 0
        self.requests: list[ResearchProviderRequest] = []

    def research(self, request: ResearchProviderRequest) -> ResearchProviderResult:
        self.calls += 1
        self.requests.append(request)
        from a_stock_lab.features.tail_radar.application.research_models import (
            ResearchProviderSource,
        )

        return ResearchProviderResult(
            provider=self.provider_id,
            requested_model=self.model_id,
            actual_model="fixture-model-snapshot",
            response_id=f"response-{self.calls}",
            retrieved_at=NOW,
            output=self.output,
            sources=(
                (
                    ResearchProviderSource(
                        url=SOURCE_URL,
                        title="Fixture announcement",
                        retrieved_at=NOW,
                    ),
                )
                if self.include_source
                else ()
            ),
            token_usage=ResearchTokenUsage(
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
            ),
        )


class FakeRepository:
    def __init__(self) -> None:
        self.candidate = candidate_data()
        self.cached: TailRadarResearchData | None = None
        self.attempts: dict[UUID, TailRadarResearchData] = {}
        self.point_in_time_intraday_queries: list[datetime] = []

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None:
        return self.candidate if candidate_id == CANDIDATE_ID else None

    def get_intraday_analysis_at_or_before(
        self, *, candidate_id: UUID, analysis_as_of: datetime
    ) -> None:
        assert candidate_id == CANDIDATE_ID
        self.point_in_time_intraday_queries.append(analysis_as_of)
        return None

    def claim_research(
        self, request: TailRadarResearchClaimRequest
    ) -> TailRadarResearchClaimResult:
        if not request.force and self.cached is not None:
            return TailRadarResearchClaimResult(research=self.cached, created=False)
        running = TailRadarResearchData(
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
            status=TailRadarResearchStatus.RUNNING,
            is_forced=request.force,
            base_research_id=None if self.cached is None else self.cached.research_id,
            token_usage=ResearchTokenUsage(),
            error_code=None,
            actual_started_at=request.started_at,
            actual_finished_at=None,
            created_at=request.started_at,
            updated_at=request.started_at,
            payload=None,
            sources=(),
        )
        self.attempts[running.research_id] = running
        if not request.force:
            self.cached = running
        return TailRadarResearchClaimResult(research=running, created=True)

    def complete_research(self, completion: TailRadarResearchCompletion) -> TailRadarResearchData:
        running = self.attempts[completion.research_id]
        values = running.model_dump(mode="python")
        values.update(
            artifact_id=completion.artifact_id,
            actual_model=completion.actual_model,
            provider_response_id=completion.provider_response_id,
            status=completion.status,
            token_usage=completion.token_usage,
            actual_finished_at=completion.finished_at,
            updated_at=completion.finished_at,
            payload=completion.payload,
            sources=tuple(
                TailRadarResearchSourceData(
                    **source.model_dump(mode="python"),
                    created_at=completion.finished_at,
                )
                for source in completion.sources
            ),
        )
        completed = TailRadarResearchData.model_validate(values)
        self.attempts[completed.research_id] = completed
        if not completed.is_forced:
            self.cached = completed
        return completed

    def fail_research(
        self, *, research_id: UUID, finished_at: datetime, error_code: str
    ) -> TailRadarResearchData:
        running = self.attempts[research_id]
        values = running.model_dump(mode="python")
        values.update(
            status=TailRadarResearchStatus.FAILED,
            error_code=error_code,
            actual_finished_at=finished_at,
            updated_at=finished_at,
        )
        failed = TailRadarResearchData.model_validate(values)
        self.attempts[research_id] = failed
        if not failed.is_forced:
            self.cached = failed
        return failed


def service(repository: FakeRepository, provider: FakeProvider) -> TailRadarResearchService:
    return TailRadarResearchService(
        repository=cast(TailRadarRepository, repository),
        provider=cast(TailRadarResearchProvider, provider),
        clock=lambda: NOW,
    )


def test_research_is_cached_and_only_force_repeats_the_paid_provider_call() -> None:
    repository = FakeRepository()
    provider = FakeProvider(structured_output())
    research = service(repository, provider)

    first = research.execute(candidate_id=CANDIDATE_ID, analysis_as_of=ANALYSIS_AS_OF)
    cached = research.execute(candidate_id=CANDIDATE_ID, analysis_as_of=ANALYSIS_AS_OF)
    forced = research.execute(
        candidate_id=CANDIDATE_ID,
        analysis_as_of=ANALYSIS_AS_OF,
        force=True,
    )

    assert first.research.status is TailRadarResearchStatus.SUCCEEDED
    assert cached.research.research_id == first.research.research_id
    assert forced.research.is_forced is True
    assert forced.research.base_research_id == first.research.research_id
    assert provider.calls == 2
    assert repository.point_in_time_intraday_queries == [ANALYSIS_AS_OF] * 3
    assert "published after analysis_as_of" in provider.requests[0].instructions
    assert (
        first.research.sources[0].publication_timestamp_status
        is PublicationTimestampStatus.VERIFIED
    )


def test_post_as_of_source_fails_only_this_candidate_attempt_and_is_then_cached() -> None:
    repository = FakeRepository()
    provider = FakeProvider(structured_output(published_at=ANALYSIS_AS_OF + timedelta(minutes=1)))
    research = service(repository, provider)

    with pytest.raises(ResearchProviderInvalidResponseError, match="point-in-time"):
        research.execute(candidate_id=CANDIDATE_ID, analysis_as_of=ANALYSIS_AS_OF)

    cached = research.execute(candidate_id=CANDIDATE_ID, analysis_as_of=ANALYSIS_AS_OF)
    assert cached.research.status is TailRadarResearchStatus.FAILED
    assert cached.research.error_code == "research_provider_invalid_response"
    assert provider.calls == 1


def test_no_web_sources_persists_explicit_insufficient_evidence_without_fabrication() -> None:
    repository = FakeRepository()
    provider = FakeProvider(structured_output(include_evidence=False), include_source=False)

    result = service(repository, provider).execute(
        candidate_id=CANDIDATE_ID,
        analysis_as_of=ANALYSIS_AS_OF,
    )

    assert result.research.status is TailRadarResearchStatus.NO_EVIDENCE
    assert result.research.payload is not None
    assert result.research.payload.evidence_quality is ResearchEvidenceQuality.INSUFFICIENT
    assert result.research.payload.confidence == 0
    assert result.research.payload.verified_facts == ()
    assert result.research.sources == ()


@pytest.mark.parametrize(
    "invalid_as_of",
    [
        ANALYSIS_AS_OF.replace(tzinfo=None),
        NOW + timedelta(seconds=1),
        CANDIDATE_AS_OF - timedelta(microseconds=1),
    ],
)
def test_research_rejects_invalid_point_in_time_boundaries_before_any_paid_call(
    invalid_as_of: datetime,
) -> None:
    repository = FakeRepository()
    provider = FakeProvider(structured_output())

    with pytest.raises(TailRadarResearchTimeError):
        service(repository, provider).execute(
            candidate_id=CANDIDATE_ID,
            analysis_as_of=invalid_as_of,
        )

    assert provider.calls == 0
    assert repository.point_in_time_intraday_queries == []
