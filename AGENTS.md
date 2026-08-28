# A-Stock Lab contributor guide

Read the relevant files in `docs/` and accepted ADRs before major changes. A-Stock Lab is a
production-oriented modular monolith; architecture decisions must not be changed silently. Add or
update an ADR when a durable decision changes.

## Invariants

- Keep provider-specific code in adapters. Domain and business logic must never import concrete
  market SDKs.
- Keep API routes thin; orchestration belongs in application/services and rules belong in domain
  code.
- Never access OpenAI or expose backend secrets from frontend code.
- Keep public read APIs separate from authenticated internal/operational APIs.
- Use timezone-aware timestamps. A-share market semantics use `Asia/Shanghai`.
- Preserve an explicit `as_of` for every historical research analysis and never use information
  that was unavailable at that point in time.
- Keep deterministic market signals separate from AI interpretation.
- Database schema changes require Alembic migrations.
- Do not commit runtime financial data, generated datasets, credentials, `.env`, or secrets.
- Run relevant format, lint, typecheck, and test commands after meaningful changes.

The first-class feature boundaries are `tail_radar`, `intelligence`, `quant_lab`, and `assistant` in
both backend and frontend. Shared research output must use a versioned `ResearchArtifact` contract.

