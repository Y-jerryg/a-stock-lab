# A-Stock Lab

A-Stock Lab is a production-oriented personal A-share market research platform. Phase 0 established
the modular monolith, database contracts, runtime, observability, frontend shell, and delivery
tooling. Phase 1 adds provider-neutral market-data infrastructure, an isolated AKShare adapter,
quality-gated full-market snapshots, and opt-in Parquet diagnostics. Phase 2 adds the manual,
point-in-time execution engine, provider-neutral trading calendar, PostgreSQL snapshot manifests,
and idempotent official-run semantics. Phase 3 adds the deterministic, point-in-time
`tail-radar-screen-v1` rule, auditable candidate artifacts, and public read-only result APIs. Phase 4
adds versioned point-in-time intraday features without a trading score or prediction. Phase 5 adds
backend-only, point-in-time OpenAI web research with separately persisted sources and paid-call
idempotency. It deliberately contains no recurring scheduler or simulated results.

## Modules

- **Tail Radar** — deterministic point-in-time full-market snapshot screening
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

## Point-in-time snapshot execution

Apply migrations before using the Phase 2 commands. These commands make live calendar and market
provider calls; they are manual operations and are not run by CI:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run market-snapshot execute-now
$shanghaiDate = [DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(8)).ToString('yyyy-MM-dd')
uv run market-snapshot execute-at "$($shanghaiDate)T14:30:00+08:00"
uv run market-snapshot execute-at "$($shanghaiDate)T14:30:00+08:00" --force
uv run market-snapshot inspect --run-id <run-uuid>
uv run market-snapshot inspect --snapshot-id <snapshot-uuid>
```

An official execution is unique by job type, Shanghai trade date, intended timestamp, and execution
version. Repeating it returns the existing run without another provider call. `--force` creates an
explicit non-official rerun; it does not overwrite or supersede the official manifest. The supplied
timestamp must include an offset, cannot be in the future, and must be on the actual Shanghai
execution date because the live feed cannot reconstruct an earlier market state.

## Deterministic Tail Radar screening

After an official snapshot has been persisted, screen that immutable snapshot explicitly:

```powershell
Set-Location backend
uv run tail-radar execute --snapshot-id <snapshot-uuid>
uv run tail-radar inspect --run-id <tail-radar-run-uuid>
uv run tail-radar analyze-intraday --candidate-id <candidate-uuid> --analysis-as-of "2026-08-28T14:35:00+08:00"
```

Version `tail-radar-screen-v1` includes a valid normalized record only when
`2.00 <= pct_change <= 3.00`. Repeating the same snapshot/rule pair is idempotent. The command makes
no live provider or AI call; public `/api/v1/tail-radar` routes only read persisted runs and
candidates. See [Tail Radar documentation](docs/tail-radar.md).

## Manual OpenAI web research diagnostic

This is an explicit paid operation for one persisted candidate. Put a newly generated API key only
in the ignored root `.env`; never put it in source, `VITE_*`, a command argument, or frontend code:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run tail-radar research `
  --candidate-id <candidate-uuid> `
  --analysis-as-of "2026-08-28T14:35:00+08:00"
```

The identity `(candidate, run, analysis_as_of, prompt_version, provider, requested_model)` is
claimed in PostgreSQL before the Responses API call. Repeating it returns the persisted result,
including a failed or no-evidence attempt, without another paid call. Use `--force` only when a new
paid attempt is intentional. Normal tests mock OpenAI and never use the network. See
[Tail Radar documentation](docs/tail-radar.md) for timestamp and source-integrity rules.

## Complete Tail Radar workflow and UI

After applying the latest migration, an internal operator can execute or resume the complete
point-in-time workflow:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run tail-radar workflow `
  --intended-snapshot-time "2026-08-31T14:30:00+08:00"
uv run tail-radar resume --workflow-run-id <workflow-run-uuid>
```

Resume skips completed deterministic work and completed or no-evidence paid research. Retrying a
failed paid attempt requires the explicit `--retry-failed-research` flag. The Tail Radar browser UI
is read-only and uses hash routes, preserving static GitHub Pages compatibility. It renders only
persisted snapshot evidence, deterministic calculations, and separately labelled AI interpretation;
it never starts a scan or receives backend secrets.

## Quality commands

```powershell
./scripts/lint.ps1
./scripts/test.ps1
```

See [development guidance](docs/development.md), [architecture](docs/architecture.md), and the
[accepted decision records](docs/adr/) before major changes.
