from collections.abc import Callable, Iterable
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from a_stock_lab.core.time import as_market_timezone, now_in_market_timezone
from a_stock_lab.features.tail_radar.application.contracts import (
    TailRadarRepository,
    TailRadarResearchProvider,
)
from a_stock_lab.features.tail_radar.application.models import TailRadarCandidateData
from a_stock_lab.features.tail_radar.application.research_models import (
    ResearchProviderResult,
    TailRadarResearchClaimRequest,
    TailRadarResearchCompletion,
    TailRadarResearchDisposition,
    TailRadarResearchPayload,
    TailRadarResearchResult,
    TailRadarResearchSourceCreate,
    TailRadarResearchSourceReference,
    TailRadarResearchStatus,
)
from a_stock_lab.features.tail_radar.application.research_prompt import (
    build_research_provider_request,
)
from a_stock_lab.features.tail_radar.domain.errors import (
    ResearchProviderError,
    ResearchProviderInvalidResponseError,
    TailRadarCandidateNotFoundError,
    TailRadarResearchTimeError,
)
from a_stock_lab.features.tail_radar.domain.research import (
    ProviderResearchClaim,
    PublicationTimestampStatus,
    ResearchClaimClassification,
    ResearchEvidenceQuality,
    SourceAvailabilityAtAsOf,
    TailRadarResearchClaim,
    TailRadarResearchContent,
    TailRadarResearchProviderOutput,
    canonical_source_url,
    source_availability_at_as_of,
)


class TailRadarResearchService:
    """Orchestrate one cached AI interpretation without changing deterministic signals."""

    def __init__(
        self,
        *,
        provider: TailRadarResearchProvider,
        repository: TailRadarRepository,
        clock: Callable[[], datetime] = now_in_market_timezone,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        *,
        candidate_id: UUID,
        analysis_as_of: datetime,
        force: bool = False,
    ) -> TailRadarResearchResult:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise TailRadarCandidateNotFoundError("Tail Radar candidate was not found")
        try:
            as_of = as_market_timezone(analysis_as_of)
        except ValueError as exc:
            raise TailRadarResearchTimeError(
                "analysis_as_of must include an explicit UTC offset"
            ) from exc
        started_at = as_market_timezone(self._clock())
        if as_of > started_at:
            raise TailRadarResearchTimeError("analysis_as_of cannot be in the future")
        if as_of < candidate.as_of:
            raise TailRadarResearchTimeError(
                "analysis_as_of cannot precede candidate snapshot evidence"
            )
        intraday = self._repository.get_intraday_analysis_at_or_before(
            candidate_id=candidate_id,
            analysis_as_of=as_of,
        )
        provider_request = build_research_provider_request(
            analysis_as_of=as_of,
            evidence={
                "candidate": candidate.model_dump(mode="json"),
                "deterministic_intraday_analysis": (
                    None if intraday is None else intraday.model_dump(mode="json")
                ),
            },
        )
        claim = self._repository.claim_research(
            TailRadarResearchClaimRequest(
                research_id=uuid4(),
                candidate_id=candidate.candidate_id,
                run_id=candidate.run_id,
                snapshot_id=candidate.snapshot_id,
                symbol=candidate.symbol,
                trade_date=candidate.trade_date,
                analysis_as_of=as_of,
                prompt_sha256=provider_request.prompt_sha256,
                provider=self._provider.provider_id,
                requested_model=self._provider.model_id,
                started_at=started_at,
                force=force,
            )
        )
        if not claim.created:
            return TailRadarResearchResult(
                disposition=TailRadarResearchDisposition.CACHED,
                research=claim.research,
            )

        try:
            provider_result = self._provider.research(provider_request)
            completion = _build_completion(
                research_id=claim.research.research_id,
                candidate=candidate,
                analysis_as_of=as_of,
                prompt_sha256=provider_request.prompt_sha256,
                expected_provider=self._provider.provider_id,
                expected_model=self._provider.model_id,
                provider_result=provider_result,
                finished_at=as_market_timezone(self._clock()),
            )
        except ResearchProviderError as exc:
            self._repository.fail_research(
                research_id=claim.research.research_id,
                finished_at=as_market_timezone(self._clock()),
                error_code=exc.code,
            )
            raise
        except ValueError as exc:
            error = ResearchProviderInvalidResponseError(
                "research provider output violated point-in-time integrity"
            )
            self._repository.fail_research(
                research_id=claim.research.research_id,
                finished_at=as_market_timezone(self._clock()),
                error_code=error.code,
            )
            raise error from exc

        completed = self._repository.complete_research(completion)
        return TailRadarResearchResult(
            disposition=(
                TailRadarResearchDisposition.FORCED_CREATED
                if force
                else TailRadarResearchDisposition.CREATED
            ),
            research=completed,
        )


