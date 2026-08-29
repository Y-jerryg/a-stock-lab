# Data architecture

## PostgreSQL: structured operational and research metadata

PostgreSQL is authoritative for execution lifecycle, research artifacts, analysis and candidate
metadata, news/source metadata, and relational indexes. SQLite is not a production substitute.

Phase 0 creates two durable shared contracts:

- `execution_runs` records intended and actual timing, status, provider, implementation version,
  metadata, and structured error information.
- `research_artifacts` stores module, artifact type, optional symbol/trade date, aware `as_of`, schema
  version, structured JSON payload, and creation time.

Artifact type names are namespaced (for example `tail_radar.stock_analysis`) and payload consumers
must select a supported `schema_version`. The schema remains flexible without sacrificing indexed,
auditable envelope fields.

## Parquet: large immutable datasets

Accepted full-market snapshots use Parquet under `runtime/market-data/<fetch-date>/`. Each file has
a stable typed record schema and embeds its snapshot manifest as Parquet metadata. Files are written
through an atomic same-directory replacement and are always ignored by Git. Containers bind-mount
`runtime/`, so data does not exist only in disposable layers. Historical bars and large quantitative
datasets will follow the same immutable-data principle in later phases.

The Phase 1 diagnostic embeds its manifest in each Parquet file. A future scheduled ingestion
workflow should additionally register dataset manifests in PostgreSQL with provider, content
identity, time range, schema version, row count, creation time, storage location, and quality status.
Bulk records should not be duplicated into PostgreSQL by default.

## Integrity rules

- Market/research timestamps are timezone-aware; A-share market semantics use `Asia/Shanghai`.
- Historical artifacts always retain an explicit `as_of`.
- No calculation may access data observed after its `as_of` boundary.
- Provider identifiers and raw fields are normalized in adapters before entering domain logic.
- Database changes require reviewed Alembic migrations.
- Runtime data and credentials are never committed.

Vector stores, embeddings, and semantic retrieval remain deliberately deferred. Provider expansion
and scheduled ingestion require evidence from live diagnostics before adoption.
