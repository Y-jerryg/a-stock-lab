# ADR 0002: PostgreSQL plus Parquet storage

- Status: Accepted
- Date: 2026-08-28

## Context

Execution and research metadata is relational and frequently filtered, while market snapshots,
historical bars, and quantitative matrices will be large, immutable, and scan-oriented.

## Decision

Use PostgreSQL for structured operational/research records and future dataset manifests. Use Parquet
for future large immutable financial datasets. Do not use SQLite as the production database.

## Consequences

Transactional integrity and relational indexing remain strong without forcing analytical bulk data
into row storage. Dataset provenance and lifecycle tooling must be designed before Parquet ingestion
begins. Runtime datasets remain outside Git.

