# Development

## Prerequisites

- Docker Desktop with Docker Compose v2.24 or newer (required for the development override syntax)
- PowerShell 7 recommended
- For direct development: Python 3.12, `uv`, Node.js 22, and pnpm 11

The project can live at `D:\Dev\a-stock-lab`, but application code does not assume that path.

## Docker workflow

On the first startup, explicitly create the ignored local configuration and review its development
credentials:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

The supplied template publishes PostgreSQL at `localhost:55432`. This machine reserves the usual
alternative port 5433 at the Windows networking layer even when no process is listening. Change only
`POSTGRES_HOST_PORT` if 55432 is unavailable. This published port exists for native Python,
Miniconda, `psql`, and other local debugging tools. PostgreSQL still listens on 5432 inside the
container, and Docker services always use `postgres:5432`; they never use
`localhost:${POSTGRES_HOST_PORT}`.

For the hot-reload development stack, run:

```powershell
./scripts/dev.ps1
```

The development override mounts source code, enables FastAPI reload, runs Vite, persists PostgreSQL
in a named volume, and bind-mounts `runtime/` for immutable market datasets. A one-shot `migrate`
service completes Alembic before either API or worker starts. Stop the stack with:

```powershell
./scripts/dev.ps1 -Stop
```

Use `docker compose up --build` without the override to validate production-style images. That stack
serves the Nginx frontend on port 8080.

## Direct backend workflow

Start PostgreSQL (the Compose database can be used), then:

```powershell
Set-Location backend
uv sync --locked
uv run alembic upgrade head
uv run uvicorn a_stock_lab.main:app --reload
```

Configuration is read from environment variables and `.env`; see `.env.example`. A Miniconda Python
3.12 interpreter is valid for direct debugging. The container uses standard CPython and never
depends on Conda. With `DATABASE_URL` left blank, the native backend builds its connection from the
shared PostgreSQL credentials and `localhost:${POSTGRES_HOST_PORT}`. An explicit `DATABASE_URL`
overrides that derived value.

## Direct frontend workflow

Use Node.js 22.12 or newer for native frontend commands. The Docker and CI toolchains use Node 22.

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
$env:VITE_API_BASE_URL = 'http://localhost:8000'
pnpm dev
```

Never place credentials in `VITE_*`; Vite variables are public build output.

## Quality gates

```powershell
./scripts/lint.ps1
./scripts/test.ps1
```

Backend gates are Ruff formatting/lint, strict mypy, and pytest. Frontend gates are ESLint, strict
TypeScript, Prettier, Vitest, and a production Vite build. CI also builds both runtime images.

## Manual market-data diagnostic

Normal tests mock the provider and never use the internet. To make one explicit live observation:

```powershell
Set-Location backend
uv run market-data-diagnostic
```

Use `--repeat 3 --interval-seconds 120` to collect latency/success/count observations. Repeated calls
enforce a minimum 30-second interval. Use `--persist` only when a validated Parquet snapshot is
actually wanted; otherwise the command is read-only. Details are in
[market-data.md](market-data.md).

## Manual point-in-time snapshot execution

The execution command is separate from the non-persistent diagnostic. It always records a run in
PostgreSQL and, after calendar and quality acceptance, stores Parquet plus a PostgreSQL manifest:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run market-snapshot execute-now
$shanghaiDate = [DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(8)).ToString('yyyy-MM-dd')
uv run market-snapshot execute-at "$($shanghaiDate)T14:30:00+08:00"
uv run market-snapshot inspect --run-id <run-uuid>
```

Use `--force` only for an explicit non-official rerun. A failed or successful official identity is
otherwise replayed idempotently without another network call. The trading calendar is provider data;
the engine never treats an ordinary weekday rule as sufficient evidence of a trading day. There is
a separate recurring worker; these commands remain explicit diagnostics.

## Manual Tail Radar screening

