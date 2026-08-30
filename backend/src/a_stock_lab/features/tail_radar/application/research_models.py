from datetime import date
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from a_stock_lab.core.time import as_market_timezone
from a_stock_lab.features.tail_radar.domain.research import (
    TAIL_RADAR_RESEARCH_PROMPT_VERSION,
    TAIL_RADAR_RESEARCH_SCHEMA_VERSION,
    PublicationTimestampStatus,
    ResearchClaimClassification,
    ResearchEvidenceQuality,
    SourceAvailabilityAtAsOf,
    TailRadarResearchContent,
    TailRadarResearchProviderOutput,
    canonical_source_url,
    source_availability_at_as_of,
)

TAIL_RADAR_RESEARCH_ARTIFACT_TYPE = "tail_radar.web_research"


class TailRadarResearchStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    NO_EVIDENCE = "no_evidence"
    FAILED = "failed"


class TailRadarResearchDisposition(StrEnum):
    CREATED = "created"
    FORCED_CREATED = "forced_created"
    CACHED = "cached"


class ResearchTokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def total_is_not_smaller_than_parts(self) -> "ResearchTokenUsage":
        if self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("total token usage cannot be smaller than input plus output")
        return self


class ResearchProviderRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_as_of: AwareDatetime
    prompt_version: str = TAIL_RADAR_RESEARCH_PROMPT_VERSION
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    instructions: str = Field(min_length=1)
    input_text: str = Field(min_length=1)

    @field_validator("analysis_as_of")
    @classmethod
    def normalize_as_of(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)


class ResearchProviderSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: AnyHttpUrl
    title: str | None = Field(default=None, max_length=512)
    retrieved_at: AwareDatetime

    @field_validator("retrieved_at")
    @classmethod
    def normalize_retrieved_at(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)


class ResearchProviderResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1, max_length=128)
    requested_model: str = Field(min_length=1, max_length=128)
    actual_model: str = Field(min_length=1, max_length=128)
    response_id: str = Field(min_length=1, max_length=255)
    retrieved_at: AwareDatetime
    output: TailRadarResearchProviderOutput
    sources: tuple[ResearchProviderSource, ...]
    token_usage: ResearchTokenUsage
    warnings: tuple[str, ...] = ()
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("retrieved_at")
    @classmethod
    def normalize_retrieved_at(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)

    @model_validator(mode="after")
    def sources_are_unique_and_not_from_the_future(self) -> "ResearchProviderResult":
        canonical_urls = [canonical_source_url(str(source.url)) for source in self.sources]
        if len(set(canonical_urls)) != len(canonical_urls):
            raise ValueError("research provider sources must have unique URLs")
        if any(source.retrieved_at > self.retrieved_at for source in self.sources):
            raise ValueError("research source retrieval cannot follow the provider result")
        return self


class TailRadarResearchSourceCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: UUID
    research_id: UUID
    url: AnyHttpUrl
    title: str | None = Field(default=None, max_length=512)
    publisher_domain: str = Field(min_length=1, max_length=253)
    published_at: AwareDatetime | None = None
    publication_timestamp_status: PublicationTimestampStatus
    availability_at_as_of: SourceAvailabilityAtAsOf
    retrieved_at: AwareDatetime
    relationship_claim_ids: tuple[str, ...] = ()

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def normalize_timestamps(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @field_validator("relationship_claim_ids")
    @classmethod
    def relationship_claim_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source relationship claim IDs must be unique")
        return value

    @model_validator(mode="after")
    def publication_metadata_is_coherent(self) -> "TailRadarResearchSourceCreate":
        hostname = urlsplit(str(self.url)).hostname
        if hostname is None or hostname.lower() != self.publisher_domain.lower():
            raise ValueError("source publisher domain must be derived from its URL")
        if (
            self.publication_timestamp_status is PublicationTimestampStatus.VERIFIED
            and self.published_at is None
        ):
            raise ValueError("verified publication metadata requires published_at")
        if (
            self.publication_timestamp_status is PublicationTimestampStatus.UNAVAILABLE
            and self.published_at is not None
        ):
            raise ValueError("unavailable publication metadata cannot include published_at")
        if self.published_at is not None and self.published_at > self.retrieved_at:
            raise ValueError("source publication timestamp cannot follow retrieval")
        if (
            self.publication_timestamp_status is PublicationTimestampStatus.VERIFIED
        ) != (
            self.availability_at_as_of
            in {SourceAvailabilityAtAsOf.AVAILABLE, SourceAvailabilityAtAsOf.PUBLISHED_AFTER}
        ):
            raise ValueError("source availability requires coherent publication verification")
        return self


class TailRadarResearchSourceData(TailRadarResearchSourceCreate):
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)


class TailRadarResearchSourceReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: UUID
    url: AnyHttpUrl
    publication_timestamp_status: PublicationTimestampStatus
    availability_at_as_of: SourceAvailabilityAtAsOf
    relationship_claim_ids: tuple[str, ...]

    @field_validator("relationship_claim_ids")
    @classmethod
    def relationship_claim_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source-reference claim IDs must be unique")
        return value


