# Core module

Status: Implemented backend foundation, unified `/admin/` shell, and Page 8
governance integration; final suite/accessibility/owner gates remain
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
- focused local sign-in and the unified `/admin/` host boundary;
- responsive, progressively scoped Pages 1–8 adapters under the reserved
  `/admin/platform/` route space;
- the shared administration host, safety mixins, platform navigation, and
  record-oriented visual grammar selected by ADR 0039;
- canonical platform brand assets, accessible palette tokens, and application
  metadata

It does not own tenant context, business rules, permissions, audit, or a generic
`utils` collection.

The platform identity is defined in
[`../product/platform-brand.md`](../product/platform-brand.md) under ADR 0021.
It supports Maru's stable operational shell; convention-owned seasonal
frontends remain replaceable clients.

## Current browser shell

ADR 0039 makes `maru.urls`, rather than `maru.baseline_urls`, the default URL
configuration. The current implementation provides one
authenticated `/admin/` namespace:

- `/admin/` is the permission-filtered administration home;
- `/admin/workspace/` embeds API-backed Convention work;
- `/admin/platform/organizations/...` owns the purpose-built Pages 1–8 spine;
  and
- `/admin/<app-label>/<model-name>/...` retains specialist records.

The `platform` segment is reserved so the page spine cannot collide with a
Django application label. Explicit routes must be registered before
`admin.site.urls`. Pages 1–2 remain platform-administrator setup. Pages 3–7 use
exact organization/edition capability checks. Page 8 has bounded platform,
representation-manager, and exact-invitee policies. The shell mounts:

- Page 1 organization inventory;
- Page 2 Draft organization creation;
- Page 3 organization record/update/protected empty-Draft deletion;
- Page 4 convention-series creation;
- Page 5 convention-series record/update and edition inventory;
- Page 6 event-edition creation; and
- Page 7 event-edition record/update and explicit working-context selection;
  and
- Page 8 organization representation, exact controller invitations,
  self-response, and initial Draft-to-Active activation.

Sign-out and edition context select/clear are POST actions. The shell creates
no convention relationship for the platform administrator. Convention work
and specialist records use their existing independent policy/model-permission
boundaries; being visible in one menu does not broaden them. Public and
personal HTML routes remain outside `/admin/` according to purpose.

Focused route, authorization, shell/sidebar, and Page 8 backend verification
passes. Populated and fresh migrations, a local populated restore drill,
desktop/390-pixel smoke, and the Page 8 sensitive-read/denial audit boundary
also pass. The final consolidated local backend gate passes 792 tests in
329.21 seconds with 90.01 percent coverage and no warnings; a separate behavior
run passes the same 792 tests in 291.86 seconds. Nine focused unified-routing
tests pass, including scoped non-staff account-control routing. A live Board
logout reaches `/accounts/login/`, removes the logged-in banner, and produces no
new console warning or error. A platform-administrator reload renders one
searchable `#nav-filter`, Specialist records and Platform administration
exactly once each, the correct `demo.admin` account, and no new console warning
or error. Keyboard, automated accessibility, complete visual-state, and
owner-tutorial evidence remain open.

Every mounted page has bounded empty/populated/conflict/failure states. A
database dependency failure produces safe `503` guidance and a server exception
log without exposing the database message. Page adapters call module-owned
queries and commands; `core` does not absorb their business rules.

`StrictInputForm` admits only declared fields plus CSRF, and
`reject_unknown_fields(...)` provides the equivalent API boundary. Errors
report at most five bounded field names. Module services still repeat
security-critical validation because transport validation alone is not an
authority or integrity boundary.

Page 8 reuses that primitive for four closed forms. Provision accepts only a
bounded reason; invite accepts exact email plus reason; self-response accepts a
positive expected invitation version plus `accept|decline`; activation accepts
a positive representation version, exact case-sensitive organization name,
and reason. Organization, person, representation, role, actor, state, scope,
lifecycle, timestamps, and evidence remain code-owned.

