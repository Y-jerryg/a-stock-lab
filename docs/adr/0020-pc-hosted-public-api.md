# ADR 0020: PC-hosted HTTPS API for Pages and visitor-provided AI keys

- Status: Accepted
- Date: 2026-09-14
- Extends: ADR 0014 and deployment topology; no domain or schema change

The operator chooses to keep the backend and existing data on their own PC, with visitors using
their own OpenAI keys. GitHub Pages still hosts the static website and Trend Radar publication.

Use an opt-in Compose overlay containing a dedicated Nginx public API gateway and Cloudflare Quick
Tunnel. No additional host/database ports are published. Expose public GET APIs and only the exact
existing per-candidate research POST; all other routes, docs and operations remain inaccessible.
The gateway allows the operator's Pages origin, handles preflight, forwards the transient key only
to the backend, disables caching and POST replay, limits body size, and sets global read/research
budgets (20 read requests/second, 6 research requests/minute with burst 2, 2 concurrent research
requests). Logs omit headers, query strings and bodies and use bounded local rotation. Existing
backend validation, explicit fee confirmation, per-candidate claim and sanitized errors remain.

The start script derives the repository and Pages URL using authenticated GitHub CLI, starts the
gateway/tunnel, verifies HTTPS reads and preflight, then updates only VITE_API_BASE_URL and triggers
Pages. It records nonsecret runtime status locally. Stop disconnects the tunnel and gateway while
preserving local data. Starting again adopts the current tunnel URL and republishes when needed.
No API key, account token, database or raw runtime directory goes to the frontend build.

Quick Tunnels are explicitly a testing arrangement, without a fixed hostname or uptime guarantee.
The PC, Docker and Internet connection must stay on; after tunnel restart the operator must run
the connection script again so Pages receives the new URL. For stable ongoing hosting, retain the
same gateway and use a named tunnel with an operator-owned domain. That requires separate domain
and Cloudflare account setup. No account, paid resource or fixed domain is invented by this change.

Source: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).
Paid AI success still requires a visitor key with model access and credit; transport checks and
mocked provider tests alone must not be reported as successful paid analysis.
