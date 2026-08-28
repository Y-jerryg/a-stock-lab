# ADR 0001: Production modular monolith

- Status: Accepted
- Date: 2026-08-28

## Context

Four research modules need distinct ownership boundaries while sharing execution, artifacts,
persistence, configuration, and operational practices. The project is maintained as one personal
research platform and does not yet have independent scaling or team boundaries.

## Decision

Use one modular backend application and one frontend application. Feature packages isolate domain,
application, and adapter concerns. The same backend package/image may later run API and worker
processes. Do not introduce microservices.

## Consequences

Transactions, refactoring, testing, and local operations remain simple. Boundaries require discipline
and import review rather than network enforcement. A future split needs a new ADR backed by measured
operational need.

