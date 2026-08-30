# ADR 0009: Point-in-time deterministic intraday features

- Status: Accepted
- Date: 2026-08-29

## Context

Tail Radar candidates need reproducible intraday description without a composite score, trading
advice, or future-return prediction. Intraday providers can return out-of-order, duplicated,
incomplete, or later-than-requested bars. A historical analysis must never consume a bar that was
not complete at its explicit `analysis_as_of`.

## Decision

Add provider-neutral unadjusted five-minute bars to `MarketDataProvider`. A normalized bar timestamp
is the completed bar end in `Asia/Shanghai`; volume is shares and amount is RMB. AKShare-specific
arguments, source columns, lot-to-share conversion, retry behavior, and response normalization stay
inside the adapter.

Version the calculation as `tail-radar-intraday-v1` and the persisted feature schema as version 1.
Before any quality evaluation or calculation, exclude every bar whose `ended_at` is later than
`analysis_as_of`. Persist the number excluded. Any duplicate eligible timestamp invalidates
the computation instead of selecting one arbitrarily. Out-of-order bars are reported and sorted.
Missing session bars and malformed/off-session rows are reported; only features with sufficient
evidence are calculated. Day-extrema, path, and cumulative VWAP features require a complete sequence
from the 09:35 bar through the latest eligible bar, excluding the midday recess.

Returns use percentage points. Previous 5/15/30-minute returns compare the latest close with the
close one/three/six trading bars earlier. Return since open compares the latest close with the first
bar's open. Intraday position is `(close - low) / (high - low)`. VWAP is cumulative RMB amount divided
by cumulative share volume. Zero denominators produce `null`, never invented values.

Define the version-one descriptive conditions explicitly:

- `steady_strengthening`: complete path, at least seven bars, last seven closes non-decreasing,
  return since open at least 0.5%, and current drawdown from the day high no more than 0.3%.
- `late_acceleration`: the latest 15-minute return is at least 0.5% and exceeds the immediately
  preceding 15-minute return by at least 0.3 percentage points.
- `early_spike_followed_by_pullback`: complete path, first-30-minute high at least 1.0% above the
  opening price, and current price at least 1.0% below that early high.
- `recovery_from_intraday_weakness`: complete path, day low at least 0.5% below the opening price,
  current price at least 0.8% above the low, and normalized intraday position at least 0.6.
- `materially_below_earlier_intraday_peak`: complete path and current drawdown from the day high at
  least 1.0%.

Persist each result as a `tail_radar.intraday_features` `ResearchArtifact` with a relational link to
the candidate, Tail Radar run, and source snapshot. Preserve symbol, source IDs, candidate `as_of`,
analysis `as_of`, provider provenance, request window, latest bar used, versions, configuration,
features, path conditions, and quality report. Enforce idempotency on candidate, `analysis_as_of`,
and calculation version. The public candidate-detail API exposes only the latest persisted analysis;
execution remains an explicit internal CLI command.

## Consequences

Feature values are reproducible and safe from bar-level look-ahead. Incomplete evidence remains
visible instead of being filled or silently accepted. Future calculation or threshold changes need
a new calculation version and tests. No overall score, buy/sell label, target price, prediction,
scheduler, or anonymous execution endpoint is introduced.
