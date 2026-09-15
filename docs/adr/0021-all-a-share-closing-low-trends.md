# ADR 0021: All A-share scans ending at a new closing low

- Status: Accepted
- Date: 2026-09-15
- Amends the strategy/universe in ADR 0015/0016; retains ADR 0018/0019 execution/publication

The owner clarified that the latest 7–9 trading closes must form a decline, allowing at most two
upward days without a 1.5% amplitude cap, and that the final close must be the lowest. The former
Top-300 universe omitted desired stocks before evaluation. Attention is now a presentation priority.

## Decision

Use the latest completed exchange session as the endpoint. Examine 9, then 8, then 7 consecutive
closing observations (N prices, N-1 internal comparisons), keeping the longest valid window. Require
a strictly new closing low at the endpoint, a negative OLS slope, no flat adjacent closes, and at
most two positive daily changes. All remaining changes must be negative. Percentage changes within
1e-8 of zero count as flat rather than creating artificial declines. The optional rebound cap defaults
to null; an explicit numeric configuration can retain a stricter local cap. Volume comparisons and
the strong-contraction badge remain separate from these price conditions; required valid history,
nonzero volume and calendar continuity checks still apply.

Fetch an independent Shanghai/Shenzhen/Beijing A-share security list through the adapter's isolated
AKShare `stock_info_a_code_name` operation. Reject empty, duplicate, obviously incomplete or
exchange-missing universes; never silently substitute an attention Top-300 list. Fetch same-session
attention observations, rank available scores over the listed universe, and left-join them onto all
listed stocks. Missing attention does not exclude a stock: score/date are null and rank 0 explicitly
means unavailable, displayed as “暂无关注度排名”. No score is invented. A completely unavailable heat
feed, invalid list or stale heat remains a global error. Listing and provider failures keep bounded
attempts and logs; per-stock isolation, saved progress and existing failure thresholds remain.

`TREND_TOP_N` now controls the attention priority/highlight threshold (default 300), never scan size.
Within successful candidates, the attention Top-N group comes first, followed by the existing volume
ordering; attention and strong volume have separate badges. `requested_count` is the entire listed
universe; `heat_universe_count` counts available ranked observations. Missing latest bars, suspensions
and insufficient history are not invented or silently treated as valid downtrends.

Persist `rule_version: 2` and `universe_scope: all_a` in each run's configuration JSON. Public
parameters carry those fields, and absent fields identify historical rule 1 / top_heat scans. Shared
ResearchArtifact payloads use schema version 3. No SQL column/table changes are required. Preserve
historical runs and immutable candidate evidence; re-exporting does not re-screen an old run. Re-run
collection to produce a new strategy result, then publish it and the updated frontend normally.

The full-market job is longer than a Top-300 job; existing manual/scheduled lifecycle remains.
No public scan control or new remote authority is added. Runtime market data stays outside Git.

Source for the list operation: [AKShare implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_info.py).
