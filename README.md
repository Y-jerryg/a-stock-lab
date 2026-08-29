# A-Stock Lab

A-Stock Lab is a production-oriented personal A-share market research platform. Phase 0 established
the modular monolith, database contracts, runtime, observability, frontend shell, and delivery
tooling. Phase 1 adds provider-neutral market-data infrastructure, an isolated AKShare adapter,
quality-gated full-market snapshots, and opt-in Parquet diagnostics. It deliberately contains no
Tail Radar screening, trading rules, AI calls, or simulated financial results.

## Modules

- **Tail Radar** — point-in-time late-session market research (implementation begins after Phase 0)
- **Intelligence** — daily market and company intelligence (reserved)
- **Quant Lab** — historical quantitative research (reserved)
- **AI Research Assistant** — future assistant grounded in artifacts from the other modules

## First local startup (Docker, recommended)

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

For source mounts and hot reload after creating `.env`, run `./scripts/dev.ps1` or:

```powershell
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

Visit:

- Frontend development server: <http://localhost:5173>
- Backend health: <http://localhost:8000/api/v1/health>
- Backend OpenAPI docs (development only): <http://localhost:8000/docs>
- PostgreSQL for local tools: `localhost:55432` with the supplied development template

For the production-style local images, run `docker compose up --build` and visit the frontend at
<http://localhost:8080>. Nginx proxies `/api` to the backend, so no browser-facing localhost API URL
is baked into the image.

`POSTGRES_HOST_PORT` controls only the port published on Windows. PostgreSQL continues listening on
port 5432 inside its container, and backend containers always connect through `postgres:5432`. The
template uses 55432 because this Windows machine reserves 5433 even when no process is listening.

## Local backend (PowerShell / Miniconda compatible)

Python 3.12 and PostgreSQL are required. The project uses `uv` for deterministic dependency locking,
but Docker never depends on Conda.

```powershell
Set-Location backend
uv sync --locked
uv run alembic upgrade head
uv run uvicorn a_stock_lab.main:app --reload
```

A normal Python 3.12 or Miniconda environment can instead run `python -m pip install -e .` to install
the application for direct debugging. The `uv` lockfile remains the maintained, reproducible
development and CI workflow. When `DATABASE_URL` is blank, native Python derives its connection from
the shared `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` values at
`localhost:${POSTGRES_HOST_PORT}`. Set `DATABASE_URL` only for a full explicit override.

## Local frontend

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
```

Only public configuration belongs in `VITE_*`. Set `VITE_API_BASE_URL` to the separately hosted API
origin for static production hosting and `VITE_BASE_PATH` to the GitHub Pages repository path (for
example `/a-stock-lab/`). Hash routing keeps direct navigation reliable on static hosts.

## Database migrations

```powershell
Set-Location backend
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
uv run alembic downgrade -1
```

Every schema change must include and review an Alembic migration. Containers apply committed
migrations on startup only after PostgreSQL reports healthy.

## Manual live market-data diagnostic

The live diagnostic is intentionally not part of tests or CI. It makes a real AKShare/Eastmoney
request and does not persist anything unless `--persist` is supplied:

```powershell
Set-Location backend
uv sync --locked
uv run market-data-diagnostic
uv run market-data-diagnostic --repeat 3 --interval-seconds 120
uv run market-data-diagnostic --persist
```

Successful and failed observations are emitted as JSON, including request timing, latency, record
count, quality metrics, and normalized samples. Persisted snapshots are written below
`runtime/market-data/`, which is ignored by Git. See [market-data documentation](docs/market-data.md)
for the contract, thresholds, failure semantics, and storage layout.

## Quality commands

```powershell
./scripts/lint.ps1
./scripts/test.ps1
```

See [development guidance](docs/development.md), [architecture](docs/architecture.md), and the
[accepted decision records](docs/adr/) before major changes.
