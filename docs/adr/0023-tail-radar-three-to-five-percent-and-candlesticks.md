# ADR 0023: Tail Radar 3–5 percent screening and saved intraday candlesticks

- Status: Accepted
- Date: 2026-09-16
- Supersedes: ADR 0008 default screening range only

New screenings use `tail-radar-screen-v2` and the inclusive range `3.00 <= pct_change <= 5.00`.
Keep v1 (2–3 percent) configurations readable and reproducible. Validate that persisted rule
versions match their ranges. The existing snapshot/rule uniqueness gives each version an independent
run; do not rewrite past candidates or turn late quotes into historical official snapshots.
The scheduler's next captured snapshot uses v2. Already screened workflows retain their candidate set.
No database schema or ResearchArtifact shape changes are needed.

Candidate details render the existing persisted, cutoff-filtered five-minute OHLC bars as unadjusted
candlesticks, with a linked volume histogram. Internal volume is shares; the axis displays ten-thousand
shares and the tooltip shows exact shares and RMB amount. Red denotes rising bars and green falling
bars. This replaces the close-price line, adds linked zoom, and does not fetch quotes on public reads
or add future bars to the analysis. Old artifacts without saved bars keep an explicit empty state.
Daily K lines in Trend Radar remain a separate saved series with their existing adjustment semantics.
