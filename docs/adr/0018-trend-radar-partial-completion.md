# ADR 0018: Isolate stock failures and publish explicit partial completion

- Status: Accepted
- Date: 2026-09-13
- Amends: ADR 0015 screening failure semantics and ADR 0016 publication semantics

## Context

The operator requires a Top-300 batch to keep useful work when individual daily requests fail.
Live checks found Eastmoney daily connection failures while the calendar and heat feed worked.
The former exception boundary aborted at the first stock and also lost the updated immutable run
value, resetting the resolved session and progress in the failure record.

## Decision

Keep the real exchange calendar and 15:15 Asia/Shanghai completion cutoff. Manual scans on weekends
and holidays use the latest completed session; heat must match it. Do not invent historical heat,
fill missing daily observations, or treat a missing latest bar as an ordinary non-candidate.

Daily provider errors, malformed/duplicate/future sequences and missing latest bars fail that stock.
Record the stock and continue. Successful processing includes valid stocks excluded by the screening
rules; candidate_count remains a separate metric. Final coverage reports requested_count,
successful_count, failed_count and failed_symbols. Nonzero isolated failures produce
completed_with_warnings, exit code 0, and a clearly labelled published partial dataset.

Default global failure limits are failures >= 20% of the requested universe OR 10 consecutive stock
failures, both configurable. The denominator is the requested universe, never the number attempted
so far. Calendar/heat failures, stale heat, invalid configuration, database outages and unexpected
application faults remain global failures. An abort retains processed counts and candidate evidence
locally, but does not replace the latest published completed dataset.

After every stock, transactionally checkpoint the run and any candidate/input bars. Completed runs
emit version 2 trend_radar.candidate ResearchArtifacts (other feature contracts are unchanged).
Every ten stocks, best-effort export progress. Cache refresh replaces the complete symbol/vintage
series transactionally; immutable run evidence is unaffected. A later scan can reuse valid same-day
cache entries for six hours. This is cache reuse, not exact run resumption after a changing heat feed.

The adapter retains hard subprocess timeouts, pacing and up to three attempts per source by default.
After exhausted primary request errors, fetch the whole lookback from AKShare's Sina qfq daily
endpoint. Suspend primary calls for five minutes before probing it again. Do not splice bars from
different sources or fall back on successfully returned but malformed bar values. Sina shares are
converted to lots; amount stays in yuan. Every bar retains its actual source, and the run lists the
sources used across stocks. No screening strategy or provider SDK is moved into domain code.

Each provider attempt logs run/stock context, source, operation, attempt, date bounds, endpoint or
actual failing URL, original exception type/message and full child traceback. The final stock failure
also logs its orchestration traceback. Redact credential-like values before logging. Public files
include only stock identifiers, names, safe error codes and coverage; detailed errors remain local.

Alembic 0011 widens the status column from 16 to 32 characters. Publication index version 2 supports
the new status and coverage; candidate result files remain version 1 because their shape is unchanged.
The updated frontend and bundle installer read both index versions 1 and 2. Deploy the reader with
the writer; old readers correctly reject the new version instead of silently misrepresenting coverage.

## Consequences

A 297/300 completed scan is usable and visibly incomplete. Broad outages stop without wasting another
290 requests, while previous checkpoints remain inspectable. Visitors still cannot initiate scans.
Upstream failures remain possible; this decision makes them diagnosable and limits their impact.

Sina qfq fields and units are documented by
[AKShare](https://akshare.akfamily.xyz/data/stock/stock.html#历史行情数据-新浪).
