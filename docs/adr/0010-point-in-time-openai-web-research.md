# ADR 0010: Point-in-time OpenAI web research

- Status: Accepted
- Date: 2026-08-30

The CLI-only delivery decision was extended by single-candidate research in
[ADR 0013](0013-authenticated-on-demand-tail-radar-research.md), whose credential policy is now
superseded by [ADR 0014](0014-request-scoped-user-openai-keys.md). Provider and point-in-time
integrity decisions remain in force.

## Context

Tail Radar candidates need evidence-backed company, sector, policy, macro, supply-chain, and market
context. This interpretation is probabilistic and paid, while candidate membership and intraday
features are deterministic. Historical research must not present later-published information as
known at its explicit `analysis_as_of`, and retries must not silently incur repeated charges.

## Decision

Introduce a provider-neutral Tail Radar research contract and application service. Keep the current
official OpenAI Python SDK and all Responses API/web-search details in one backend adapter. Use
Responses structured output validated by Pydantic, disable SDK retries, apply an explicit timeout,
and translate timeout, rate-limit, connection/API, and malformed-output failures into a
provider-neutral hierarchy. There is no frontend SDK or secret and no anonymous execution API.

Version the initial prompt as `tail-radar-research-v1` and persist its SHA-256 hash. The prompt
defines `analysis_as_of` as a hard information cutoff, distinguishes publication from retrieval,
and requests separate verified facts, interpretations, insufficient evidence, and source
assessments. Application validation accepts only URLs observed in the actual web-search response.
A verified fact requires verified publication at or before the boundary. Later-published sources
may be retained for audit but cannot support substantive claims. Uncertain or unavailable
publication times remain explicit and are never promoted to verified historical evidence.

Before an external call, atomically claim one non-forced identity by candidate, Tail Radar run,
`analysis_as_of`, prompt version, provider, and requested model. Replays return the existing attempt,
including running, failed, and no-evidence states. An explicit `--force` operation creates a linked
attempt; it does not overwrite the cached result. This provides at-most-one ordinary paid attempt
under concurrent execution and prevents one provider's result from masking another provider. Reuse
of one prompt version with a different prompt hash is rejected before a paid call. A candidate
failure never changes the source Tail Radar run.

Persist attempt lifecycle and token accounting in `tail_radar_research_analyses`, source metadata
and claim relationships in `tail_radar_research_sources`, and successful/no-evidence structured
content as a versioned `tail_radar.web_research` `ResearchArtifact`. Public candidate detail may
read the latest successful or no-evidence artifact, while execution stays an explicit backend CLI
diagnostic.

Prompt version `tail-radar-research-v2` adds a Simplified Chinese narrative-output requirement for
the Chinese public interface. Source titles, URLs, stock symbols, company names, proper nouns,
model identifiers, structured enum values, and version identifiers keep their authentic form.
Version 1 artifacts remain immutable; the new version intentionally creates a distinct cache
identity so changed instructions cannot reuse or overwrite an earlier paid analysis.

## Consequences

Deterministic signals remain reproducible and independent of AI availability. Research has audited
point-in-time provenance, explicit uncertainty, independently queryable sources, and bounded cost.
Changing the prompt, provider, or model intentionally changes the cache identity. Forced retries
cost money and remain visible. Normal CI uses mocks and never needs internet access or an API key.
Automatic batch orchestration, recurring scheduling, semantic retrieval, and investment
recommendations are deferred.

## References

- [OpenAI Responses API: create a response](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [OpenAI GPT-5.6 Sol model capabilities](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
