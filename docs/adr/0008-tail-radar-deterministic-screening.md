# ADR 0008: Point-in-time deterministic Tail Radar screening

- Status: Accepted
- Date: 2026-08-29

## Context

Tail Radar needs a reproducible first candidate-selection rule without continuous monitoring,
technical indicators, provider coupling, or AI interpretation. A selected stock must remain
explainable from the exact official full-market snapshot that produced it. Repeating an execution
must not create conflicting candidate sets.

## Decision

Version the initial rule as `tail-radar-screen-v1`. It evaluates every normalized record from one
successful official snapshot exactly once and includes a record only when its valid `pct_change` is
inside the inclusive range `2.00 <= pct_change <= 3.00`, its symbol and current price are valid, and
registered snapshot evidence exists. ST, amount, float-market-cap, exchange, and board filter slots
are represented in typed configuration but are rejected if enabled in version one.

Persist one shared `ExecutionRun` plus one `tail_radar_runs` record for a snapshot/rule pair. Enforce
that pair's uniqueness in PostgreSQL. Because the shared official-run key has no source-input
column, Tail Radar derives its execution implementation identity from the public rule version and
source snapshot UUID. This lets two versioned official snapshots for the same intended slot be
screened independently while the feature record and public contract retain the exact rule version.
Persist every included candidate as a versioned
`tail_radar.candidate` `ResearchArtifact`, extended by a relational `tail_radar_candidates` row that
links the artifact to its Tail Radar run and market snapshot. The artifact payload preserves the
normalized record, rule configuration and decision, source timestamps, provider provenance,
snapshot checksum, and rule version. Storage paths remain manifest infrastructure and are not copied
into domain evidence. Candidate `as_of` is the actual fetch-finish time, while the
intended snapshot time remains separately preserved.

The application verifies the registered Parquet checksum and embedded snapshot manifest before
screening. Candidate artifacts, feature links, finalized counts, and the successful run transition
commit in one PostgreSQL transaction. A commit with an uncertain outcome is not followed by a
failure transition.

Expose only paginated public `GET` APIs for already-persisted runs and candidates. Execution remains
an explicit CLI operation taking a snapshot UUID. No public endpoint, scheduler, or polling loop
triggers a market fetch or Tail Radar execution.

## Consequences

Boundary behavior and candidate provenance are reproducible, downstream Intelligence, Quant Lab,
and Assistant work can consume versioned artifacts, and anonymous traffic cannot cause expensive
work. A failed official screening remains visible and is not silently replaced. Future rule changes
or optional filters require a new rule version and tests; technical indicators and AI remain
separate later-stage concerns.
