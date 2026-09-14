# Trend Radar verification — local operator / read-only website

## 2026-09-14: saved candidate charts (ADR 0019)

- Existing completed real scan was re-exported without provider calls: 18 candidates, 59 saved bars
  each (1,062 total). The details JSON is 259,340 bytes; the complete public ZIP is 39,603 bytes.
  The ZIP installed successfully through the same validator used by the static website workflow.
- Backend full regression: 210 tests passed against disposable PostgreSQL. Four additional bundle
  checks then passed for malformed prices, future dates, missing details and legacy compatibility.
  The publication suite totals 14 passing tests. Cache-refresh regression confirms exported charts
  retain the original candidate input bars. Ruff format/lint and Mypy src/tests (161 files) passed.
- Frontend: 27 tests, ESLint, TypeScript, Prettier and Docker production build passed. Tests cover
  direct links, missing older exports, unknown symbols, identity/date/price validation and trailing
  moving averages. The local backend and frontend containers were rebuilt and are healthy.
- Real browser verification: stock-name navigation, two different candidate pages, direct refresh,
  same-run return, candlesticks/MA lines/trend shading, linked volume zoom and a 59-row daily table.
  At 390px mobile width the page fits without horizontal overflow; the wide table scrolls inside
  its panel. Opening a stock from the bottom of the list starts its detail page at the top.
  Chart volume-axis tick density was reduced after visual inspection. No browser console errors.
- This change publishes canonical saved candidate bars only. It does not extend the saved lookback
  or refresh prices when a visitor clicks. Older bundles explain re-export; no public deployment
  or Release upload was performed. Local usage is documented in trend-radar.md.

## Earlier verification: initial static publication

Verified on 2026-09-13 (Asia/Shanghai), for ADR 0016. This record replaces the earlier
Supabase setup verification; those cloud deployment requirements no longer apply.

## Completed

- Backend: 190 tests passed with real PostgreSQL, including the existing feature regression suite.
  Tests used an isolated disposable database, including a second disposable database for Trend
  Radar migrations/locking/schedule claims. The test databases were removed after execution.
- Ruff lint and format passed; Mypy passed for `src tests` (159 source files).
- Alembic upgraded the local existing database from revision 0008 through 0009 and 0010 without
  deleting existing evidence. `alembic check` reported no new upgrade operations.
- Frontend: 13 tests passed; ESLint, TypeScript, Prettier and production build passed.
- Docker backend and frontend images built successfully. PostgreSQL, backend and frontend started
  successfully and passed their health checks. The desktop action script's Initialize and Export
  operations were exercised against this stack using Windows PowerShell.
- The Windows Forms control script passed PowerShell parsing and control-instantiation smoke checks.
  It exposes local Prepare, Scan, Export, Publish and View operations; there is no local HTTP
  control server. The GUI's actual button click was not automated.
- Real Nginx checks: exported index GET returned 200; POST, PUT and DELETE returned 403.
  A discovered owner-only file permission issue was fixed: public JSON uses mode 0644 so the
  separate Nginx user can read it. Atomic result-before-index publication remains intact.
- Browser checks in headless Edge: real empty initial publication; old admin URL redirects to the
  read-only page; 1440px desktop and 390px mobile result cards and filters worked with synthetic
  fixtures; no horizontal overflow, page errors, write requests, scan buttons or admin links.
  Synthetic fixtures and screenshots stay in ignored `runtime/qa/`, outside the public directory.
- Public export tests verify preservation of the last success after failure, private configuration
  exclusion, repair after an export failure without a market call, and index preservation on a
  failed write. ZIP validation rejects extra/traversal paths before installation.
- The deployment downloader was checked with simulated initial absence, required missing data,
  service failure, missing asset and successful download. No GitHub token or release was created.
- Supabase SDK, adapter, migrations, browser login/request functions and environment wiring were
  removed. ADR 0015 is retained only as a superseded architectural record.

## Operational status and limits

The local read-only website is available at `http://localhost:8080/#/trend-radar`. The exported
index is empty until the operator performs the first successful scan. This revision did not run
an unsolicited live Top-300 scan or place synthetic results in the public dataset. The complete
scan service was exercised against deterministic market fixtures and real PostgreSQL.

No public release upload or GitHub Pages deployment was performed. GitHub CLI is not installed on
this machine; the operator must install/login and deploy the new workflow to main before using
Publish. A submitted workflow is not proof of a successful public deployment. Local-only operation
requires none of this setup and does not require a Supabase account.
