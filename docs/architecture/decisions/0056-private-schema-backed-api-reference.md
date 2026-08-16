# ADR 0056: Private schema-backed API reference

- Status: Accepted
- Date: 2026-08-16
- Supersedes: ADR 0030 only for its prohibition on browsable API documentation
  in the default `maru.urls` surface
- Clarifies: ADR 0001 and ADR 0039
- Requirements: INT-001, NFR-002, NFR-003, NFR-008

## Context

Maru already publishes one deterministic OpenAPI 3.1 contract at
`/api/v1/schema` and checks in the corresponding schema and generated client.
In a browser, however, that endpoint is downloaded as a machine document. It
does not provide the searchable, linked reference an operator or contributor
expects.

ADR 0030 intentionally kept the controlled rebuild JSON-only and rejected
browsable API HTML. The unified default shell later returned under ADR 0039,
but that decision did not silently reverse the JSON-only API constraint. A
browser reference therefore needs an explicit, narrower decision.

The existing schema endpoint was also anonymously readable, cacheable, and
covered by the credentialed registration-client CORS prefix. Although it
contains no record data, it describes the complete internal API vocabulary.

## Decision

Keep `/api/v1/schema` as the only authoritative API contract. Add two derived
views to the default `maru.urls` surface:

- `/api/v1/docs/` renders a searchable Swagger UI; and
- `/api/v1/redoc/` renders a reading-focused ReDoc reference.

These are presentation adapters over the same schema, not independent API
contracts, a second management shell, or DRF's per-endpoint browsable API.
`maru.baseline_urls` retains ADR 0030's controlled JSON-only surface and does
not mount either HTML view.

The schema and both derived views require a session-authenticated, freshly
resolved, active platform administrator. Permission checks fail closed on a
database error. Anonymous browser visits to the HTML views receive the normal
sign-in redirect; unauthorized schema requests receive `403`.

All three responses are private, non-cacheable, non-indexable, excluded from
credentialed registration-client CORS, and use a same-origin opener policy.
Swagger is an exploration surface, not an API client: submit methods are
disabled. Direct API requests retain their normal authentication, CSRF,
step-up, tenant, capability, strict-input, and idempotency boundaries.

Bundle pinned Swagger and ReDoc assets with `drf-spectacular-sidecar`. Override
the stock ReDoc template so it makes no Google Fonts or other third-party
asset request. Production artifacts must run `collectstatic` and serve those
versioned local assets. Schema generation remains CLI-capable and deterministic
without an HTTP session.

## Consequences

- Platform operators and contributors can browse and search the API without
  downloading and manually opening a large schema document.
- The raw schema is no longer anonymously disclosed.
- The checked-in OpenAPI document, generated TypeScript types, API behavior,
  route contracts, and authorization policies do not change.
- No model or database migration is introduced.
- A future strict Content Security Policy must nonce, hash, or externalize the
  documentation templates' small inline initialization scripts before it can
  prohibit inline script globally.
- Reachable documentation is not production approval, third-party credential
  issuance, or permission to bypass ordinary API controls.

## Alternatives considered

### Keep only the raw schema download

Rejected because it is correct for tooling but needlessly difficult for
human discovery and review.

### Enable DRF's browsable API on every endpoint

Rejected because it would add a second rendering and interaction contract to
every API handler and reverse ADR 0030 much more broadly than needed.

### Load UI assets from public CDNs

Rejected because an internal reference should not depend on unpinned remote
JavaScript, CSS, fonts, availability, or third-party request disclosure.

### Make the reference public

Rejected for the current internal platform because the complete API vocabulary
is operational metadata and Maru has no approved public developer-portal
boundary.