def _build_completion(
    *,
    research_id: UUID,
    candidate: TailRadarCandidateData,
    analysis_as_of: datetime,
    prompt_sha256: str,
    expected_provider: str,
    expected_model: str,
    provider_result: ResearchProviderResult,
    finished_at: datetime,
) -> TailRadarResearchCompletion:
    if provider_result.provider != expected_provider:
        raise ValueError("research provider identity changed during the request")
    if provider_result.requested_model != expected_model:
        raise ValueError("research provider model changed during the request")
    if provider_result.retrieved_at > finished_at:
        raise ValueError("research retrieval timestamp cannot follow completion")

    source_creates, source_id_by_url = _build_sources(
        research_id=research_id,
        analysis_as_of=analysis_as_of,
        provider_result=provider_result,
    )
    content = _build_content(
        output=provider_result.output,
        sources=source_creates,
        source_id_by_url=source_id_by_url,
    )
    useful = any(
        claim.classification is not ResearchClaimClassification.INSUFFICIENT_EVIDENCE
        and claim.source_ids
        for claim in content.all_claims()
    )
    if not useful:
        content = TailRadarResearchContent(
            concise_summary=(
                "No useful web evidence could be verified for this candidate at the requested "
                "analysis_as_of."
            ),
            verified_facts=(),
            likely_drivers=(),
            company_context=(),
            sector_context=(),
            market_context=(),
            positive_factors=(),
            risk_factors=(),
            unresolved_questions=("No source with usable point-in-time evidence was found.",),
            evidence_quality=ResearchEvidenceQuality.INSUFFICIENT,
            confidence=0,
        )
    source_references = tuple(
        TailRadarResearchSourceReference(
            source_id=source.source_id,
            url=source.url,
            publication_timestamp_status=source.publication_timestamp_status,
            availability_at_as_of=source.availability_at_as_of,
            relationship_claim_ids=source.relationship_claim_ids,
        )
        for source in source_creates
    )
    payload = TailRadarResearchPayload(
        **content.model_dump(mode="python"),
        symbol=candidate.symbol,
        candidate_id=candidate.candidate_id,
        source_run_id=candidate.run_id,
        source_snapshot_id=candidate.snapshot_id,
        source_candidate_as_of=candidate.as_of,
        analysis_as_of=analysis_as_of,
        provider=provider_result.provider,
        requested_model=provider_result.requested_model,
        model_identifier=provider_result.actual_model,
        provider_response_id=provider_result.response_id,
        prompt_sha256=prompt_sha256,
        source_references=source_references,
        token_usage=provider_result.token_usage,
        provider_warnings=provider_result.warnings,
        provider_metadata=provider_result.provider_metadata,
    )
    return TailRadarResearchCompletion(
        research_id=research_id,
        artifact_id=uuid4(),
        status=(
            TailRadarResearchStatus.SUCCEEDED if useful else TailRadarResearchStatus.NO_EVIDENCE
        ),
        payload=payload,
        sources=source_creates,
        actual_model=provider_result.actual_model,
        provider_response_id=provider_result.response_id,
        token_usage=provider_result.token_usage,
        finished_at=finished_at,
    )


