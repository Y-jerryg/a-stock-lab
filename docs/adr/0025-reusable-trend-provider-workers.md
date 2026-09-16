# ADR 0025: Reusable isolated processes and four-way trend collection

- Status: Accepted
- Date: 2026-09-17
- Amends: ADR 0018 execution and ADR 0024 incremental cache lifecycle

## Context

Incremental date windows still require a request per stock on a new session. The serial adapter
started and imported AKShare in a new interpreter for every attempt, costing about 1.72 seconds
per startup in the operator's Docker environment. The owner requested reusable processes and
four concurrent daily collections after cancelling the current scan.

## Decision

Add TREND_FETCH_WORKERS (default 4, range 1–8). Application orchestration has a bounded window of
at most that many stock futures. Provider/cache reads execute concurrently, with individual stock
diagnostic context established in each thread. The coordinator alone screens, writes cache and
candidate checkpoints, updates counters and publishes progress. Harvest in universe order so the
existing consecutive-failure rule remains deterministic. A slow leading stock can delay harvesting
the small window; bound request time rather than queue the entire exchange universe. Check failure
thresholds before replenishing; at most workers minus one other stocks may already be in flight.
Closing the collection cancels queued work and joins active bounded requests before releasing the
scan lock. Successful checkpoints are retained under the existing partial-completion policy.

The adapter owns a lazily started spawn-process pool, with one request at a time per leased process.
SDK imports remain loaded between requests. Pipes carry normalized rows or redacted structured
exception details, preserving the one-shot field mapping and source/volume conventions. Timeout or
worker exit kills and joins only that process and discards its pipe; retry obtains a fresh process.
Normal provider exceptions return their full redacted traceback and do not poison the pool. Recycle
each process after 250 attempts to bound native SDK/JavaScript-engine memory growth. Close processes
at scan exit (including failures and busy attempts) and scheduler exit. A later scan can reuse the
provider object and lazily create fresh processes. No long-lived system service or extra Docker
container is required.

All sources, retries and fallbacks share one monotonic request-start pacer (default 0.3 seconds),
while per-attempt exponential retry delays remain. Protect the Eastmoney five-minute cooldown with
a lock; after it expires allow only one recovery probe while other workers use Sina. Initial healthy
requests may run concurrently. A successful probe cannot erase a concurrently recorded outage.
Keep per-request hard timeouts and never implement a timeout that merely abandons a running SDK
thread. Detailed logs retain stock ordinal, symbol, run, provider, attempt and traceback; completion
logs additionally report processed_count and fetch_workers for an accurate desktop progress display.

No screening rule, universe, API, published data schema or SQL schema changes. Cached reuse and
point-in-time evidence boundaries remain as specified in ADR 0024. Runtime benchmarks do not create
public scans or overwrite saved results. Actual speed depends on upstream behavior and cannot be
inferred solely by dividing a serial runtime by four.
