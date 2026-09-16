# ADR 0024: Incremental daily cache and bounded public trend history

- Status: Accepted
- Date: 2026-09-16
- Amends: ADR 0016, 0019 and 0021 cache/publication behavior

## Decision

Reuse the newest locally stored daily-bar vintage no later than the requested completed session,
and only when every observation was fetched by the current scan's as_of. Remove the six-hour,
same-vintage-only cache restriction. Keep the calculation window: max trend days plus baseline
volume days (29 sessions by default), using the exchange calendar, never weekday inference.
No database schema changes: the existing mutable trend_daily_bars table remains a local cache.

A complete window is reused without market requests. Missing sessions request a range starting
at the earlier of the first gap or the last three stored observations. Compare overlapping source,
adjustment, OHLC, volume and amount exactly; missing or changed overlap requires a full refresh of
the retained window. A full refresh also occurs when the oldest retained observation is at least
TREND_CACHE_REFRESH_DAYS old (default 7 calendar days), to pick up historical corrections beyond
the overlap. Provider retries, timeouts, stock isolation and calendar validation remain unchanged.
This is a bounded correction policy, not a guarantee against every upstream retrospective edit.
An adapter can still download more internally than its requested date range (notably Sina's SDK).

At scan start, remove cache bars older than the calculation window and superseded vintages;
successful updates replace the symbol's older cache vintages. Never prune immutable per-run
candidate inputs, research artifacts or scans. Historical research reads that saved evidence,
not today's mutable cache. Heat/universe observations still refresh for each new run. Tail Radar's
point-in-time intraday snapshots retain their existing behavior; past prices cannot stand in for
a new 14:30 snapshot.

Progress export writes the small index only when completed-run files already exist. Initial/final
and explicit exports still fully validate persisted results and evidence. This removes repeated
serialization of every historical chart after every ten stocks without weakening final validation.

Validate all immutable evidence before publishing only the final calculation window for each
chart. Keep the existing public schema and 50 MiB uncompressed archive limit. Before constructing
a bundle, budget the index and both files per completed run, retaining the newest completed runs
that fit; once an older completed run does not fit, omit it and older completed runs from the public
manifest/archive. Keep the latest complete run intact, including all its candidates. If the latest
alone exceeds the limit, fail locally without replacing the previous bundle. Database history and
local exported history remain available. Public historical links may expire as the budget fills.

Add independent presentation classification `max_pullback_pct <= 2%` (1e-8 numerical tolerance),
including zero-rebound candidates, and a 0/1/2 rebound-day filter. Combine it with existing volume,
trend-length and search filters. Do not change candidate inclusion or introduce a 2% hard cap.
Classification uses saved deterministic metrics and therefore works on existing exported runs.