def _source_matches_reference(
    source: TailRadarResearchSourceCreate,
    reference: TailRadarResearchSourceReference,
) -> bool:
    return (
        canonical_source_url(str(source.url)) == canonical_source_url(str(reference.url))
        and source.publication_timestamp_status is reference.publication_timestamp_status
        and source.availability_at_as_of is reference.availability_at_as_of
        and set(source.relationship_claim_ids) == set(reference.relationship_claim_ids)
    )


class TailRadarResearchPayload(TailRadarResearchContent):
    symbol: str = Field(pattern=r"^\d{6}$")
    candidate_id: UUID
    source_run_id: UUID
    source_snapshot_id: UUID
    source_candidate_as_of: AwareDatetime
    analysis_as_of: AwareDatetime
    provider: str = Field(min_length=1, max_length=128)
    requested_model: str = Field(min_length=1, max_length=128)
    model_identifier: str = Field(min_length=1, max_length=128)
    provider_response_id: str = Field(min_length=1, max_length=255)
    prompt_version: str = TAIL_RADAR_RESEARCH_PROMPT_VERSION
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: int = TAIL_RADAR_RESEARCH_SCHEMA_VERSION
    source_references: tuple[TailRadarResearchSourceReference, ...]
    token_usage: ResearchTokenUsage
    provider_warnings: tuple[str, ...] = ()
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("source_candidate_as_of", "analysis_as_of")
    @classmethod
    def normalize_timestamps(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)

    @model_validator(mode="after")
    def validate_payload_provenance(self) -> "TailRadarResearchPayload":
        if self.prompt_version != TAIL_RADAR_RESEARCH_PROMPT_VERSION:
            raise ValueError("unsupported Tail Radar research prompt version")
        if self.schema_version != TAIL_RADAR_RESEARCH_SCHEMA_VERSION:
            raise ValueError("unsupported Tail Radar research schema version")
        if self.source_candidate_as_of > self.analysis_as_of:
            raise ValueError("research analysis cannot precede candidate evidence")
        source_ids = {source.source_id for source in self.source_references}
        if len(source_ids) != len(self.source_references):
            raise ValueError("research source references must be unique")
        canonical_urls = {
            canonical_source_url(str(source.url)) for source in self.source_references
        }
        if len(canonical_urls) != len(self.source_references):
            raise ValueError("research source-reference URLs must be unique")
        claim_source_ids = {
            source_id for claim in self.all_claims() for source_id in claim.source_ids
        }
        if not claim_source_ids.issubset(source_ids):
            raise ValueError("research claims reference unknown persisted sources")
        claim_ids = {claim.claim_id for claim in self.all_claims()}
        expected_relationships: dict[UUID, set[str]] = {
            source.source_id: set() for source in self.source_references
        }
        for claim in self.all_claims():
            for source_id in claim.source_ids:
                expected_relationships[source_id].add(claim.claim_id)
        for source in self.source_references:
            relationships = set(source.relationship_claim_ids)
            if not relationships.issubset(claim_ids):
                raise ValueError("research sources reference unknown persisted claims")
            if relationships != expected_relationships[source.source_id]:
                raise ValueError(
                    "research claim/source relationships must agree in both directions"
                )
        return self


def _validate_terminal_payload(
    *, status: TailRadarResearchStatus, payload: TailRadarResearchPayload
) -> None:
    substantive_claims = tuple(
        claim
        for claim in payload.all_claims()
        if claim.classification is not ResearchClaimClassification.INSUFFICIENT_EVIDENCE
    )
    if status is TailRadarResearchStatus.SUCCEEDED and not substantive_claims:
        raise ValueError("successful research requires at least one substantive claim")
    if status is TailRadarResearchStatus.NO_EVIDENCE and (
        substantive_claims
        or payload.evidence_quality is not ResearchEvidenceQuality.INSUFFICIENT
        or payload.confidence != 0
    ):
        raise ValueError("no-evidence research must preserve explicit insufficient evidence")


class TailRadarResearchClaimRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    research_id: UUID
    candidate_id: UUID
    run_id: UUID
    snapshot_id: UUID
    symbol: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    analysis_as_of: AwareDatetime
    prompt_version: str = TAIL_RADAR_RESEARCH_PROMPT_VERSION
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1, max_length=128)
    requested_model: str = Field(min_length=1, max_length=128)
    started_at: AwareDatetime
    force: bool = False

    @field_validator("analysis_as_of", "started_at")
    @classmethod
    def normalize_timestamps(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)


