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
in a named volume, and bind-mounts `runtime/` for future immutable datasets. Stop it with:

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

## Adding work

1. Read `AGENTS.md`, relevant architecture docs, and accepted ADRs.
2. Add provider-independent rules in the feature domain; put SDK code only in adapters.
3. Keep routes limited to input/output translation and service invocation.
4. Preserve timezone-aware `as_of` values throughout historical work.
5. Publish cross-module results as versioned research artifacts.
6. Add an Alembic revision for every database schema change.
7. Run the relevant quality gates and update documentation or ADRs for durable decisions.
