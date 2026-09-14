# ADR 0019: Publish saved candidate daily bars for stock detail pages

- Status: Accepted
- Date: 2026-09-14
- Amends: ADR 0016 and ADR 0018 public data scope

## Context

The operator requests clickable Trend Radar candidates with daily candlestick charts and detailed
metrics. The scanner already retains immutable candidate input bars in PostgreSQL. Fetching live
data on a click would change the evidence behind historical results and require a public backend.

## Decision

Publish the normalized saved OHLC, volume, amount, adjustment, source and collection timestamps for
candidate stocks only. This explicitly expands the earlier public bundle scope, which excluded all
bars. Do not publish raw SDK responses, the entire heat universe, internal failures or credentials.
Read trend_scan_results.input_bars, never the mutable daily cache. No new provider calls or schema
migrations are needed to add charts to existing scans with saved evidence.

Add version 1 details/<run-id>.json containing the allowlisted PublicRun, candidate metrics and saved
bars. Volume units are lots and amount units are CNY. Validate symbol, sequence, completed date and
as_of boundaries before export. Missing historical bars are shown as unavailable, not backfilled.
Index version 2 adds detail_schema_version: 1; existing summary result files stay at version 1.
Write details and result files before switching the index. Bundles include only manifest-declared
files, at most 203 entries (100 attempts plus an older latest completed run, two files each and index)
with the existing 50 MiB uncompressed bound. The installer accepts old bundles without details and
validates new identities and bar boundaries before writing anything.

The hash route /trend-radar/runs/:runId/stocks/:symbol reads same-origin static GET data, so direct
links and refreshes work on GitHub Pages. Keep the selected scan on return to the list. Use existing
ECharts for linked candlestick/volume panels, MA5/10/20, zoom and a shaded detected trend window.
Show latest saved OHLC, computed daily change, volume/amount, screening metrics, dated evidence and
a readable daily table. All prices are qfq; chart overlays are deterministic, not AI interpretation.

## Consequences

Existing saved candidates gain charts through re-export. Website visitors cannot trigger collection.
Public bundles become larger and include the candidate market evidence requested by the operator.
The number of available bars is limited to what that scan saved; no intraday or live quote is implied.
