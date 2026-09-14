# ADR 0015: Trend Radar with an outbound-only cloud control plane

- Status: Superseded by [ADR 0016](0016-trend-radar-local-control-static-publication.md) on 2026-09-13
- Date: 2026-09-12

## Context

Trend Radar adds a fifth feature boundary to the modular monolith. A public static site needs
historical daily results and authenticated scan requests while computation and raw data remain on
the operator's Windows machine. Existing Tail Radar capture and AI workflows must remain intact.

## Decision

Add `features/trend_radar` in both applications. Reuse SQLAlchemy, Alembic, PostgreSQL, the backend
image, structured logging, argparse, React Query and hash routing. No new inbound local endpoint is
introduced. Compose exposes local PostgreSQL and the API on loopback. Trend Radar's optional worker
profile holds the Supabase secret; frontend builds receive only its URL and publishable/anon key.

Use Supabase as publication and control plane, with separate migrations and explicit RLS. Public
reads include sanitized run attempts, successful results and heartbeat metadata. Only users in
`trend_admin_users`, maintained by a trusted operator, may call the request RPC. Authenticated users
cannot insert requests directly or modify operational rows. Auth user metadata never grants admin.

All triggers call one service under a local connection-scoped PostgreSQL advisory lock and a cloud
lease. A cloud transaction serializes claims, coalesces pending requests and enforces one automatic
attempt per Shanghai trading date. A 120-second lease is renewed by an independent heartbeat thread;
publication rejects expired ownership. The next claim marks abandoned cloud runs/requests failed.
Failed automatic attempts require a deliberate manual/CLI retry, preserving their daily identity.
Workers sharing this deployment must share the same local PostgreSQL lock domain.

Define heat as Eastmoney's full available A-share **attention index** (`stock_comment_em`), sorted
descending with symbol tie-breaking. This is not Eastmoney's separate Top-100 popularity list.
Never synthesize the missing 200, use turnover as heat, or exclude ST/Beijing as a screening rule.
Fail if fewer than the configured Top N are available, if symbols repeat, or if selected heat dates
do not match the latest completed session. Source coverage, including Beijing, is provider-dependent.

Use qfq daily OHLC, actual reported volume and amount. A window contains N closes and N-1 internal
close-to-close returns. Select the longest valid 9/8/7 window before checking its preceding baseline.
Daily bars are considered complete after 15:15 Shanghai; during market hours use the previous
completed session. No arbitrary historical live scan/as-of override is accepted. `data_as_of` is the
aware knowledge boundary after collection, not a claim that current adjusted data existed earlier.

Raw evidence uses local JSONB records with indexed relational identities. A qfq series may change
after corporate actions, so cache a coherent short history per symbol and completed-session vintage;
refresh the whole lookback on a new vintage or after six hours. Do not append differently adjusted
price vintages. Candidate results retain immutable used bars, and Top N snapshots are per run.
Cross-feature outputs use existing `ResearchArtifact` schema version 1 with type
`trend_radar.candidate`. No AI interpretation is involved.

Publish all derived results and the success status in one cloud transaction. Latest means the
successful run with greatest `(started_at, id)`, never the last attempted run or a partly uploaded
dataset. Supabase stores no raw OHLC history. Same-day manual/CLI runs have distinct UUIDs.

## Consequences

The browser needs no route to the local machine. Changes are additive to Tail Radar. Free provider
outages, stale heat, malformed bars or a missing latest session fail the run without changing public
success. Missing sessions inside the lookback are explicit exclusions; zero-volume trend windows
cannot qualify. Without authoritative suspension metadata, a missing latest bar fails the whole scan
instead of silently accepting an incomplete universe. New listings are recorded as insufficient
history. A zero amount baseline yields null context, never a volume-based highlight.

The adapter isolates AKShare calls in child processes to enforce hard timeouts without monkeypatching
global HTTP behavior. Sequential bounded retries and pacing trade throughput for predictable load.
API stability, licensing, revised data, source-date delays, and availability still require monitoring.
The first version uses Chinese stock cards at all widths, polls every five seconds, and caches only
the static PWA shell. It never caches Auth responses, control operations or market results offline.
