# Deployment architecture

Phases 0 and 1 define deployable boundaries but do not deploy them.

## Frontend

The React application is a static artifact. It uses `HashRouter`, so a URL such as
`/a-stock-lab/#/tail-radar` requires no server rewrite for the client route. `VITE_BASE_PATH` controls
asset paths for a GitHub Pages repository deployment, while `VITE_API_BASE_URL` points to the
separately deployed backend. Both values are public; secrets must never be placed in frontend build
variables.

The container deployment uses Nginx and same-origin `/api` proxying. This is convenient for local or
single-environment container hosting and does not constrain the independent static deployment.

## Backend

The FastAPI image is independently deployable and configuration-only. Production should inject
`DATABASE_URL`, allowed CORS origins, log level, runtime storage location, and provider credentials
through a secret manager or protected environment configuration. API documentation is disabled when
`APP_ENV=production`.

The same image can later launch a worker entry point that imports the same application/domain code.
No queue or worker service exists yet.

## Database and datasets

PostgreSQL requires managed backups, point-in-time recovery, encrypted connections, and restricted
network access in a real deployment. Schema migrations should run as an explicit release step before
new application instances receive traffic. The manual market-data diagnostic writes accepted
snapshots to the configured runtime filesystem. Local Compose bind-mounts that directory; a real
deployment requires durable filesystem or object storage before persisted diagnostics can be relied
upon across instance replacement. PostgreSQL dataset-manifest registration remains future work for
scheduled ingestion.

In local Compose, `POSTGRES_HOST_PORT` controls only the Windows-facing debugging port. The database
container continues listening on 5432, and backend containers connect through `postgres:5432` on the
Compose network. A host-published database port should not be exposed in a production deployment.

## Network and access boundary

Public users receive read-oriented `/api/v1` routes. Future expensive or mutating research operations
belong behind authentication and authorization on a separate internal boundary. CORS is an additional
browser control, not authentication.

No cloud provider, monitoring vendor, domain, TLS termination, authentication system, or production
data retention policy is selected through Phase 1.
