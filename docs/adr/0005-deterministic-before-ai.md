# ADR 0005: Deterministic market logic separated from AI interpretation

- Status: Accepted
- Date: 2026-08-28

## Context

Quantitative selection and historical evaluation must be reproducible, while language-model research
is probabilistic and provider-dependent. Mixing them would obscure causality and auditability.

## Decision

Compute and persist deterministic signals before any AI interpretation. AI consumes explicit,
versioned inputs and publishes separately identified artifacts with provider and execution metadata.

## Consequences

Signals can be reproduced without model access, AI output cannot silently alter candidate selection,
and failures remain isolated. Workflows require clear intermediate artifact contracts.