class TailRadarResearchCompletion(BaseModel):
    model_config = ConfigDict(frozen=True)

    research_id: UUID
    artifact_id: UUID
    status: TailRadarResearchStatus
    payload: TailRadarResearchPayload
    sources: tuple[TailRadarResearchSourceCreate, ...]
    actual_model: str = Field(min_length=1, max_length=128)
    provider_response_id: str = Field(min_length=1, max_length=255)
    token_usage: ResearchTokenUsage
    finished_at: AwareDatetime

    @field_validator("finished_at")
    @classmethod
    def normalize_finished_at(cls, value: AwareDatetime) -> AwareDatetime:
        return as_market_timezone(value)

    @model_validator(mode="after")
    def completion_is_terminal_and_linked(self) -> "TailRadarResearchCompletion":
        if self.status not in {
            TailRadarResearchStatus.SUCCEEDED,
            TailRadarResearchStatus.NO_EVIDENCE,
        }:
            raise ValueError("research completion must use a successful terminal status")
        if any(source.research_id != self.research_id for source in self.sources):
            raise ValueError("research sources must link to the completed research")
        source_ids = {source.source_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("completed research sources must be unique")
        reference_ids = {source.source_id for source in self.payload.source_references}
        if source_ids != reference_ids:
            raise ValueError("completed research sources must match payload references")
        references = {source.source_id: source for source in self.payload.source_references}
        if any(
            not _source_matches_reference(source, references[source.source_id])
            for source in self.sources
        ):
            raise ValueError("completed research source metadata must match payload references")
        if self.token_usage != self.payload.token_usage:
            raise ValueError("completed research token usage must match its payload")
        if any(source.retrieved_at > self.finished_at for source in self.sources):
            raise ValueError("research source retrieval cannot follow completion")
        for source in self.sources:
            expected_availability = source_availability_at_as_of(
                published_at=source.published_at,
                publication_status=source.publication_timestamp_status,
                analysis_as_of=self.payload.analysis_as_of,
            )
            if source.availability_at_as_of is not expected_availability:
                raise ValueError("research source availability disagrees with analysis_as_of")
        _validate_terminal_payload(status=self.status, payload=self.payload)
        return self


class TailRadarResearchData(BaseModel):
    model_config = ConfigDict(frozen=True)

    research_id: UUID
    artifact_id: UUID | None
    candidate_id: UUID
    run_id: UUID
    snapshot_id: UUID
    symbol: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    analysis_as_of: AwareDatetime
    prompt_version: str
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    requested_model: str
    actual_model: str | None
    provider_response_id: str | None
    status: TailRadarResearchStatus
    is_forced: bool
    base_research_id: UUID | None
    token_usage: ResearchTokenUsage
    error_code: str | None
    actual_started_at: AwareDatetime
    actual_finished_at: AwareDatetime | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    payload: TailRadarResearchPayload | None
    sources: tuple[TailRadarResearchSourceData, ...]

    @field_validator(
        "analysis_as_of",
        "actual_started_at",
        "actual_finished_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def normalize_timestamps(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        return None if value is None else as_market_timezone(value)

    @model_validator(mode="after")
    def terminal_state_matches_artifact(self) -> "TailRadarResearchData":
        successful = self.status in {
            TailRadarResearchStatus.SUCCEEDED,
            TailRadarResearchStatus.NO_EVIDENCE,
        }
        if successful != (self.artifact_id is not None and self.payload is not None):
            raise ValueError("research terminal status must agree with its artifact")
        if self.status is TailRadarResearchStatus.RUNNING and self.actual_finished_at is not None:
            raise ValueError("running research cannot have a finish timestamp")
        if self.status is not TailRadarResearchStatus.RUNNING and self.actual_finished_at is None:
            raise ValueError("terminal research requires a finish timestamp")
        if self.status is TailRadarResearchStatus.FAILED and not self.error_code:
            raise ValueError("failed research requires an error code")
        if successful and self.error_code is not None:
            raise ValueError("successful research cannot have an error code")
        if self.payload is not None and self.payload.analysis_as_of != self.analysis_as_of:
            raise ValueError("research payload as_of is inconsistent")
        if self.actual_finished_at is not None and self.actual_finished_at < self.actual_started_at:
            raise ValueError("research completion cannot precede its start")
        if not self.is_forced and self.base_research_id is not None:
            raise ValueError("ordinary research cannot have forced-attempt lineage")
        if self.base_research_id == self.research_id:
            raise ValueError("research attempt cannot reference itself as its base")
        if self.payload is not None:
            _validate_terminal_payload(status=self.status, payload=self.payload)
            if self.payload.token_usage != self.token_usage:
                raise ValueError("research payload token usage is inconsistent")
            source_by_id = {source.source_id: source for source in self.sources}
            if len(source_by_id) != len(self.sources):
                raise ValueError("stored research sources must be unique")
            references = {source.source_id: source for source in self.payload.source_references}
            if set(source_by_id) != set(references):
                raise ValueError("stored research sources do not match payload references")
            for source_id, source in source_by_id.items():
                reference = references[source_id]
                if source.research_id != self.research_id:
                    raise ValueError("stored research source belongs to another analysis")
                if self.actual_finished_at is None or source.retrieved_at > self.actual_finished_at:
                    raise ValueError("stored research source has invalid retrieval timing")
                if not _source_matches_reference(source, reference):
                    raise ValueError("stored research source metadata is inconsistent")
        return self


class TailRadarResearchClaimResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    research: TailRadarResearchData
    created: bool


class TailRadarResearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    disposition: TailRadarResearchDisposition
    research: TailRadarResearchData
