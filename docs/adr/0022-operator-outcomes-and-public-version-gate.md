# ADR 0022: Explicit operator outcomes and compatible publication

- Status: Accepted
- Date: 2026-09-15
- Extends ADR 0016, 0020 and 0021; no database schema change

The overnight full-market scan completed with warnings and durable candidates, but the operator
reported failure. INFO and stock errors share stderr, and desktop final status relied solely on a
Windows Process exit-code property. Publishing a rule-2 dataset against an older frontend also
succeeded at the deployment level while breaking browser parameter validation.

Each desktop action now writes a separate result JSON under the existing ignored operator runtime
directory. It includes action, exit code, final state, a human-readable message, compact scan counts
and an aware completion timestamp. The window reads that authoritative report after process exit;
it does not infer a failed scan from stderr or a missing cached exit code. CLI `scan --summary` avoids
dumping thousands of exclusion entries into the GUI; detailed evidence remains in PostgreSQL/logs.

Publication checks the required rule version against a small frontend capability manifest in the
target repository's main branch before replacing the Release asset. Missing/incompatible support
stops publication and tells the operator to deploy code first. This is a compatibility gate, not a
claim of deployment success: the corresponding Pages workflow must still finish successfully.

The same desktop window now offers local start, health/status, Tail view, existing public start/stop,
and the offline guide. Local start includes the Tail scheduler. Trend scans remain manual by default;
no new public mutation endpoint or automatic paid AI call is introduced.

The result reader preserves publication ordering so the attention Top-N priority is not overwritten
by an older client-side volume sort. Search examines the complete candidate list; pagination renders
30 cards at a time to handle a full-market result without a thousand-card document.