Health, build, schema, and versioned APIs remain authoritative. HTML and
embedded clients call the same module services; a mounted preserved screen does
not replace those contracts.

## Unified administration implementation

ADR 0039 again selects the original Django administration index as the
canonical `/admin/` home and reuses its stronger visual grammar.
API-backed Convention work is embedded inside the same base template at
`/admin/workspace/`; the embedded application does not render another global
menu or workspace selector. Its inner pages use the same record-oriented
heading, module, form, table, button, spacing, and responsive language as
specialist record pages. Existing model URLs remain under `/admin/`. Shared admin mixins remove
destructive bulk deletion and make command-owned records view-only. One
collapsible sidebar links recurring work, contextual access sharing, and the
permission-filtered specialist record directory.
Django's `nav_sidebar.js` expects one `#nav-filter` even when no model directory
is available. The custom sidebar preserves that DOM contract and hides the
filter for scoped accounts with no Specialist records instead of removing it.
Django AdminSite's normal URL wrapper rejects non-staff accounts before its
account-control views run. Maru therefore declares `/admin/logout/`,
`/admin/password_change/`, and its completion route before `admin.site.urls`.
Active scoped non-staff accounts admitted to the unified shell can use real
logout and password-change handlers without receiving staff status or access
to Specialist records.
Django's generic `Group` page is hidden
because Maru authority is expressed through scoped capabilities and versioned
role bundles, not a parallel unscoped role system.

Module-owned admin pages provide the domain-specific names, filters, searches,
field groupings, and archived-state behavior. Technical UUIDs and timestamps
remain available in collapsed detail sections rather than leading list views.
The header also hosts the ADR 0008 convention-workspace selector. Event-owned
modules declare their scope explicitly; the shared shell does not infer tenant
ownership or treat the selected edition as authorization.

The administration home shows Django's alphabetical application/model list
only to accounts with independent staff/model permissions. Active scoped non-
staff accounts still enter the Maru shell and see only permitted Maru work.
ADR 0027 removes the former global Quick Start because it consumed every
administration page's top chrome. Dependency guidance remains contextually in
Convention work's **Setup guide**; record existence still does not prove
approval, authority, readiness, or completion. ADR 0040 replaces its broad
first-authority ceremony as the normal path with selected-organization Page 8.
The old bootstrap command/service is recovery evidence only until an explicit
legacy-reconciliation procedure approves a narrower use. Its former web
ceremony and `/api/v1/management/convention-bootstrap` endpoint are not mounted.

Every active authenticated account enters the management product at `/admin/`.
An exact Page 8 invitee may open only their scoped invitation even before they
hold organization authority; active non-administrators without a relationship
retain the safe empty state. Ordinary Django record pages remain staff/model-
permission protected. Platform staff status does not grant convention
capabilities. Removed `/manage/`, `/staff/`, and `/admin/records/` paths do not
redirect.

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

Current integration tests cover route collisions, anonymous/inactive/platform/
scoped-nonstaff/staff boundaries, sidebar visibility, Convention work,
specialist-record gating, old-route behavior, Page 8 menu and disclosure,
strict forms, stale/replay behavior, and activation failure. They prove that a
selected edition, Django staff flag, and visible menu never grant organization
authority. Database-level representation tests cover cross-approval,
constraints, atomicity, and platform exclusion. The responsive smoke, local
migration/restore, bounded Page 8 read/denial audit, final local full suite/
coverage gate, nine-test focused routing regression, live Board logout, and
platform-administrator reload pass. Keyboard/automated accessibility, complete
visual states, and owner evidence remain required.

## Limitations

Complete computed effective access, invitation notification discovery,
metrics/tracing export, error capture, rate limiting, and a public status
service remain. Page 8's root-representation explanation is only the first
policy-derived slice; M2 must still add department/resource/field explanations
before department-owned mutation pages are mounted. The unified shell and
initial Page 8 lifecycle are implemented backend milestones, not production-
ready release claims.
