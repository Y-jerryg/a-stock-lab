# Market data infrastructure

Phase 1 implements the provider boundary and full-market snapshot ingestion infrastructure. Phase 2
adds manual point-in-time execution, a provider-neutral trading calendar, Parquet checksums, and
PostgreSQL run/manifest persistence. Phase 3 consumes verified official snapshots for deterministic
Tail Radar screening. Phase 4 adds provider-neutral unadjusted five-minute bars for explicit
candidate analysis. Recurring scheduling, bulk intraday persistence, daily history, and
security-master ingestion remain unimplemented.

## Dependency boundary

`MarketDataProvider` is the application-facing contract. Its capability vocabulary reserves
full-market snapshots, intraday bars, daily bars, security master, and trading calendar without
pretending unsupported feeds exist. `AkShareMarketDataProvider` declares and implements
`full_market_snapshot` and `intraday_bars`.

All AKShare imports, Chinese source-column mappings, SDK exception handling, and provider metadata
live in the `shared/market_data/adapters/akshare*.py` adapter modules. Provider-neutral service and
quality code consume only normalized models. Adding another provider must implement the contract
and normalization in a new adapter; it must not add provider branches to domain or feature code.
This implements the existing decision in [ADR 0004](adr/0004-provider-interfaces.md).

The adapter calls AKShare's documented `stock_zh_a_spot_em` interface, which returns the full
Shanghai, Shenzhen, and Beijing A-share snapshot in one logical operation. The current upstream
schema is documented by [AKShare](https://akshare.akfamily.xyz/data/stock/stock.html#id3).

## Normalized snapshot

Every accepted record contains a six-digit symbol, exchange when it can be inferred reliably, name,
price and change fields, OHLC/previous close, volume and amount, amplitude, volume ratio, turnover,
valuation fields, market-cap fields, provider provenance, provider timestamp, and fetch timestamp.
Numeric placeholders such as `-` become `null`; values are never invented. The selected AKShare
interface does not provide a genuine observation timestamp, so `provider_timestamp` remains `null`.
`fetched_at` and all manifest timestamps are timezone-aware `Asia/Shanghai` values.
Provider-normalized `fetched_at` values must fall inside the service-observed fetch start/finish
window; an adapter cannot label cached or future rows as part of the current call.

Prices, changes, amounts, and market caps retain their documented RMB units. Percentage fields use
percentage points (for example `1.5` means 1.5%), not decimal fractions. The adapter converts
AKShare's volume from lots (`手`) to shares so the internal `volume` field has a provider-independent
unit. `volume_ratio`, PE, and PB remain dimensionless ratios.

Exchange inference is provider-independent and intentionally narrow: `6xxxxx` maps to Shanghai,
`0xxxxx`/`3xxxxx` to Shenzhen, and established `4xxxxx`/`8xxxxx`/`92xxxx` families to Beijing.
Anything else remains unknown instead of being guessed.

An accepted provider snapshot has a UUID, provider, actual fetch start/end times, monotonic latency,
record count, schema version, provider metadata/version, legitimate provider timestamp, and a
quality report. A failing provider batch raises
`MarketDataQualityError`; it cannot be represented or persisted as an official snapshot.

## Quality policy

Defaults are explicit environment settings rather than hidden constants:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `MARKET_SNAPSHOT_MIN_RECORDS` | `4000` | Minimum normalized rows; deliberately below the current universe but high enough to catch partial pagination |
| `MARKET_SNAPSHOT_MAX_DUPLICATE_SYMBOLS` | `0` | Maximum extra rows sharing an already-seen symbol |
| `MARKET_SNAPSHOT_MAX_MISSING_SYMBOL_RATIO` | `0.001` | Missing-symbol rows divided by upstream rows |
| `MARKET_SNAPSHOT_MAX_INVALID_PRICE_RATIO` | `0.005` | Unparseable or non-positive prices divided by normalized rows |
| `MARKET_SNAPSHOT_MAX_INVALID_PCT_CHANGE_RATIO` | `0.005` | Unparseable or implausible percentage changes divided by normalized rows |
| `MARKET_SNAPSHOT_MAX_MALFORMED_ROW_RATIO` | `0.01` | Rows with any normalization issue divided by upstream rows |
| `MARKET_SNAPSHOT_MAX_ABS_PCT_CHANGE` | `1000` | Maximum plausible absolute percentage value before it is invalid |

Unavailable numeric fields are not automatically malformed: suspended securities can legitimately
lack live values. Non-numeric garbage is malformed and remains `null`. Missing/invalid symbols cause
the row to be omitted and reported. Duplicate, price, percentage, missing-symbol, malformed-row, and
low-count metrics are all retained in the manifest.

Threshold changes alter which data is considered official and should be reviewed like business
rules. The defaults are safety floors, not evidence that AKShare is sufficiently reliable for the
14:30 workflow; the live diagnostic exists to collect that evidence.

## Reliability and errors

The error hierarchy distinguishes provider unavailability, provider timeout, invalid provider
responses, and quality rejection. AKShare applies a timeout and retry behavior to its individual
paginated HTTP requests. The adapter maps those terminal errors and, by default, allows only two
full-call attempts in total with a five-second delay. These settings are bounded to prevent an
aggressive loop:

- `MARKET_DATA_RETRY_ATTEMPTS` (default `2`, maximum `3`)
- `MARKET_DATA_RETRY_DELAY_SECONDS` (default `5`, maximum `60`)

Invalid schemas and quality failures are not retried. A single high-level snapshot call can span
many paginated requests, so the diagnostic reports end-to-end monotonic latency rather than
pretending the SDK's per-request timeout is a whole-operation deadline.

## Live diagnostic and persistence

From `backend/`:

```powershell
uv run market-data-diagnostic
uv run market-data-diagnostic --samples 10
uv run market-data-diagnostic --repeat 3 --interval-seconds 120
uv run market-data-diagnostic --persist
```

The command emits one JSON object per observation with success/failure, request timestamps, latency,
record count, quality metrics, and normalized samples. This makes redirected output suitable for
repeated empirical observations. It is manual and excluded from CI; unit tests inject fake tabular
responses and never make network calls.

Provider, quality, and persistence failures have distinct status and error types. A persistence
failure retains the successful fetch timing, count, and quality report in the diagnostic output.

Diagnostic persistence is opt-in only. Accepted snapshots are written with Zstandard compression
and atomically published without replacing an existing snapshot ID to
`runtime/market-data/YYYY-MM-DD/full-market-<snapshot-id>.parquet`. The complete manifest is embedded
in Parquet schema metadata under `a_stock_lab.snapshot_manifest`. Writes return a relative storage
key, SHA-256 checksum, and byte size. The entire runtime tree is ignored by Git and bind-mounted by
Docker for persistence outside the container layer. Failed writes remove their uniquely named
temporary file before returning an error.

## Trading calendar

`TradingCalendar` is independent of the market quote provider contract. The first adapter uses
AKShare's Sina trading-date history and normalizes it into a provider-neutral `TradingDay`. Dates
missing inside authoritative coverage are closed, including weekday holidays; a Monday-Friday rule
is never treated as sufficient. Requests outside authoritative coverage fail rather than guessing.
The fetched calendar is cached for the life of one command invocation.

The current AKShare calendar function does not expose a request-timeout parameter. Phase 2 keeps the
operation manual and maps terminal SDK/network failures, but a provider with a controllable timeout
is still required before this adapter is used by unattended scheduling.

## Point-in-time execution and manifests

The execution engine preserves five distinct aware `Asia/Shanghai` timestamps:

- `intended_snapshot_time`
- `actual_fetch_started_at`
- `actual_fetch_finished_at`
- `provider_timestamp`, only when the upstream genuinely supplies one
- `persisted_at`

Official identity is `(job_type, trade_date, intended_snapshot_time, execution_version)` and is
enforced by PostgreSQL. A duplicate official command returns its existing run and manifest without
calendar, quote-provider, or storage calls. `--force` creates a non-official run and links it to the
official run when present; neither rows nor manifest references are overwritten. The durable
identity and filesystem/database coordination rules are recorded in
[ADR 0007](adr/0007-point-in-time-snapshot-execution.md).

The engine first commits a running claim, then checks the provider-backed calendar, fetches and
quality-gates the snapshot, writes Parquet, and atomically commits the PostgreSQL manifest plus
successful run status. Provider, calendar, quality, and persistence failures mark the claimed run
failed. A file is retained after manifest registration begins if commit outcome is uncertain, since
deleting it could break a manifest that actually committed.

Manual commands from `backend/`:

```powershell
uv run market-snapshot execute-now
$shanghaiDate = [DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(8)).ToString('yyyy-MM-dd')
uv run market-snapshot execute-at "$($shanghaiDate)T14:30:00+08:00"
uv run market-snapshot execute-at "$($shanghaiDate)T14:30:00+08:00" --force
uv run market-snapshot inspect --run-id <run-uuid>
uv run market-snapshot inspect --snapshot-id <snapshot-uuid>
```

The explicit timestamp must include an offset, may not be later than execution start, and must fall
on the actual Shanghai execution date. The live full-market feed cannot honestly backfill an earlier
date. These are manual operational commands; no scheduler or public execution API exists.

Phase 3's separate `tail-radar` command reads one registered Parquet artifact by snapshot UUID,
verifies its checksum and embedded manifest, and makes no provider or network request. See
[Tail Radar documentation](tail-radar.md).

## Intraday bars

Phase 4 uses AKShare's documented `stock_zh_a_hist_min_em` adapter operation with `period="5"` and
no price adjustment. Provider timestamps are interpreted as completed bar ends in
`Asia/Shanghai`. The adapter maps Chinese columns into normalized OHLC, volume, and amount fields;
AKShare documents volume in lots, so the adapter converts it to shares while retaining amount in
RMB. See the [official AKShare stock-data documentation](https://akshare.akfamily.xyz/data/stock/stock.html).

The provider request ends at the explicit analysis `as_of`, but the domain engine independently
filters every normalized bar with `ended_at > analysis_as_of`. This defense remains mandatory even
when the upstream claims to honor its end parameter. Intraday rows are not persisted as a new bulk
dataset in this phase; the feature artifact preserves provider/request provenance and the latest bar
actually used.
