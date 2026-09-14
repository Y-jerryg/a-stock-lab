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
GET /api/v1/tail-radar/runs/{run_id}/summary
GET /api/v1/tail-radar/runs/{run_id}/candidates?page=1&page_size=50
GET /api/v1/tail-radar/candidates/{candidate_id}
GET /api/v1/tail-radar/research-availability
```

Run and candidate collections are paginated with bounded page sizes. Candidate detail exposes the
explanatory evidence; server-local Parquet storage keys stay in snapshot-manifest infrastructure.
The research-availability response exposes only safe capability flags and the requested model name;
it never returns an API key.
There is no public POST or other
route that executes screening or fetches live market data.

## Phase 4 intraday feature analysis

`tail-radar-intraday-v2` analyzes one persisted candidate at an explicit aware
`analysis_as_of`. It uses normalized unadjusted five-minute bars only. Code excludes future bars
before quality checks or calculations; the persisted report records future, duplicate, missing,
out-of-order, malformed, and off-session observations.

Persisted price features are previous 5/15/30-minute return, return since open, distance from the
intraday high/low, normalized intraday position, and drawdown from the high. Volume/value features
are recent and prior comparable five-minute volume, acceleration ratio, recent amount, cumulative
VWAP, and distance from VWAP. Unavailable evidence produces `null` fields.

Schema 2 also retains the ordered normalized bars actually used after the point-in-time cutoff. They
are presentation evidence for the public intraday chart; future, duplicate-invalid, and off-session
bars are never placed in that used series.

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

`tail-radar-research-v2` researches one persisted candidate through a provider-neutral application
contract. The OpenAI adapter is the only code that imports the official SDK. It uses the Responses
API with web search and a strict Pydantic output schema. Screening and intraday features remain
deterministic and neither depend on nor change because of AI output.

Version 2 requires all narrative research fields to use Simplified Chinese for direct display in
the public interface. Authentic source titles, URLs, stock symbols, company names, proper nouns,
model identifiers, and version identifiers remain unmodified when translation would weaken source
attribution. The prompt-version change gives Chinese results a distinct paid-call cache identity;
historical version 1 artifacts remain immutable and reproducible.

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

## Phase 6 application workflow and on-demand AI policy

`TailRadarApplicationService` version `tail-radar-workflow-v2` composes official snapshot
execution, quality validation, screening, candidate persistence, and intraday analysis. It never
loops over candidates to call OpenAI. Every candidate starts with research status `pending`; that is
an optional follow-up and does not prevent a deterministic workflow from succeeding.

The workflow states are `claimed`, `snapshot_running`, `screening_running`,
`candidate_analysis_running`, `succeeded`, `partial_success`, and `failed`. Each candidate separately
records technical and research stage state. One candidate provider failure does not roll back other
candidates. Resume skips successful technical artifacts and does not start AI work.

```powershell
uv run tail-radar workflow `
  --intended-snapshot-time "2026-08-31T14:30:00+08:00"

uv run tail-radar resume `
  --workflow-run-id <workflow-run-uuid>
```

The optional `--analysis-as-of` fixes a later explicit boundary. If omitted, the workflow fixes the
boundary after screening. All public routes remain GET-only. Run summary exposes snapshot latency,
counts, quality and workflow completion; candidate collections expose overview features and stage
status; candidate detail exposes used bars, versions, research claims and separate source records.

Candidate intraday analysis uses `TAIL_RADAR_INTRADAY_WORKERS` (default 4, range 1–8). Snapshot and
screening remain sequential; every candidate retains the fixed `analysis_as_of`. A primary
intraday network failure starts a 60-second transport cooldown using the existing fallback.
See [ADR 0017](adr/0017-bounded-tail-radar-intraday-concurrency.md). The browser polls unfinished
stages with GET requests and never automatically retries a paid POST.

The supplied Nginx proxy waits 330 seconds for research, covering the maximum configurable
300-second backend timeout. HTML is not cached and missing asset files return 404. A failed lazy
page import displays a refresh action instead of blanking the app; refreshing makes no paid call.

Loading the page or opening a candidate detail never calls OpenAI. With backend on-demand research
enabled, the detail page accepts the user's own OpenAI API key, requires an explicit cost
confirmation, and submits exactly one candidate to:

```text
POST /api/internal/v1/tail-radar/candidates/{candidate_id}/research
```

The backend derives `analysis_as_of` from the workflow. Successful/no-evidence research is cached;
a failed attempt requires an explicit paid retry. The key stays in page memory, is sent in the
`X-OpenAI-API-Key` header, and must never be stored in `VITE_*`, a URL, logs, the database, or
browser storage. The backend creates a request-scoped OpenAI adapter and discards the key after the
request. A non-local deployment must use HTTPS, and users must trust the backend operator.

The overview offers an “上市板块” filter derived from normalized symbol and exchange evidence:
沪市主板、深市主板、创业板、科创板、北交所. This is not an industry classification. Unknown
families remain unavailable rather than receiving a fabricated label.

## Phase 7 public frontend

The Tail Radar hash route renders the latest persisted run, metrics, completion state and a sortable,
searchable, filterable, paginated candidate table. Candidate detail clearly labels raw snapshot
evidence, deterministic intraday calculations, and AI interpretation. The ECharts series uses only
persisted used bars. Missing values remain `—` or an explicit empty state. Source links open their
original URLs. The browser never receives a site-owned `OPENAI_API_KEY` and cannot start a market
workflow; a user-entered key exists only in the BYOK form's memory for one candidate request.

## Phase 8 official 14:30 worker

The recurring scheduler is a separate backend-image process, never a FastAPI background task. On a
provider-confirmed A-share trading day it targets exactly `14:30:00 Asia/Shanghai`. The schedule
record preserves that intended time; snapshot manifests separately preserve the real provider fetch
start and finish. The default initial-start tolerance is 30 seconds. If no official workflow was
claimed within that window, the worker persists `missed` and will not call a live provider later as
if it were the 14:30 observation.

A default 60-second preflight resolves the trading calendar, verifies database persistence,
confirms the normalized provider advertises snapshot and intraday capabilities, and reports backend
OpenAI/BYOK availability. It does not make an early full-market request. Missing OpenAI configuration
does not degrade or block deterministic capture; it only disables the optional single-candidate
research action.

PostgreSQL provides three layers of safety: one schedule row per logical day, a connection-scoped
advisory execution lock, and the existing unique official workflow/snapshot identities. A restart
can resume an existing nonterminal workflow after the dead connection releases its lock. The worker
makes no OpenAI calls. Existing completed/no-evidence research remains reusable, and failed paid
attempts are not automatically repeated.

Operational commands from `backend/` are:

```powershell
# Long-running process used by the Compose worker service
uv run tail-radar worker

# One immediate scheduling decision, useful for liveness/diagnosis without a real-time wait
uv run tail-radar worker-once

uv run tail-radar scheduled-status
uv run tail-radar scheduled-status --trade-date 2026-08-31

# Analysis-only recovery is allowed only if an official snapshot was already captured
uv run tail-radar scheduled-retry --trade-date 2026-08-31

uv run tail-radar worker-health --max-age-seconds 30
```

The existing `tail-radar workflow --intended-snapshot-time ...` remains the manual complete
diagnostic. `market-snapshot execute-at ... --force` creates an explicitly non-official live
snapshot, and `tail-radar research ... --force` creates an explicitly forced paid research attempt.
Neither replaces an official missed or failed 14:30 capture. Public APIs and the frontend remain
read-only and expose none of these controls.
