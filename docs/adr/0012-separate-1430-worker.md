# ADR 0012: Separate database-coordinated 14:30 Tail Radar worker

- Status: Accepted
- Date: 2026-08-31

The worker's batch-AI behavior in this record is superseded by
[ADR 0013](0013-authenticated-on-demand-tail-radar-research.md). The scheduling and point-in-time
capture decisions remain in force.

## Context

The official Tail Radar workflow needs an unattended A-share trading-day capture at 14:30:00
Asia/Shanghai. Running a scheduler inside FastAPI would multiply jobs with web replicas and couple
request serving to market timing. A process restart, duplicate worker, provider outage, or late
startup must not create a second official run or make a later live response look like the intended
14:30 point in time.

## Decision

Run an independent `tail-radar worker` process from the existing backend image. The worker resolves
each date through the provider-neutral `TradingCalendar`; it never substitutes a weekday rule. The
schedule identity is `tail_radar.official_1430`, Shanghai trade date, and
`tail-radar-schedule-v1`. PostgreSQL stores one schedule record for that identity, while the
existing official workflow and snapshot identities remain the authoritative protections for
research and market artifacts.

Use a PostgreSQL connection-scoped advisory lock around the due execution or restart recovery. The
lock is automatically released if the process or connection dies. This prevents concurrent workers
from orchestrating the same workflow; unique official `execution_runs` indexes remain the final
database protection.

The official intended time is always 14:30:00 Asia/Shanghai. The default poll interval is five
seconds, preflight lead is 60 seconds, and maximum permitted initial start delay is 30 seconds; all
three operational values are bounded configuration. If no official workflow was claimed by the end
of that start window, persist `missed` and do not make a later live request. Actual provider fetch
times continue to come from the snapshot engine and are never overwritten with the intended time.

Preflight resolves the live trading calendar, proves database read/write availability by storing
the schedule state, checks provider-neutral quote capabilities, and reports whether backend OpenAI
configuration is present. It deliberately does not fetch the full quote universe early because
that would be a second market observation and could delay or interfere with the official call.
Missing AI configuration degrades preflight but does not block the deterministic official capture;
research fails per candidate and can be retried explicitly after configuration.

On restart, a worker with an existing nonterminal workflow resumes it under the database lock.
Successful and no-evidence paid research is reused. The worker never automatically forces a paid
retry. A failed initial snapshot is terminal for the official identity because a later live fetch
cannot reconstruct 14:30. A missed capture and a non-trading day are also terminal. Operators may
resume analysis only when an official snapshot already exists. Forced snapshot or research commands
remain explicitly non-standard and never replace official evidence.

Write a secret-free atomic heartbeat below `runtime/worker/` and expose liveness through a CLI
health command used by Docker Compose. SIGTERM and SIGINT trigger an interruptible graceful stop.
Do not add Redis, Celery, or a queue without measured concurrency or delivery requirements.

## Consequences

Web replicas cannot accidentally schedule work, duplicate worker processes are coordinated by
PostgreSQL, and late or missed executions remain honest. Runtime Parquet and heartbeat files must be
on durable mounted storage, while PostgreSQL records the audit history. AKShare's current calendar
adapter still lacks a controllable upstream request timeout; provider reliability and worker alerts
remain operational risks that must be observed before broad production use.
