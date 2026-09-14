# Deployment architecture

The repository defines independently deployable static frontend, API, worker, PostgreSQL, and
runtime-artifact boundaries. Local Compose is a validation/development topology, not a complete
internet production platform.

## Frontend

The React application is a static artifact. It uses `HashRouter`, so a URL such as
`/a-stock-lab/#/tail-radar` requires no server rewrite for the client route. `VITE_BASE_PATH` controls
asset paths for a GitHub Pages repository deployment, while `VITE_API_BASE_URL` points to the
separately deployed backend. Both values are public; secrets must never be placed in frontend build
variables.

The container deployment uses Nginx and same-origin `/api` proxying. This is convenient for local or
single-environment container hosting and does not constrain the independent static deployment.

The GitHub Pages workflow builds only `frontend/` and uploads only `frontend/dist`. It derives the
repository project base, loads the published Trend Radar result bundle, rejects local or
credential-bearing `VITE_API_BASE_URL` values when configured, and deploys with the `github-pages`
environment. Trend Radar needs no public backend; other API-driven modules still need one. CI and
Pages deployment remain separate workflows. Repository setup and the deployment blocker are
documented in [github-pages.md](github-pages.md).

## Backend

The FastAPI image is independently deployable and configuration-only. Production should inject
`DATABASE_URL`, allowed CORS origins, log level, runtime storage location, and provider credentials
through a secret manager or protected environment configuration. API documentation is disabled when
`APP_ENV=production`.

The same image exposes the manual `market-snapshot` and `tail-radar` commands and launches the
separate `tail-radar worker` Compose service. The worker invokes the same application/domain code;
the FastAPI process never starts a scheduler. PostgreSQL coordinates the daily schedule and active
execution. No Redis, Celery, or queue is required. Public Tail Radar routes read persisted data only.

The worker emits a secret-free heartbeat below mounted `runtime/worker/`, which Compose uses for
liveness. It handles SIGTERM/SIGINT gracefully. Production still needs external alerting for
preflight degradation, missed schedules, failed/partial runs, and stale heartbeats; container
restart policy alone is not monitoring.

## Database and datasets

PostgreSQL requires managed backups, point-in-time recovery, encrypted connections, and restricted
network access in a real deployment. Schema migrations should run as an explicit release step before
new application instances receive traffic. The manual market-data diagnostic and point-in-time
engine write accepted snapshots to the configured runtime filesystem. Local Compose bind-mounts
that directory. Phase 2 registers executed snapshot manifests and checksums in PostgreSQL, but a real
deployment still requires durable filesystem or object storage before artifacts can be relied upon
across instance replacement. Database backups do not include referenced Parquet content; both stores
need coordinated retention and recovery.

In local Compose, `POSTGRES_HOST_PORT` controls only the Windows-facing debugging port. The database
container continues listening on 5432, and backend containers connect through `postgres:5432` on the
Compose network. A host-published database port should not be exposed in a production deployment.

## Network and access boundary

Public users receive read-oriented `/api/v1` routes. Single-candidate AI research remains under the
separate `/api/internal/v1` operational boundary and requires the caller's transient OpenAI key plus
explicit cost confirmation. This BYOK credential is not A-Stock Lab authentication. CORS is an
additional browser control, not authentication. Production BYOK requires HTTPS, a trusted backend,
abuse controls, and browser security hardening before public use.

No cloud provider, monitoring vendor, domain, TLS termination, authentication system, recurring
scheduler, or production data retention policy is selected through Phase 3.
