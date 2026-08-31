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
in a named volume, and bind-mounts `runtime/` for immutable market datasets. Stop it with:

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
no recurring scheduler.

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

## Manual OpenAI research diagnostic

Normal development, CI, and tests do not need an OpenAI key. To make one deliberate paid research
request, set a newly generated `OPENAI_API_KEY` only in the root `.env`, apply migrations, and run:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run tail-radar research `
  --candidate-id <candidate-uuid> `
  --analysis-as-of "2026-08-28T14:35:00+08:00"
```

Do not pass keys on the command line and never use `VITE_*` for secrets. The command analyzes one
candidate, prints structured JSON, and is not exposed by public HTTP routes. Identical attempts are
cached before the external call; `--force` deliberately creates another paid attempt. Provider
timeouts, rate limits, API errors, invalid structured output, and no-evidence results remain local
to that candidate and do not change the Tail Radar run.

## Complete Tail Radar workflow

Apply migrations before the first complete run. The workflow intentionally combines live market
data and paid AI research, so use it only with a valid local `.env` and during an intended A-share
snapshot window:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run tail-radar workflow `
  --intended-snapshot-time "2026-08-31T14:30:00+08:00"

uv run tail-radar resume `
  --workflow-run-id <workflow-run-uuid>
```

Resume reuses completed snapshot, screening, technical, and paid research work. A failed AI attempt
is also cached and is retried only when `--retry-failed-research` is supplied deliberately. Public
HTTP routes and the frontend remain read-only; neither can start live or paid execution.

## Adding work

1. Read `AGENTS.md`, relevant architecture docs, and accepted ADRs.
2. Add provider-independent rules in the feature domain; put SDK code only in adapters.
3. Keep routes limited to input/output translation and service invocation.
4. Preserve timezone-aware `as_of` values throughout historical work.
5. Publish cross-module results as versioned research artifacts.
6. Add an Alembic revision for every database schema change.
7. Run the relevant quality gates and update documentation or ADRs for durable decisions.
