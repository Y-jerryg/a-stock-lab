# Tail Radar deterministic screening

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
