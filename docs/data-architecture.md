# Data architecture

Trend Radar retains daily heat, coherent qfq bar vintages, scan history and immutable candidate
evidence in local PostgreSQL. Only allowlisted scan summaries and candidate metrics are exported
as static public JSON; schedule claims and worker heartbeat stay local. See [Trend Radar](trend-radar.md) for schemas, migration commands and retention limits.

## PostgreSQL: structured operational and research metadata

PostgreSQL is authoritative for execution lifecycle, research artifacts, analysis and candidate
metadata, news/source metadata, and relational indexes. SQLite is not a production substitute.

The durable relational contracts are:

- `execution_runs` records intended and actual timing, status, provider, implementation version,
  official/forced identity, optional rerun lineage, metadata, and structured error information.
- `research_artifacts` stores module, artifact type, optional symbol/trade date, aware `as_of`, schema
  version, structured JSON payload, and creation time.
- `market_snapshot_manifests` records each accepted Parquet artifact, point-in-time timestamps,
  provider provenance, quality report, relative storage key, SHA-256 checksum, schema version, and
  status. One manifest belongs to one execution run.
- `tail_radar_runs` links a shared execution run to one official source snapshot, screening rule
  version, exact configuration, and finalized evaluation counts.
- `tail_radar_candidates` links a candidate `ResearchArtifact` to its Tail Radar run, source market
  snapshot, and symbol. The artifact payload carries the complete normalized row and screening
  evidence.
- `tail_radar_intraday_analyses` links a versioned intraday feature artifact to its candidate, Tail
  Radar run, and source snapshot and enforces candidate/`analysis_as_of`/calculation-version
  idempotency.
- `tail_radar_research_analyses` records each OpenAI research attempt, its
  candidate/run/snapshot identity,
  aware `analysis_as_of`, prompt hash/version, requested and actual model, token counts, lifecycle,
  forced-attempt lineage, and immutable research artifact reference.
- `tail_radar_research_sources` stores source URLs separately with title/domain, verified or
  uncertain publication timing, retrieval timing, historical availability classification, and
  claim relationships. Unknown metadata remains null rather than being fabricated.
- `tail_radar_workflows` extends one shared execution run with snapshot, screening, fixed
  `analysis_as_of`, lifecycle, aggregate technical/research counts, and fatal-stage metadata.
- `tail_radar_workflow_candidates` stores isolated technical/research stage state and immutable
  artifact/analysis links for every candidate, enabling safe resume after partial completion.
- `tail_radar_schedules` stores one operational decision for each official Shanghai trade date,
  including intended 14:30 time, calendar evidence, preflight report, missed/terminal status,
  workflow linkage, actual orchestration timing, and bounded error metadata.

Artifact type names are namespaced (for example `tail_radar.candidate`) and payload consumers
must select a supported `schema_version`. The schema remains flexible without sacrificing indexed,
auditable envelope fields.

Phase 3 publishes deterministic selections as `tail_radar.candidate` schema version 1 artifacts.
The candidate `as_of` is the actual source fetch-finish timestamp, while the payload separately
retains intended time, all actual timestamps, snapshot identity/checksum, rule version, normalized
row, and exact inclusive decision evidence.

Phase 4 publishes `tail_radar.intraday_features` schema version 1 artifacts. These retain the source
candidate/run/snapshot, explicit `analysis_as_of`, latest bar used, provider request/provenance,
calculation version and configuration, nullable feature groups, descriptive path conditions, and an
intraday quality report. Raw intraday history is not added to PostgreSQL.

Phase 5 publishes `tail_radar.web_research` schema version 1 artifacts. The payload distinguishes
verified facts, interpretations, and insufficient evidence, and retains candidate/run/snapshot
provenance, source IDs, prompt hash/version, requested and actual model identifiers, token usage,
confidence, evidence quality, and explicit `analysis_as_of`. A partial unique index admits one
non-forced attempt for
`(candidate, run, analysis_as_of, prompt_version, provider, requested_model)`. Forced attempts are
separate rows linked to the cached base attempt; no result is overwritten.

Phase 6 publishes no replacement aggregate signal. Workflow version 2 orchestrates the candidate
and intraday-feature artifacts, then leaves AI research pending as an optional, explicitly
confirmed single-candidate follow-up using a request-scoped user key. The key is not persisted;
research progress and artifact links remain relationally recorded. Phase 7 uses
intraday artifact schema 2, which adds only the exact normalized, ordered, cutoff-safe bars used by
`tail-radar-intraday-v2`; deterministic formulas remain unchanged.

Phase 8 schedule rows do not replace `execution_runs` identities. A PostgreSQL advisory lock
serializes active worker orchestration, while unique official workflow and snapshot indexes remain
the durable duplicate protection. A `missed` schedule has no workflow link and therefore cannot be
mistaken for a captured official point in time.

## Parquet: large immutable datasets

Accepted full-market snapshots use Parquet under `runtime/market-data/<fetch-date>/`. Each file has
a stable typed record schema and embeds its snapshot manifest as Parquet metadata. Files are
published through an atomic same-directory no-clobber link and are always ignored by Git. Containers
bind-mount `runtime/`, so data does not exist only in disposable layers. Historical bars and large
quantitative datasets will follow the same immutable-data principle in later phases.

The embedded fetch manifest remains self-describing. Phase 2 also registers an immutable PostgreSQL
manifest for executed snapshots so provenance can be inspected without scanning Parquet metadata.
The database stores a relative storage key rather than a machine-specific absolute path. Bulk rows
are not duplicated into PostgreSQL.

Official execution claims are unique by job type, trade date, intended snapshot time, and execution
version. Forced runs are marked non-official and may link to the official run. The Parquet file is
created before the database manifest transaction; if commit outcome becomes uncertain, the file is
retained to avoid breaking a manifest that may have committed.

## Integrity rules

- Market/research timestamps are timezone-aware; A-share market semantics use `Asia/Shanghai`.
- Historical artifacts always retain an explicit `as_of`.
- No calculation may access data observed after its `as_of` boundary.
- Provider identifiers and raw fields are normalized in adapters before entering domain logic.
- Database changes require reviewed Alembic migrations.
- Runtime data and credentials are never committed.

Vector stores, embeddings, and semantic retrieval remain deliberately deferred. Provider expansion
and scheduled ingestion require evidence from live diagnostics before adoption.