After a successful official snapshot execution, pass its snapshot UUID explicitly. Screening reads
the registered local Parquet artifact and PostgreSQL only; it does not make a live provider call:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run tail-radar execute --snapshot-id <snapshot-uuid>
uv run tail-radar inspect --run-id <tail-radar-run-uuid>
```

Repeating the same snapshot under `tail-radar-screen-v1` returns the existing run. Public APIs are
read-only and cannot execute this command. See [Tail Radar documentation](tail-radar.md).

## On-demand OpenAI research

Normal development, CI, capture, screening, and deterministic analysis do not need an OpenAI key.
To enable the detail-page action, set only the feature flag in the ignored root `.env`:

```dotenv
OPENAI_RESEARCH_MODEL=gpt-5.6-sol
TAIL_RADAR_ON_DEMAND_RESEARCH_ENABLED=true
```

Restart the backend after changing `.env`. Open one candidate, enter your own OpenAI API key, check
the cost confirmation, and click “确认并分析当前股票”. Loading the page does not call OpenAI. The key
stays in that component's memory, is sent once in `X-OpenAI-API-Key`, and must never be placed in
`VITE_*`, the URL, logs, or browser storage. The backend creates a request-scoped provider and does
not persist or return the key. The endpoint accepts exactly one candidate per request. Outside
loopback development, the frontend and API must use HTTPS and the user must trust the backend.

`OPENAI_API_KEY` remains optional and is used only by the backend CLI diagnostic below. It is not
required and is ignored by the browser BYOK flow.

The CLI remains available for a deliberate single-candidate diagnostic:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run tail-radar research `
  --candidate-id <candidate-uuid> `
  --analysis-as-of "2026-08-28T14:35:00+08:00"
```

Do not pass keys on the command line and never use `VITE_*` for secrets. Identical attempts are
cached before the external call; `--force` deliberately creates another paid attempt. Provider
timeouts, rate limits, API errors, invalid structured output, and no-evidence results remain local
to that candidate and do not change the Tail Radar run.

## Deterministic Tail Radar workflow

Apply migrations before the first complete run. Workflow version 2 combines live market data,
quality validation, screening, and deterministic intraday analysis. It deliberately makes zero
OpenAI calls, regardless of candidate count:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run tail-radar workflow `
  --intended-snapshot-time "2026-08-31T14:30:00+08:00"

uv run tail-radar resume `
  --workflow-run-id <workflow-run-uuid>
```

Resume reuses completed snapshot, screening, and technical work. AI remains pending until a user
explicitly confirms one candidate in its detail page. Public `/api/v1` routes remain read-only; the
single paid action lives under the separate `/api/internal/v1` operational boundary and requires a
request-scoped user OpenAI key.

## Scheduled worker operations

Compose starts `worker` as a separate service from the same backend image after the one-shot
`migrate` service has applied migrations. The worker writes liveness to
`runtime/worker/tail-radar-heartbeat.json` and handles SIGTERM/SIGINT. FastAPI does not host the
scheduler. Useful PowerShell commands are:

```powershell
docker compose ps worker
docker compose exec worker tail-radar worker-health --max-age-seconds 30
docker compose exec worker tail-radar scheduled-status
docker compose logs --tail 100 worker

# Native backend equivalents
Set-Location backend
uv run tail-radar worker-once
uv run tail-radar scheduled-status
uv run tail-radar scheduled-retry --trade-date 2026-08-31
```

The official intended slot is fixed at 14:30:00 Asia/Shanghai. The checked-in defaults preflight 60
seconds earlier, poll every five seconds, and allow an initial start at most 30 seconds late. A later
startup is persisted as `missed`; it does not fetch a live snapshot. Preflight checks the provider
calendar and declared market capabilities but intentionally avoids a second full-market request.

If an official snapshot was captured before a later technical failure, `scheduled-retry` resumes
incomplete deterministic analysis and reuses success. It never starts AI research. If the snapshot
provider failed or the slot was missed, an official
retry is impossible because a later live response cannot reproduce 14:30. Operators may use the
existing `market-snapshot ... --force` and `tail-radar research ... --force` diagnostics, but those
outputs stay explicitly non-official/forced.

## Adding work

1. Read `AGENTS.md`, relevant architecture docs, and accepted ADRs.
2. Add provider-independent rules in the feature domain; put SDK code only in adapters.
3. Keep routes limited to input/output translation and service invocation.
4. Preserve timezone-aware `as_of` values throughout historical work.
5. Publish cross-module results as versioned research artifacts.
6. Add an Alembic revision for every database schema change.
7. Run the relevant quality gates and update documentation or ADRs for durable decisions.
