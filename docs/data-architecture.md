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

## Parquet: future large immutable datasets

Full-market snapshots, historical bars, and large quantitative datasets will use Parquet under the
configured runtime data directory. Those files are not implemented in Phase 0 and are always ignored
by Git. Containers bind-mount `runtime/`, so future data does not exist only in disposable layers.

Future dataset manifests should live in PostgreSQL and record provider, content identity, time range,
schema version, creation time, and path. This preserves discoverability and provenance while keeping
large analytical scans out of transactional tables.

## Integrity rules

- Market/research timestamps are timezone-aware; A-share market semantics use `Asia/Shanghai`.
- Historical artifacts always retain an explicit `as_of`.
- No calculation may access data observed after its `as_of` boundary.
- Provider identifiers and raw fields are normalized in adapters before entering domain logic.
- Database changes require reviewed Alembic migrations.
- Runtime data and credentials are never committed.

Vector stores, embeddings, semantic retrieval, market-data persistence, and provider integrations are
explicitly deferred.

