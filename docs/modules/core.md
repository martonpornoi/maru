# Core module

Status: Implemented backend foundation and controlled Pages 1–7 management shell
Last updated: 2026-08-01

## Purpose and requirements

`maru.core` owns genuinely domain-neutral runtime primitives supporting
NFR-001, NFR-004, NFR-006, NFR-008, and NFR-009.

## Owned behavior

- UUID/timestamp abstract persistence base
- strict reusable value validators
- strict HTML/API input helpers that reject undeclared fields
- request correlation
- allowlisted structured JSON logging
- RFC 9457-style DRF problem responses
- liveness, database readiness, and build identity endpoints
- an ADR 0030 root redirect and focused local sign-in;
- the responsive, progressively scoped Pages 1–7 administration shell;
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
`/admin/`; `/accounts/login/` is the only unauthenticated HTML page. The
authenticated `/admin/` namespace requires an active platform administrator
and now mounts the organization → series → edition spine:

- Page 1 organization inventory;
- Page 2 Draft organization creation;
- Page 3 organization record/update/protected empty-Draft deletion;
- Page 4 convention-series creation;
- Page 5 convention-series record/update and edition inventory;
- Page 6 event-edition creation; and
- Page 7 event-edition record/update and explicit working-context selection.

Sign-out and edition context select/clear are POST actions. The shell creates
no convention relationship for the platform administrator. Previous
Convention work, public registration, volunteer, and specialist-record HTML
routes remain unmounted and return 404.

Every mounted page has bounded empty/populated/conflict/failure states. A
database dependency failure produces safe `503` guidance and a server exception
log without exposing the database message. Page adapters call module-owned
queries and commands; `core` does not absorb their business rules.

`StrictInputForm` admits only declared fields plus CSRF, and
`reject_unknown_fields(...)` provides the equivalent API boundary. Errors
report at most five bounded field names. Module services still repeat
security-critical validation because transport validation alone is not an
authority or integrity boundary.

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
tests cover Pages 1–7 authorization, progressive/current navigation, strict
input, safe failure behavior, and platform non-participation.

## Limitations

Computed effective access, metrics/tracing export, error capture, rate limiting,
and a public status service remain. The current access summary is deliberately
static and labels platform oversight only; M2 must replace it with policy-
computed organization/department/resource explanations before convention-owned
mutation pages are mounted.
