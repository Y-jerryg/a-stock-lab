# GitHub Pages frontend deployment

GitHub Pages hosts only the compiled React/Vite files. It does not run FastAPI, the Tail Radar
worker, PostgreSQL, Alembic, AKShare, or OpenAI. Those components require a separately operated
backend environment with durable PostgreSQL and runtime artifact storage.

For the read-only Trend Radar module, a public backend and `VITE_API_BASE_URL` are optional.
Use the computer-side publication steps in [Trend Radar operations](trend-radar.md); the workflow
loads public JSON from the `trend-radar-data` release asset and never hosts a scan request API.

## Repository configuration for API-driven modules

1. Deploy the public backend first and determine its real HTTPS API origin. Do not use a placeholder
   or a localhost URL.
2. In the GitHub repository, open **Settings → Secrets and variables → Actions → Variables** and
   create the repository variable `VITE_API_BASE_URL` with that public HTTPS backend URL. This is a
   public browser build value, not a secret.
3. Open **Settings → Pages → Build and deployment → Source** and select **GitHub Actions**.
4. Ensure the separately deployed backend's `CORS_ORIGINS` includes the final GitHub Pages origin.
   CORS is browser policy, not authentication. The public data APIs remain read-only; the separate
   single-candidate research operation requires a user-supplied OpenAI key and explicit confirmation.

Never configure `OPENAI_API_KEY`, database credentials, provider credentials, or any other secret as
`VITE_*`. Vite replaces those variables into browser-delivered files. The Pages workflow allows an omitted API URL for static Trend Radar, but rejects a configured
non-HTTPS, credential-bearing, localhost, or loopback API URL before building.

## Workflow behavior

`.github/workflows/pages.yml` is separate from `.github/workflows/ci.yml`. On relevant pushes to
`main`, or an explicit manual dispatch, it:

1. derives `/` for an `<owner>.github.io` site or `/<repository>/` for a project site;
2. builds only `frontend/` with Node 22 and the locked pnpm dependencies;
3. verifies `dist/index.html` uses the derived asset base and scans the browser bundle for backend
   secrets and local API assumptions;
4. uploads only `frontend/dist` as the GitHub Pages artifact; and
5. deploys through the protected `github-pages` environment using GitHub's supported Pages actions.

The application uses `HashRouter`, so routes such as
`/<repository>/#/tail-radar/candidates/<id>` work without server rewrites. The frontend exposes no
market-scan or batch-analysis control. Its optional BYOK form keeps the user's key only in component
memory and sends it to the configured HTTPS backend for one candidate; the key is never compiled
into the Pages artifact. Users must trust that backend operator.

## Local production-equivalent build

Local development remains unchanged and may use `http://localhost:8000`. To validate project-site
asset paths without deploying, supply explicit temporary public build values in PowerShell:

```powershell
Set-Location frontend
if (-not $env:PRODUCTION_BACKEND_URL) { throw 'Set PRODUCTION_BACKEND_URL explicitly.' }
$env:VITE_API_BASE_URL = $env:PRODUCTION_BACKEND_URL
$env:VITE_BASE_PATH = '/a-stock-lab/'
pnpm install --frozen-lockfile
pnpm build
Select-String -Path dist/index.html -Pattern '/a-stock-lab/assets/'
```

API-driven modules require a real backend URL. Static Trend Radar can deploy with this variable
omitted; its public results and charts are loaded from the website's own files. First-time Windows
operators can follow [the Chinese publishing walkthrough](trend-radar-first-publish.md).
