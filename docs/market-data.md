# Market data infrastructure

Phase 1 implements the provider boundary and full-market snapshot ingestion infrastructure. It does
not implement Tail Radar screening, scheduled ingestion, intraday history, daily history, security
master ingestion, or a trading-calendar feed.

## Dependency boundary

`MarketDataProvider` is the application-facing contract. Its capability vocabulary reserves
full-market snapshots, intraday bars, daily bars, security master, and trading calendar without
pretending those unimplemented feeds exist. `AkShareMarketDataProvider` currently declares and
implements only `full_market_snapshot`.

All AKShare imports, Chinese source-column mappings, SDK exception handling, and provider metadata
live in `shared/market_data/adapters/akshare.py`. Provider-neutral service and quality code consume
only normalized models. Adding another provider must implement the contract and normalization in a
new adapter; it must not add provider branches to domain or feature code. This implements the
existing decision in [ADR 0004](adr/0004-provider-interfaces.md).

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

Prices, changes, amounts, and market caps retain their documented RMB units. Percentage fields use
percentage points (for example `1.5` means 1.5%), not decimal fractions. The adapter converts
AKShare's volume from lots (`手`) to shares so the internal `volume` field has a provider-independent
unit. `volume_ratio`, PE, and PB remain dimensionless ratios.

Exchange inference is provider-independent and intentionally narrow: `6xxxxx` maps to Shanghai,
`0xxxxx`/`3xxxxx` to Shenzhen, and established `4xxxxx`/`8xxxxx`/`92xxxx` families to Beijing.
Anything else remains unknown instead of being guessed.

An official snapshot has a UUID, provider, request start/end times, monotonic latency, record count,
schema version, provider metadata, and a quality report. A failing provider batch raises
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

Persistence is opt-in only. Accepted snapshots are written atomically with Zstandard compression to
`runtime/market-data/YYYY-MM-DD/full-market-<snapshot-id>.parquet`. The complete manifest is embedded
in Parquet schema metadata under `a_stock_lab.snapshot_manifest`. The entire runtime tree is ignored
by Git and bind-mounted by Docker for persistence outside the container layer. Failed writes remove
their uniquely named temporary file before returning an error.
