# ADR 0026: Supplementary daily reference charts for Tail Radar

- Status: Accepted
- Date: 2026-09-17
- Extends: ADR 0020; no database schema change

Tail candidates retain immutable intraday snapshots and analysis evidence. Add a separate public
GET `/api/v1/tail-radar/candidates/{id}/daily-chart` for supplementary historical daily candles.
Validate candidate identity through the existing query service before any provider request.
Unlike saved research GETs, this quote endpoint may collect external daily data on a cache miss.
It never invokes AI, modifies screening, or feeds these later-fetched quotes into ResearchArtifacts.

Use the existing isolated daily market adapter and its provider-neutral contract rather than
introducing market SDK imports into application logic. The chart service excludes the snapshot's
unfinished trading day, uses Asia/Shanghai dates, returns explicit cutoff and acquisition timestamps,
and marks its purpose `reference_only`. Current provider qfq revisions are reference quotes, not
proof of information available at the original snapshot. The UI makes that distinction visible.

Cache normalized quotes by symbol/cutoff for one day in the mounted runtime directory. Retain at
most 120 candles per entry, 6,000 entries and 30 days of files. Writes use atomic replacement;
corrupt/expired files are cache misses. Serialize cache misses, reject excess requests with 429,
and bound provider attempts/timeouts; always close its child processes. Existing intraday/detail
reads and AI actions remain independent of supplementary chart errors. No runtime quotes enter Git.

Share the daily chart rendering component (candles, volume, trailing MAs) between both features.
Store list pagination/filter/sort state in route query parameters and carry it through detail links,
so explicit return links, browser Back and reload retain the list state. Filter changes reset page.

The PC tunnel startup now tests actual HTTPS availability, recreates an unhealthy tunnel once,
and publishes the verified address. AI enablement is optional for public reads. Quick Tunnel remains
an operator-started testing connection, not a permanent domain or automatic unattended recovery.
