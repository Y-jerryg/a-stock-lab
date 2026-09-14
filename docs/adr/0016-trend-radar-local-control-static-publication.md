# ADR 0016: Local Trend Radar operations and a read-only static website

- Status: Accepted
- Date: 2026-09-13
- Supersedes: [ADR 0015](0015-trend-radar-cloud-control-plane.md)

## Context

The owner changed the product requirement: only someone operating the local computer can start
collection. Website visitors see results and cannot submit requests, including on desktop browsers.
Consequently a remote request queue, website authentication and Supabase database are unnecessary.

## Decision

Retain PostgreSQL as the authoritative local store and keep the deterministic strategy, provider
adapters, shared ResearchArtifact and as_of semantics from ADR 0015. Remove its Supabase adapter,
cloud migrations, environment keys, browser SDK, login screen and request operations. No replacement
HTTP scan endpoint is introduced. Existing unrelated feature operations are outside this decision.

A Windows Forms operator window invokes the same local CLI used by an optional scheduled worker.
The default is manual operation. A session-scoped PostgreSQL advisory lock serializes all scans
and exports. Alembic 0010 adds a unique trade-date schedule claim, backfilled from historical runs.
Interrupted attempts are recovered when a subsequent scan acquires the lock. Failed scheduled
attempts require an explicit local retry instead of retrying on every worker poll.

Publication exports versioned JSON: an allowlisted run index and per-success candidate results.
Result files are completed first and the index is atomically replaced last. Local database success
survives an export failure; a separate export command repairs publication without fetching market
data. The latest successful dataset remains visible after subsequent failed attempts. No raw bars,
internal error details, credentials or entire configuration dumps enter the public bundle.

The website reads same-origin static JSON with GET only. Docker mounts the public directory read-only;
the Nginx location rejects writes and returns 404 for missing data. The former admin route redirects
to the read-only page. User agents, viewport sizes and login states cannot enable scanning.

Public GitHub Pages deployments are explicit operator actions. A dedicated public ZIP is uploaded
as a release attachment, not committed as runtime financial data. Pages downloads and validates its
exact filenames and run identities before building the static site. Code-only deployments also
reuse this bundle. Missing first-publication data produces an empty state; failed downloads or
invalid existing bundles abort deployment. A successful workflow, not upload completion, means the
public website has updated. Alternative static hosts can publish the same directory atomically.

## Consequences

No Supabase account, API keys or website administrator setup is needed. The computer must run for
collection, and local updates require a separate publication to reach public hosting. Operational
heartbeat stays local. The last 100 attempts plus the latest success are exported; older evidence
remains in PostgreSQL. This change does not silently delete any previously provisioned cloud project.