def _build_sources(
    *,
    research_id: UUID,
    analysis_as_of: datetime,
    provider_result: ResearchProviderResult,
) -> tuple[tuple[TailRadarResearchSourceCreate, ...], dict[str, UUID]]:
    provider_sources = {
        canonical_source_url(str(source.url)): source for source in provider_result.sources
    }
    assessments = {
        canonical_source_url(str(assessment.url)): assessment
        for assessment in provider_result.output.source_assessments
    }
    if not set(assessments).issubset(provider_sources):
        raise ValueError("model output referenced a URL absent from web-search evidence")
    claim_relationships: dict[str, set[str]] = {}
    for claim in provider_result.output.all_claims():
        for url in claim.source_urls:
            key = canonical_source_url(str(url))
            if key not in provider_sources:
                raise ValueError("research claim cited a URL absent from web-search evidence")
            claim_relationships.setdefault(key, set()).add(claim.claim_id)

    source_creates: list[TailRadarResearchSourceCreate] = []
    source_ids: dict[str, UUID] = {}
    for key, source in provider_sources.items():
        assessment = assessments.get(key)
        relationships = tuple(sorted(claim_relationships.get(key, set())))
        if assessment is None:
            published_at = None
            timestamp_status = PublicationTimestampStatus.UNAVAILABLE
        else:
            if set(assessment.relationship_claim_ids) != set(relationships):
                raise ValueError("source relationship metadata disagrees with cited claims")
            published_at = assessment.published_at
            timestamp_status = assessment.publication_timestamp_status
        if published_at is not None and published_at > source.retrieved_at:
            raise ValueError("verified source publication timestamp follows retrieval")
        availability = source_availability_at_as_of(
            published_at=published_at,
            publication_status=timestamp_status,
            analysis_as_of=analysis_as_of,
        )
        hostname = urlsplit(str(source.url)).hostname
        if hostname is None:
            raise ValueError("research source URL has no publisher domain")
        source_id = uuid4()
        source_ids[key] = source_id
        source_creates.append(
            TailRadarResearchSourceCreate(
                source_id=source_id,
                research_id=research_id,
                url=source.url,
                title=source.title,
                publisher_domain=hostname.lower(),
                published_at=published_at,
                publication_timestamp_status=timestamp_status,
                availability_at_as_of=availability,
                retrieved_at=source.retrieved_at,
                relationship_claim_ids=relationships,
            )
        )
    return tuple(source_creates), source_ids


def _build_content(
    *,
    output: TailRadarResearchProviderOutput,
    sources: tuple[TailRadarResearchSourceCreate, ...],
    source_id_by_url: dict[str, UUID],
) -> TailRadarResearchContent:
    source_by_id = {source.source_id: source for source in sources}

    def convert(claims: Iterable[ProviderResearchClaim]) -> tuple[TailRadarResearchClaim, ...]:
        converted: list[TailRadarResearchClaim] = []
        for claim in claims:
            source_ids = tuple(
                source_id_by_url[canonical_source_url(str(url))] for url in claim.source_urls
            )
            if (
                claim.classification is not ResearchClaimClassification.INSUFFICIENT_EVIDENCE
                and not source_ids
            ):
                raise ValueError("substantive research claims require web-search evidence")
            if (
                any(
                    source_by_id[source_id].availability_at_as_of
                    is SourceAvailabilityAtAsOf.PUBLISHED_AFTER
                    for source_id in source_ids
                )
                and claim.classification is not ResearchClaimClassification.INSUFFICIENT_EVIDENCE
            ):
                raise ValueError("post-as_of sources cannot support contemporaneous claims")
            if claim.classification is ResearchClaimClassification.VERIFIED_FACT and not any(
                source_by_id[source_id].availability_at_as_of is SourceAvailabilityAtAsOf.AVAILABLE
                and source_by_id[source_id].publication_timestamp_status
                is PublicationTimestampStatus.VERIFIED
                for source_id in source_ids
            ):
                raise ValueError("verified facts require verified pre-as_of publication evidence")
            converted.append(
                TailRadarResearchClaim(
                    claim_id=claim.claim_id,
                    statement=claim.statement,
                    classification=claim.classification,
                    source_ids=source_ids,
                )
            )
        return tuple(converted)

    return TailRadarResearchContent(
        concise_summary=output.concise_summary,
        verified_facts=convert(output.verified_facts),
        likely_drivers=convert(output.likely_drivers),
        company_context=convert(output.company_context),
        sector_context=convert(output.sector_context),
        market_context=convert(output.market_context),
        positive_factors=convert(output.positive_factors),
        risk_factors=convert(output.risk_factors),
        unresolved_questions=output.unresolved_questions,
        evidence_quality=output.evidence_quality,
        confidence=output.confidence,
    )
