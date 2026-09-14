# ADR 0017: Bounded Tail Radar intraday concurrency

- Status: Accepted
- Date: 2026-09-13

## Context

The September 3 workflow captured 5,908 snapshot rows in 49.5 seconds, but processing 250
candidate intraday series took approximately another 26 minutes. Each candidate waited on the
same intermittently unavailable Eastmoney transport before trying the existing Sina fallback.

## Decision

Keep snapshot capture and screening sequential. Run deterministic candidate analysis with a bounded
thread pool, configured by `TAIL_RADAR_INTRADAY_WORKERS` (default 4, range 1–8). Every candidate
retains the workflow's immutable analysis_as_of. Repository methods create independent sessions;
existing workflow row locks serialize aggregate count updates. Wait for submitted work before
completing the workflow. Resume skips successful candidates. AI is never submitted to this pool.

Within one AKShare provider instance, a network failure starts a 60-second primary intraday
transport cooldown. Requests during that interval use the existing Sina fallback directly.
After expiry, try Eastmoney again. Protect shared cooldown state with a lock. Schema failures do
not activate the cooldown; existing normalization, volume units and point-in-time checks remain.
The snapshot transport is independent and still requires complete pagination and quality gates.

## Consequences

One slow candidate no longer serializes all candidates. There are at most eight concurrent
candidate requests, and the default is four; upstream throttling still remains possible. Operators
can set one worker to restore sequential execution. This is a latency optimization, not a
guarantee of data-source availability or a change to screening/research contracts. It adds no
database columns, new provider, AI calls, or historical snapshot backfill.
