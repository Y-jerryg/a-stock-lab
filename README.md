# A-Stock Lab

Trend Radar scans all listed A-shares for latest 9–8–7-session declines ending at a new closing low,
with at most two rebound days. Attention Top-300 candidates are highlighted alongside independent
volume-contraction labels. It uses local PostgreSQL, a Windows operator window for scans, and
a Chinese read-only website backed by exported static results. No Supabase account is required.
See [Trend Radar setup and operations](docs/trend-radar.md) and
[ADR 0016](docs/adr/0016-trend-radar-local-control-static-publication.md).
The [verification record](docs/trend-radar-verification.md) lists checks actually run and deployment
steps that still require configured infrastructure.

日常使用请双击根目录 `Start-Guide.cmd` 打开[两个雷达完整离线指南](docs/user-guide.html)。
中文说明：[本机使用与网站分享](docs/usage-and-sharing.md)。之前的扫描修复见
[趋势雷达修复验证](docs/trend-radar-repair-2026-09-13.md)。
全市场范围与最新下降趋势规则见 [2026-09-15 验证记录](docs/trend-radar-rule-verification-2026-09-15.md)。

A-Stock Lab is a production-oriented personal A-share market research platform. Phase 0 established
the modular monolith, database contracts, runtime, observability, frontend shell, and delivery
tooling. Phase 1 adds provider-neutral market-data infrastructure, an isolated AKShare adapter,
quality-gated full-market snapshots, and opt-in Parquet diagnostics. Phase 2 adds the manual,
point-in-time execution engine, provider-neutral trading calendar, PostgreSQL snapshot manifests,
and idempotent official-run semantics. Phase 3 adds the deterministic, point-in-time
`tail-radar-screen-v1` rule, auditable candidate artifacts, and public read-only result APIs. Phase 4
adds versioned point-in-time intraday features without a trading score or prediction. Phase 5 adds
backend-only, point-in-time OpenAI web research with separately persisted sources and paid-call
idempotency. Phases 6 and 7 add resumable orchestration and the evidence-separated read UI. Phase 8
adds a separate database-coordinated 14:30 Asia/Shanghai worker. The platform never uses simulated
financial results.

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

The separate [GitHub Pages workflow](.github/workflows/pages.yml) derives the Pages base path,
requires the repository Actions variable `VITE_API_BASE_URL`, validates the browser bundle, and
deploys only `frontend/dist`. Configure **Settings → Pages → Build and deployment → Source → GitHub
Actions**. The repository intentionally contains no production backend URL; see
[GitHub Pages deployment](docs/github-pages.md).

## Database migrations

```powershell
Set-Location backend
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
uv run alembic downgrade -1
```

Every schema change must include and review an Alembic migration. Local Compose runs one one-shot
`migrate` service after PostgreSQL is healthy; API and worker start only after it succeeds, avoiding
concurrent migration runners. Production should keep migration as an explicit release step.

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

## Deterministic workflow, UI, and on-demand AI

After applying the latest migration, an internal operator can execute or resume the complete
point-in-time workflow:

```powershell
Set-Location backend
uv run alembic upgrade head
uv run tail-radar workflow `
  --intended-snapshot-time "2026-08-31T14:30:00+08:00"
uv run tail-radar resume --workflow-run-id <workflow-run-uuid>
```

Workflow version 2 runs the official snapshot, screening, and deterministic intraday analysis only.
It never batches OpenAI calls, so the first run costs no OpenAI fees regardless of candidate count.
The Tail Radar browser uses hash routes, preserving static GitHub Pages compatibility. It presents
snapshot evidence in a board-filterable table with activity, size, and intraday fields.

Optional AI research begins only after a user opens one candidate, enters their own OpenAI API key,
checks the cost confirmation, and submits that one stock. The site only needs
`TAIL_RADAR_ON_DEMAND_RESEARCH_ENABLED=true`; the request-scoped key stays in page memory, passes
through the backend, and is never persisted. Never place a key in `VITE_*`. Successful identical
research is served from cache, while a failed attempt requires a separate explicit retry
confirmation. Non-local deployments must use HTTPS and a trusted backend.

## Official 14:30 worker

Docker Compose runs the scheduler as a separate `worker` service using the backend image; FastAPI
does not run background scheduling. The worker consults the provider-neutral trading calendar,
preflights shortly before 14:30, and stores `missed` if it cannot begin the official live capture
within the configured 30-second window.

```powershell
docker compose ps worker
docker compose exec worker tail-radar scheduled-status
docker compose exec worker tail-radar worker-health --max-age-seconds 30
docker compose logs --tail 100 worker
```

Database uniqueness and an advisory lock prevent duplicate official execution. A restart resumes
nonterminal deterministic work without making paid research calls. Analysis can be retried only when an
official snapshot exists; a missed or failed initial capture cannot be reconstructed from a later
live response. Operational commands remain backend-only and are not exposed by the public API or UI.

## Quality commands

```powershell
./scripts/lint.ps1
./scripts/test.ps1
```

See [development guidance](docs/development.md), [architecture](docs/architecture.md), and the
[accepted decision records](docs/adr/) before major changes.
