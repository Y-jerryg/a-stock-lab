# ADR 0014: Request-scoped user OpenAI keys

- Status: Accepted
- Date: 2026-09-02
- Supersedes: the shared operations-token and backend-key requirement in ADR 0013

## Context

ADR 0013 made AI research single-candidate and explicitly confirmed, but required a site-level
OpenAI key plus a separate operations token. That is appropriate for a private operator workflow
but cumbersome for a site where each user should pay for only the research they personally request.

OpenAI keys are secrets. They must not be embedded in a Vite build, persisted by A-Stock Lab, added
to URLs, or emitted in logs. A browser-entered key is still exposed to that page's JavaScript and to
the receiving backend, so this model requires a trusted site and HTTPS outside loopback development.

## Decision

Keep AI execution on the backend and keep the paid POST under the separate `/api/internal/v1`
operational boundary. When on-demand research is enabled, require the caller's OpenAI API key in the
`X-OpenAI-API-Key` request header and retain the literal one-candidate cost confirmation in the JSON
body. Remove the A-Stock Lab operations token from configuration and from the browser flow.

Construct a new OpenAI adapter for the request using a Pydantic `SecretStr`. The key exists only for
that request lifetime and is not persisted, hashed, included in provider metadata, returned in a
response, or logged. The scheduler, migration container, public read models, and static frontend
build receive no user key. A rejected key produces a typed, sanitized authentication error.

The server continues to choose the model and cost limits. A user key cannot change the model,
prompt, point-in-time boundary, candidate, or tool budget. Existing successful/no-evidence research
is returned from A-Stock Lab's cache before provider code is entered. A failed provider attempt still
requires an explicit retry so a browser cannot silently spend again.

## Consequences

Starting the stack, running the 14:30 workflow, listing candidates, and opening candidate details
still make zero OpenAI calls. A confirmed form submission can analyze exactly one candidate using
the submitting user's account. No shared site OpenAI budget or secondary token is required for the
browser flow.

This is bring-your-own-key, not user authentication or authorization. A valid OpenAI key does not
identify an A-Stock Lab user, and CORS is not an authorization boundary. Before exposing the feature
on a public production site, the deployment needs HTTPS, a trusted backend operator, browser security
hardening, abuse monitoring/rate limiting, and a clear key-handling notice. Users should prefer a
dedicated restricted project key with conservative spend limits and rotate/delete it after use.
