# ADR 0013: Authenticated on-demand Tail Radar research

- Status: Superseded by ADR 0014
- Date: 2026-09-02
- Supersedes: the batch-AI portions of ADR 0011 and ADR 0012

## Context

The official 14:30 workflow previously attempted AI web research for every candidate. Candidate
counts vary with the market, so opening the system for the first time could create an unpredictable
number of paid model and web-search calls. The public static frontend must remain unable to trigger
anonymous expensive operations, while a local operator needs a deliberate way to research one
selected candidate after reviewing deterministic evidence.

The overview also needs a reliable board filter. The normalized snapshot identifies symbols and
exchanges but does not contain a trustworthy industry classification. An industry label must not be
invented from a company name or model output.

## Decision

Version `tail-radar-workflow-v2` performs the official snapshot, quality validation, deterministic
screening, candidate persistence, and point-in-time intraday analysis only. It leaves each AI stage
`pending`. Pending AI work does not make the deterministic workflow partial or failed. Resume never
starts batch AI research, and the worker never makes an OpenAI call.

Add one authenticated internal operation:

```text
POST /api/internal/v1/tail-radar/candidates/{candidate_id}/research
```

The endpoint is useful only when the backend-only feature flag, OpenAI key, and high-entropy
operations token are configured. It requires a Bearer token and a literal confirmation in the body.
The server derives `analysis_as_of` from the candidate's workflow; the browser cannot move the
historical boundary. One request can address only one candidate. A failed attempt requires a
separate retry confirmation, and a successful/no-evidence artifact is returned from the existing
cache without entering provider code again.

The public API remains read-only. It exposes only a non-secret availability description. The UI
keeps the operations token in component memory, never in a `VITE_*` variable, URL, log, or browser
storage. Compose injects the OpenAI key and operations token only into the backend API container;
the scheduler worker and migration container do not receive them. Merely loading an overview or
candidate detail performs GET requests only.

Derive a provider-independent `AShareBoard` from stable A-share symbol families and the normalized
exchange: Shanghai main board, Shenzhen main board, ChiNext, STAR Market, and Beijing Stock
Exchange. Return null for an unrecognized family. This supports an honest “上市板块” filter; it is
not an industry-sector classification. Industry filtering remains deferred until a normalized
security-master capability supplies authoritative classifications.

## Consequences

The cost of initial capture is independent of candidate count because it makes zero OpenAI calls.
Each paid call is visible, single-candidate, confirmed, authenticated, idempotently claimed, and
failure-isolated. The static public site still cannot anonymously spend money. Operators must
protect a second backend credential in addition to the OpenAI key.

Historical workflow-v1 and research artifacts remain immutable. Workflow v2 may report success
while its AI counts are pending because AI is now an optional follow-up, not a completion gate.
