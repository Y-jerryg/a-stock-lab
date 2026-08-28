# ADR 0006: Static frontend separated from backend deployment

- Status: Accepted
- Date: 2026-08-28

## Context

The public frontend is likely to use GitHub Pages, while the API and secrets require a separate
runtime. Static hosts do not reliably rewrite arbitrary client-side paths to `index.html`.

## Decision

Build the frontend as static Vite assets, use hash routing, configure the repository asset base at
build time, and configure the public API origin independently. Keep all secrets and provider calls in
the backend.

## Consequences

Direct navigation works on GitHub Pages without a custom 404 workaround. URLs include `#`, and the
backend must configure CORS for the final Pages origin. Container hosting may use a same-origin Nginx
proxy without changing the architecture.

