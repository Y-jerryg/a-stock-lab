from datetime import datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.application.research_models import (
    ResearchTokenUsage,
    TailRadarResearchCompletion,
    TailRadarResearchPayload,
    TailRadarResearchSourceCreate,
    TailRadarResearchSourceReference,
    TailRadarResearchStatus,
)
from a_stock_lab.features.tail_radar.domain.research import (
    ProviderResearchClaim,
    PublicationTimestampStatus,
    ResearchClaimClassification,
    ResearchEvidenceQuality,
    SourceAvailabilityAtAsOf,
    TailRadarResearchClaim,
    TailRadarResearchContent,
)

ANALYSIS_AS_OF = datetime(2026, 8, 28, 14, 35, tzinfo=MARKET_TIME_ZONE)
SOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")
RESEARCH_ID = UUID("22222222-2222-4222-8222-222222222222")
SOURCE_URL = "https://example.test/announcement"
TOKENS = ResearchTokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)


def research_payload(
    *, relationship_claim_ids: tuple[str, ...] = ("fact_one",)
) -> TailRadarResearchPayload:
    claim = TailRadarResearchClaim(
        claim_id="fact_one",
        statement="A fixture announcement was published before the cutoff.",
        classification=ResearchClaimClassification.VERIFIED_FACT,
        source_ids=(SOURCE_ID,),
    )
    return TailRadarResearchPayload(
        symbol="600000",
        candidate_id=UUID("33333333-3333-4333-8333-333333333333"),
        source_run_id=UUID("44444444-4444-4444-8444-444444444444"),
        source_snapshot_id=UUID("55555555-5555-4555-8555-555555555555"),
        source_candidate_as_of=ANALYSIS_AS_OF - timedelta(minutes=5),
        analysis_as_of=ANALYSIS_AS_OF,
        concise_summary="One verified fixture fact was found.",
        verified_facts=(claim,),
        likely_drivers=(),
        company_context=(),
        sector_context=(),
        market_context=(),
        positive_factors=(),
        risk_factors=(),
        unresolved_questions=(),
        evidence_quality=ResearchEvidenceQuality.HIGH,
        confidence=0.9,
        provider="fixture",
        requested_model="fixture-model",
        model_identifier="fixture-model-snapshot",
        provider_response_id="response_fixture",
        prompt_sha256="a" * 64,
        source_references=(
            TailRadarResearchSourceReference(
                source_id=SOURCE_ID,
                url=SOURCE_URL,
                publication_timestamp_status=PublicationTimestampStatus.VERIFIED,
                availability_at_as_of=SourceAvailabilityAtAsOf.AVAILABLE,
                relationship_claim_ids=relationship_claim_ids,
            ),
        ),
        token_usage=TOKENS,
    )


def source(*, url: str = SOURCE_URL, domain: str = "example.test") -> TailRadarResearchSourceCreate:
    return TailRadarResearchSourceCreate(
        source_id=SOURCE_ID,
        research_id=RESEARCH_ID,
        url=url,
        title="Fixture announcement",
        publisher_domain=domain,
        published_at=ANALYSIS_AS_OF - timedelta(hours=1),
        publication_timestamp_status=PublicationTimestampStatus.VERIFIED,
        availability_at_as_of=SourceAvailabilityAtAsOf.AVAILABLE,
        retrieved_at=ANALYSIS_AS_OF + timedelta(days=1),
        relationship_claim_ids=("fact_one",),
    )


def test_equivalent_source_urls_are_rejected_before_provider_output_is_accepted() -> None:
    with pytest.raises(ValidationError, match="source URLs must be unique"):
        ProviderResearchClaim(
            claim_id="fact_one",
            statement="A fixture fact.",
            classification=ResearchClaimClassification.VERIFIED_FACT,
            source_urls=(
                "https://EXAMPLE.test:443/announcement",
                "https://example.test/announcement",
            ),
        )


def test_persisted_claim_taxonomy_and_bidirectional_source_relationships_are_validated() -> None:
    with pytest.raises(ValidationError, match="verified_facts"):
        TailRadarResearchContent(
            concise_summary="Invalid taxonomy.",
            verified_facts=(
                TailRadarResearchClaim(
                    claim_id="interpretation_one",
                    statement="This is not a verified fact.",
                    classification=ResearchClaimClassification.INTERPRETATION,
                ),
            ),
            likely_drivers=(),
            company_context=(),
            sector_context=(),
            market_context=(),
            positive_factors=(),
            risk_factors=(),
            unresolved_questions=(),
            evidence_quality=ResearchEvidenceQuality.LOW,
            confidence=0.2,
        )

    with pytest.raises(ValidationError, match="both directions"):
        research_payload(relationship_claim_ids=())


def test_completion_rejects_source_metadata_that_disagrees_with_the_artifact() -> None:
    with pytest.raises(ValidationError, match="source metadata"):
        TailRadarResearchCompletion(
            research_id=RESEARCH_ID,
            artifact_id=UUID("66666666-6666-4666-8666-666666666666"),
            status=TailRadarResearchStatus.SUCCEEDED,
            payload=research_payload(),
            sources=(source(url="https://other.test/announcement", domain="other.test"),),
            actual_model="fixture-model-snapshot",
            provider_response_id="response_fixture",
            token_usage=TOKENS,
            finished_at=ANALYSIS_AS_OF + timedelta(days=1),
        )
