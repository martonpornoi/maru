# Core module

Status: Implemented backend foundation with ADR 0031 Page 1 platform home
Last updated: 2026-07-31

## Purpose and requirements

`maru.core` owns genuinely domain-neutral runtime primitives supporting
NFR-001, NFR-004, NFR-006, and NFR-008.

## Owned behavior

- UUID/timestamp abstract persistence base
- strict reusable value validators
- request correlation
- allowlisted structured JSON logging
- RFC 9457-style DRF problem responses
- liveness, database readiness, and build identity endpoints
- an ADR 0030 root redirect and focused local sign-in;
- the ADR 0031 platform-administrator-only organization inventory at `/admin/`;
- preserved administration safety mixins and previous shell implementation,
  not mounted in the current default experience
- canonical platform brand assets, accessible palette tokens, and application
  metadata

It does not own tenant context, business rules, permissions, audit, or a generic
`utils` collection.

The platform identity is defined in
[`../product/platform-brand.md`](../product/platform-brand.md) under ADR 0021.
It supports Maru's stable operational shell; convention-owned seasonal
frontends remain replaceable clients.

## Current browser baseline

`maru.baseline_urls` is the default URL configuration. `/` redirects to
`/admin/`; `/accounts/login/` is the only unauthenticated HTML page; and
`/admin/` is the only authenticated HTML page. The home requires an active
platform administrator and shows only the C1 organization inventory described
by UX-014. It performs no mutation and creates no convention relationship.
Sign-out is a POST action. Previous HTML routes are not mounted and return 404.

The home renders empty and populated states atomically. A database query failure
produces a safe read-only `503` page and server exception log without exposing
the database message. The Page 2 organization-creation route is not mounted and
Page 1 does not present an unfinished action.

Health, build, schema, and versioned APIs remain mounted. Automated backend
tests may select the preserved URL configuration, but that does not make its
pages part of the product.

## Preserved administration implementation

Before ADR 0030, the original Django administration index was the canonical
`/admin/` home.
API-backed Convention work is embedded inside the same base template at
`/admin/workspace/`; the embedded application does not render another global
menu or workspace selector. Its inner pages use the same record-oriented
heading, module, form, table, button, spacing, and responsive language as
specialist record pages. Existing model URLs remain under `/admin/`. Shared admin mixins remove
destructive bulk deletion and make command-owned records view-only. One
collapsible sidebar links recurring work, contextual access sharing, and the
permission-filtered specialist record directory.
Django's generic `Group` page is hidden
because Maru authority is expressed through scoped capabilities and versioned
role bundles, not a parallel unscoped role system.

Module-owned admin pages provide the domain-specific names, filters, searches,
field groupings, and archived-state behavior. Technical UUIDs and timestamps
remain available in collapsed detail sections rather than leading list views.
The header also hosts the ADR 0008 convention-workspace selector. Event-owned
modules declare their scope explicitly; the shared shell does not infer tenant
ownership or treat the selected edition as authorization.

The administration home keeps Django's complete alphabetical application/model
list. ADR 0027 removes the former global Quick Start because it consumed every
administration page's top chrome. Dependency guidance and the guarded
first-authority ceremony remain contextually in Convention work's **Setup
guide**; record existence still does not prove approval, authority, readiness,
or completion.

Every active authenticated account enters at `/admin/`. A workspace-less
bootstrap superuser can open the guarded leadership ceremony through
Convention work; active non-administrators without a workspace retain the safe
empty state. Ordinary Django record pages remain staff/model-permission
protected. Platform staff status does not grant convention capabilities.
Removed `/manage/`, `/staff/`, and `/admin/records/` paths do not redirect.

## Public contracts

- `UUIDTimeStampedModel`
- value validators under `maru.core.validators`
- correlation context
- `/`
- `/health/live`
- `/health/ready`
- `/api/v1/meta/build`

## Security and data

Correlation accepts only UUID input and generates a replacement otherwise.
Logs include an allowlist of technical metadata. Exception type may be logged;
exception message and request payload are not.

Health failures name only the affected dependency class. Liveness deliberately
does not contact external dependencies.

## Failure and operations

Readiness returns `503` when PostgreSQL cannot answer a trivial query.
Independent provider health will be added to an authenticated operator
projection, not the public response.

## Tests

Unit tests cover strict environment parsing, validators, request correlation,
safe log output, problem response shape, and health/build behavior. Integration
tests cover Page 1 authorization, organization counts, non-participation side
effects, and safe failure behavior.

## Limitations

Audit, metrics/tracing export, error capture, rate limiting, and a public status
service arrive in later V02/operations work.
