# ADR 0007: Point-in-time snapshot execution and official identity

- Status: Accepted
- Date: 2026-08-29

## Context

Late-session research must distinguish the time a snapshot was intended to represent from the time
the provider was actually called and the time the resulting dataset became durable. Manual retries
and concurrent invocations must not create competing snapshots that both appear official. Bulk
snapshot rows are unsuitable for relational storage, while provenance and execution state require
transactional queries.

## Decision

Use an explicit logical identity for official snapshot runs: job type, A-share trade date, intended
snapshot timestamp, and execution version. PostgreSQL enforces one official run for that identity
with a partial unique index. Repeating an official command returns the existing run without calling
the calendar, provider, or storage again. `--force` creates a separately identified non-official run
and links it to the official run when one exists; it never silently replaces official history.

Claim the run in PostgreSQL before external work. Resolve the trade date through a provider-neutral
`TradingCalendar`, quality-gate the full-market response, write the immutable rows to Parquet, then
commit the Parquet manifest and successful run transition in one PostgreSQL transaction. The
manifest stores the relative storage key and SHA-256 checksum. No public API or recurring scheduler
is introduced in this phase.

Preserve `intended_snapshot_time`, `actual_fetch_started_at`, `actual_fetch_finished_at`, legitimate
`provider_timestamp`, and `persisted_at` separately as aware `Asia/Shanghai` values. Reject naive
timestamps and execution before the intended time. Because the implemented provider capability is a
live snapshot rather than historical reconstruction, also reject an intended trade date different
from the actual Shanghai execution date.

PostgreSQL and a filesystem cannot share one atomic transaction. Files created before a definitely
failed manifest registration are removed. Once registration begins, an artifact is retained if the
database outcome is uncertain so a committed manifest can never be left pointing at a deleted file.
Such an artifact may be unreferenced and is a reconciliation concern rather than an official
snapshot.

## Consequences

Official history is deterministic under retries and concurrent claims, delayed fetches remain
auditable, and large data stays outside PostgreSQL. Failed official runs require an explicit forced
rerun. Operations must monitor failed/running claims and eventually reconcile unreferenced files.
Adding recurring scheduling, retention, or object storage requires later operational design.
