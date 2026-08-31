# ADR 0011: Resumable Tail Radar workflow and evidence-separated read UI

- Status: Accepted
- Date: 2026-08-31

## Context

Tail Radar's snapshot, deterministic screening, intraday analysis, and paid web-research services
were individually auditable and idempotent, but operators had to invoke them independently. Batch
research must isolate candidate failures, preserve partial completion, and resume without repeating
successful paid work. The public frontend also needs a serious research view without presenting AI
interpretation as market fact or inventing missing values.

## Decision

Add `TailRadarApplicationService` as an application-layer orchestrator over the existing services.
It does not reimplement provider access, quality validation, screening, feature calculation, or
research. A shared `execution_runs` row plus `tail_radar_workflows` records the official workflow
identity and lifecycle. `tail_radar_workflow_candidates` records independent technical and research
stage states and artifact links for every selected candidate.

The workflow version is `tail-radar-workflow-v1`. The official identity uses the intended snapshot
slot and workflow version. New execution claims before snapshot work. Fatal snapshot or screening
failure fails the workflow; candidate failures are isolated and produce `partial_success`. Resume
skips successful technical artifacts and successful/no-evidence research. Failed research is not
repeated unless `--retry-failed-research` explicitly requests a forced paid attempt. Existing
provider-level cache claims remain the final protection against duplicate ordinary paid calls.

Set one aware `analysis_as_of` for all candidate analyses in a workflow. If omitted, it is fixed
after screening using current `Asia/Shanghai` time; it must be on the trade date, no later than
current time, and no earlier than every candidate's snapshot evidence.

Upgrade the intraday artifact to schema 2 and calculation identity `tail-radar-intraday-v2`. The
formulas and thresholds are unchanged. The artifact now retains the ordered, unique normalized bars
that actually passed the point-in-time cutoff and were used by the calculation. This makes a real
intraday chart possible without refetching or fabricating data.

Keep all public APIs read-only. Add run summary data, snapshot metrics and quality, workflow progress,
candidate stage statuses, overview feature fields, and the persisted used-bar series. The static
frontend uses hash routing and typed read clients. It visually separates `RAW MARKET DATA`,
`DETERMINISTIC CALCULATIONS`, and `AI INTERPRETATION`; missing evidence renders as unavailable.
Historical schema-1 intraday artifacts remain readable, but expose a null used-bar series because
those artifacts never persisted it; the UI shows an unavailable chart instead of fabricating one.

## Consequences

An interrupted or partially failed candidate batch is resumable and auditable. Successful expensive
work is reusable, while explicit retries remain visible and cost-bearing. Cross-module consumers can
continue reading versioned `ResearchArtifact` outputs without depending on workflow tables. The
frontend stays GitHub Pages compatible and never receives provider credentials or starts work.

There is still no scheduler, authenticated operations API, distributed queue, or automatic stale
running-attempt reaper. Concurrent ordinary AI attempts remain protected by the research cache key.
