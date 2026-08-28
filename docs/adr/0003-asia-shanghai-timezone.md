# ADR 0003: Asia/Shanghai canonical market timezone

- Status: Accepted
- Date: 2026-08-28

## Context

A-share sessions and snapshot meaning are defined by Chinese local market time. Naive timestamps are
ambiguous and enable historical look-ahead errors.

## Decision

Use timezone-aware timestamps everywhere for market and research meaning. Interpret session rules in
`Asia/Shanghai`, and require every historical analysis and artifact to preserve an explicit `as_of`.

## Consequences

Adapters must normalize provider timestamps before domain use. Persistence uses timezone-aware
PostgreSQL columns. Tests must reject naive values and cover time-boundary behavior when market logic
is implemented.

