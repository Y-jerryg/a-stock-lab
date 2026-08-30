from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from a_stock_lab.core.time import as_market_timezone

TAIL_RADAR_RESEARCH_PROMPT_VERSION = "tail-radar-research-v1"
TAIL_RADAR_RESEARCH_SCHEMA_VERSION = 1


def canonical_source_url(value: str) -> str:
    """Normalize only comparison-safe URL components without inventing or dropping query data."""
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    netloc = hostname
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


class ResearchClaimClassification(StrEnum):
    VERIFIED_FACT = "verified_fact"
    INTERPRETATION = "interpretation"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ResearchEvidenceQuality(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class PublicationTimestampStatus(StrEnum):
    VERIFIED = "verified"
    UNCERTAIN = "uncertain"
    UNAVAILABLE = "unavailable"


class SourceAvailabilityAtAsOf(StrEnum):
    AVAILABLE = "available_at_as_of"
    PUBLISHED_AFTER = "published_after_as_of"
    UNCERTAIN = "uncertain_at_as_of"


def source_availability_at_as_of(
    *,
    published_at: AwareDatetime | None,
    publication_status: PublicationTimestampStatus,
    analysis_as_of: AwareDatetime,
) -> SourceAvailabilityAtAsOf:
    """Classify source availability without promoting uncertain publication metadata."""
    if publication_status is not PublicationTimestampStatus.VERIFIED or published_at is None:
        return SourceAvailabilityAtAsOf.UNCERTAIN
    return (
        SourceAvailabilityAtAsOf.AVAILABLE
        if published_at <= analysis_as_of
        else SourceAvailabilityAtAsOf.PUBLISHED_AFTER
    )


class ProviderResearchClaim(BaseModel):
    """One model-produced claim before URL references become persisted source IDs."""

    model_config = ConfigDict(frozen=True)

    claim_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    statement: str = Field(min_length=1, max_length=2_000)
    classification: ResearchClaimClassification
    source_urls: tuple[AnyHttpUrl, ...] = ()

    @field_validator("source_urls")
    @classmethod
    def source_urls_are_unique(cls, value: tuple[AnyHttpUrl, ...]) -> tuple[AnyHttpUrl, ...]:
        if len({canonical_source_url(str(url)) for url in value}) != len(value):
            raise ValueError("research claim source URLs must be unique")
        return value


class ProviderSourceAssessment(BaseModel):
    """Publication-time assessment produced while the model can inspect the source page."""

    model_config = ConfigDict(frozen=True)

    url: AnyHttpUrl
    published_at: AwareDatetime | None = None
    publication_timestamp_status: PublicationTimestampStatus
    relationship_claim_ids: tuple[str, ...] = ()

    @field_validator("published_at")
    @classmethod
    def normalize_published_at(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @field_validator("relationship_claim_ids")
    @classmethod
    def relationship_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source relationship claim IDs must be unique")
        return value

    @model_validator(mode="after")
    def timestamp_matches_verification_status(self) -> "ProviderSourceAssessment":
        if (
            self.publication_timestamp_status is PublicationTimestampStatus.VERIFIED
            and self.published_at is None
        ):
            raise ValueError("a verified publication timestamp requires published_at")
        if (
            self.publication_timestamp_status is PublicationTimestampStatus.UNAVAILABLE
            and self.published_at is not None
        ):
            raise ValueError("an unavailable publication timestamp cannot include published_at")
        return self


class TailRadarResearchProviderOutput(BaseModel):
    """Strict provider output parsed by the adapter before application validation."""

    model_config = ConfigDict(frozen=True)

    concise_summary: str = Field(min_length=1, max_length=4_000)
    verified_facts: tuple[ProviderResearchClaim, ...]
    likely_drivers: tuple[ProviderResearchClaim, ...]
    company_context: tuple[ProviderResearchClaim, ...]
    sector_context: tuple[ProviderResearchClaim, ...]
    market_context: tuple[ProviderResearchClaim, ...]
    positive_factors: tuple[ProviderResearchClaim, ...]
    risk_factors: tuple[ProviderResearchClaim, ...]
    unresolved_questions: tuple[str, ...]
    evidence_quality: ResearchEvidenceQuality
    confidence: float = Field(ge=0, le=1)
    source_assessments: tuple[ProviderSourceAssessment, ...]

    def all_claims(self) -> tuple[ProviderResearchClaim, ...]:
        return (
            *self.verified_facts,
            *self.likely_drivers,
            *self.company_context,
            *self.sector_context,
            *self.market_context,
            *self.positive_factors,
            *self.risk_factors,
        )

    @field_validator("unresolved_questions")
    @classmethod
    def questions_are_nonempty_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not question.strip() for question in value):
            raise ValueError("unresolved research questions cannot be blank")
        if len(set(value)) != len(value):
            raise ValueError("unresolved research questions must be unique")
        return value

    @model_validator(mode="after")
    def validate_claim_taxonomy_and_source_links(self) -> "TailRadarResearchProviderOutput":
        if any(
            claim.classification is not ResearchClaimClassification.VERIFIED_FACT
            for claim in self.verified_facts
        ):
            raise ValueError("verified_facts may contain only verified_fact claims")
        if any(
            claim.classification is not ResearchClaimClassification.INTERPRETATION
            for claim in self.likely_drivers
        ):
            raise ValueError("likely_drivers may contain only interpretation claims")
        claims = self.all_claims()
        claim_ids = {claim.claim_id for claim in claims}
        if len(claim_ids) != len(claims):
            raise ValueError("research claim IDs must be unique")
        assessment_urls = [
            canonical_source_url(str(assessment.url)) for assessment in self.source_assessments
        ]
        if len(set(assessment_urls)) != len(assessment_urls):
            raise ValueError("source assessments must have unique URLs")
        related_ids = {
            claim_id
            for assessment in self.source_assessments
            for claim_id in assessment.relationship_claim_ids
        }
        if not related_ids.issubset(claim_ids):
            raise ValueError("source assessments reference unknown research claims")
        return self


class TailRadarResearchClaim(BaseModel):
    """Persisted claim whose evidence points to separately stored source rows."""

    model_config = ConfigDict(frozen=True)

    claim_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    statement: str = Field(min_length=1, max_length=2_000)
    classification: ResearchClaimClassification
    source_ids: tuple[UUID, ...] = ()

    @field_validator("source_ids")
    @classmethod
    def source_ids_are_unique(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("research claim source IDs must be unique")
        return value


class TailRadarResearchContent(BaseModel):
    model_config = ConfigDict(frozen=True)

    concise_summary: str = Field(min_length=1, max_length=4_000)
    verified_facts: tuple[TailRadarResearchClaim, ...]
    likely_drivers: tuple[TailRadarResearchClaim, ...]
    company_context: tuple[TailRadarResearchClaim, ...]
    sector_context: tuple[TailRadarResearchClaim, ...]
    market_context: tuple[TailRadarResearchClaim, ...]
    positive_factors: tuple[TailRadarResearchClaim, ...]
    risk_factors: tuple[TailRadarResearchClaim, ...]
    unresolved_questions: tuple[str, ...]
    evidence_quality: ResearchEvidenceQuality
    confidence: float = Field(ge=0, le=1)

    def all_claims(self) -> tuple[TailRadarResearchClaim, ...]:
        return (
            *self.verified_facts,
            *self.likely_drivers,
            *self.company_context,
            *self.sector_context,
            *self.market_context,
            *self.positive_factors,
            *self.risk_factors,
        )

    @model_validator(mode="after")
    def content_taxonomy_remains_valid(self) -> "TailRadarResearchContent":
        if any(
            claim.classification is not ResearchClaimClassification.VERIFIED_FACT
            for claim in self.verified_facts
        ):
            raise ValueError("verified_facts may contain only verified_fact claims")
        if any(
            claim.classification is not ResearchClaimClassification.INTERPRETATION
            for claim in self.likely_drivers
        ):
            raise ValueError("likely_drivers may contain only interpretation claims")
        claims = self.all_claims()
        if len({claim.claim_id for claim in claims}) != len(claims):
            raise ValueError("persisted research claim IDs must be unique")
        if any(not question.strip() for question in self.unresolved_questions):
            raise ValueError("unresolved research questions cannot be blank")
        if len(set(self.unresolved_questions)) != len(self.unresolved_questions):
            raise ValueError("unresolved research questions must be unique")
        return self
