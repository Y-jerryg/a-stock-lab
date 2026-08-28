# ADR 0004: Market providers behind interfaces

- Status: Accepted
- Date: 2026-08-28

## Context

Market providers vary in schemas, identifiers, credentials, availability, licensing, and data
quality. Binding research logic to a concrete SDK would make rules difficult to test and migrate.

## Decision

Define provider-independent contracts in feature domain/application layers. Keep concrete SDK
imports, normalization, retries, rate limits, and credentials inside adapters selected by
configuration.

## Consequences

Domain tests can use deterministic fakes, and providers can be replaced or compared. Adapters carry
additional mapping work and must report provenance. No market provider is selected in Phase 0.

