# Private interactive API documentation

- Date: 2026-08-16
- Status: Repository-verified; production deployment remains gated
- Requirements: INT-001, NFR-002, NFR-003, NFR-008
- Decision: ADR 0056

## Outcome

Maru now serves one canonical OpenAPI 3.1 schema and two derived browser
references:

- `/api/v1/schema` is the machine-readable contract;
- `/api/v1/docs/` is the searchable Swagger view; and
- `/api/v1/redoc/` is the reading-focused ReDoc view.

All three require a current active platform administrator. The browser views
use the ordinary sign-in redirect, the raw schema denies anonymous access, and
every success or denial is private, non-cacheable, non-indexable, excluded
from registration-client CORS, and protected by a same-origin opener policy.
Swagger submit methods are disabled.

Swagger and ReDoc assets are pinned by the Python lock and served locally by
`drf-spectacular-sidecar`. Maru's ReDoc template uses system fonts and makes no
third-party font or CDN request.

## Verification

- 33 focused unit tests passed for local static assets, controlled-baseline
  exclusion, exact-origin CORS exclusion, and the local landing destination.
- 7 focused PostgreSQL-backed integration tests passed for stable routes,
  anonymous/person/stale-admin denial, active platform-administrator access,
  HTML rendering, local asset URLs, response hardening, read-only methods, and
  the two existing schema-contract consumers.
- Ruff lint and format checks passed on the 11 changed Python test/source
  paths; strict mypy passed on the four changed source modules.
- `manage.py check` reports only the expected local fail-closed
  `identity.W001` invitation-encryption warning.
- OpenAPI validation completed with 0 errors and the 18 already-known enum
  naming warnings. Fresh generation exactly matched checked-in `openapi.yaml`
  at SHA-256
  `bc65826a8ceb93ca5cbe5e977e9f71dac50430c8168feb5c673fa8f0dccbb6fb`.
- `collectstatic --dry-run` found the pinned Swagger and ReDoc sidecar assets
  and completed with 192 static files in the current environment.

## Boundaries and recovery

This change adds no model, migration, data mutation, API operation, schema
shape, generated-client, tenant, authority, or runtime-role boundary. The
development and production databases were not migrated or modified.

Rollback removes the two derived routes and the sidecar application/dependency;
the canonical CLI-generated OpenAPI contract remains available. Do not make
the schema public as an operational workaround.

Production deployment still needs the normal immutable build, `collectstatic`,
edge/static verification, authentication and proxy rehearsal, recovery gates,
and owner acceptance. A future strict Content Security Policy must account for
the documentation initialization scripts. This checkpoint is not production
approval or a public developer-portal commitment.
