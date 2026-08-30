# Tail Radar deterministic screening and intraday features

Phase 3 implements the first real Tail Radar rule. It screens one already-persisted, successful
official full-market snapshot. It never monitors later quotes to add securities that were not in
range in that snapshot.

## Version-one rule

`TailRadarScreeningRule` version `tail-radar-screen-v1` consumes only normalized
`MarketSnapshotRecord` values. A record is included exactly when:

```text
2.00 <= pct_change <= 3.00
```

The boundaries are inclusive: `1.99` and `3.01` are excluded; `2.00`, `2.50`, and `3.00` are
included. The percentage uses percentage points, matching the normalized market-data contract.

Before range evaluation, the record must have a six-digit symbol, finite percentage change,
positive finite current price, and registered snapshot evidence. Invalid records are counted but
never become candidates. Version one does not exclude ST names and does not apply amount,
float-market-cap, exchange, or board filters. Typed configuration contains disabled slots for these
future filters and rejects attempts to enable them under the version-one identifier.

## Evidence and persistence

Execution accepts a snapshot UUID, verifies that it belongs to a successful official snapshot run,
checks the Parquet SHA-256 checksum, decodes the embedded manifest, and confirms it agrees with the
PostgreSQL manifest. It then evaluates the immutable records once.

PostgreSQL stores:

- the shared execution lifecycle in `execution_runs`;
- the selected snapshot, rule version, exact configuration, and finalized counts in
  `tail_radar_runs`;
- a relational candidate link in `tail_radar_candidates`; and
- each candidate's versioned `tail_radar.candidate` payload in `research_artifacts`.

The candidate payload preserves the complete normalized source row, inclusive thresholds and
observed values, intended and actual snapshot timestamps, source snapshot/run IDs, provider,
checksum, schema version, and screening rule version. Its `as_of` is the actual fetch-finish time,
so downstream research cannot treat later-observed evidence as earlier information.

`(snapshot_id, screening_rule_version)` is unique. The shared execution identity also includes the
source snapshot UUID, so separately versioned official snapshots for the same intended slot do not
collide. Repeating the command returns the existing Tail Radar run without rereading Parquet or
creating candidates. Candidate artifacts, candidate links, counts, and the succeeded transition
commit together.

## Manual execution

From `backend/`, after migrations and after an official market snapshot exists:

```powershell
uv run tail-radar execute --snapshot-id <snapshot-uuid>
uv run tail-radar inspect --run-id <tail-radar-run-uuid>
```

This command reads PostgreSQL and local Parquet only. It does not call AKShare, OpenAI, or any other
network service. No recurring scheduler is introduced.

## Public read API

All routes are read-only:

```text
GET /api/v1/tail-radar/runs/latest
GET /api/v1/tail-radar/runs?page=1&page_size=20
GET /api/v1/tail-radar/runs/{run_id}
GET /api/v1/tail-radar/runs/{run_id}/candidates?page=1&page_size=50
GET /api/v1/tail-radar/candidates/{candidate_id}
```

Run and candidate collections are paginated with bounded page sizes. Candidate detail exposes the
explanatory evidence; server-local Parquet storage keys stay in snapshot-manifest infrastructure.
There is no public POST or other
route that executes screening or fetches live market data.

## Phase 4 intraday feature analysis

`tail-radar-intraday-v1` analyzes one persisted candidate at an explicit aware
`analysis_as_of`. It uses normalized unadjusted five-minute bars only. Code excludes future bars
before quality checks or calculations; the persisted report records future, duplicate, missing,
out-of-order, malformed, and off-session observations.

Persisted price features are previous 5/15/30-minute return, return since open, distance from the
intraday high/low, normalized intraday position, and drawdown from the high. Volume/value features
are recent and prior comparable five-minute volume, acceleration ratio, recent amount, cumulative
VWAP, and distance from VWAP. Unavailable evidence produces `null` fields.

The explicit conditions `steady_strengthening`, `late_acceleration`,
`early_spike_followed_by_pullback`, `recovery_from_intraday_weakness`, and
`materially_below_earlier_intraday_peak` follow the fixed thresholds in
[ADR 0009](adr/0009-point-in-time-intraday-features.md). They are descriptions, not a score, advice,
or prediction.

After a candidate exists, execute manually from `backend/`:

```powershell
uv run tail-radar analyze-intraday `
  --candidate-id <candidate-uuid> `
  --analysis-as-of "2026-08-28T14:35:00+08:00"
```

The timestamp must be on the candidate trade date, at or after its snapshot evidence, no later than
the current time, and include an explicit offset. Repeating the same candidate, timestamp, and
calculation version returns the existing analysis. Candidate detail includes the latest persisted
intraday analysis; no public route executes it.

## Phase 5 point-in-time web research

`tail-radar-research-v1` researches one persisted candidate through a provider-neutral application
contract. The OpenAI adapter is the only code that imports the official SDK. It uses the Responses
API with web search and a strict Pydantic output schema. Screening and intraday features remain
deterministic and neither depend on nor change because of AI output.

Every request has an aware `analysis_as_of`. The prompt explicitly prohibits treating information
published later as evidence known at that time. The application validates URLs against sources
actually returned by web search, derives domains from URLs, and persists publication timestamps as
`verified`, `uncertain`, or `unavailable`. A verified post-boundary source is retained for audit but
classified `published_after_as_of` and cannot support a substantive claim. Retrieval time is always
preserved separately. Verified facts require at least one verified source available at the
boundary; interpretations remain explicitly labeled; absence of useful evidence becomes a
successful `no_evidence` artifact with insufficient evidence quality, not invented content.

PostgreSQL claims the paid-call identity before contacting OpenAI:

```text
(candidate, run, analysis_as_of, prompt_version, provider, requested_model)
```

The default path returns the existing running, successful, no-evidence, or failed attempt without a
second charge. `--force` creates a new attempt linked to the cached base attempt and never overwrites
it. A timeout, rate limit, provider/API error, or malformed output fails only this candidate's
research attempt; it does not invalidate the Tail Radar run. Valid partial provider output retains
warnings. Sources live in `tail_radar_research_sources`; the versioned content and source references
live in a `tail_radar.web_research` `ResearchArtifact`.

The stored SHA-256 hash must remain stable for a prompt version. If prompt text changes without a
new version, execution stops before any paid call instead of silently reusing or replacing cached
research.

Run the explicit manual diagnostic from `backend/` after placing a newly generated key in the
ignored root `.env` and applying migrations:

```powershell
uv run tail-radar research `
  --candidate-id <candidate-uuid> `
  --analysis-as-of "2026-08-28T14:35:00+08:00"
```

Add `--force` only for an intentional additional paid attempt. No normal test makes an OpenAI or web
request, and no public route starts research. Candidate detail exposes the latest successful or
no-evidence research and its sources; private provider response IDs, token accounting, and raw
provider metadata stay backend-side.
