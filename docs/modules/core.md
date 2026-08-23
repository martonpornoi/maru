# Core module

Status: Implemented backend foundation, focused responsive `/admin/` hierarchy,
shared management-page frame, Representation & access governance integration,
and Organization structure/Department management; broader journey,
accessibility, and owner gates remain
Last updated: 2026-08-23

## Purpose and requirements

`maru.core` owns genuinely domain-neutral runtime primitives supporting
UX-029, INT-001, NFR-001, NFR-002, NFR-004, NFR-006, NFR-008, and NFR-009.

## Owned behavior

- UUID/timestamp abstract persistence base
- strict reusable value validators
- strict HTML/API input helpers that reject undeclared fields
- request correlation
- allowlisted structured JSON logging
- RFC 9457-style DRF problem responses
- liveness, database readiness, and build identity endpoints
- the canonical served OpenAPI schema and private Swagger/ReDoc rendering
  adapters;
- focused local sign-in and the unified `/admin/` host boundary;
- the code-owned task navigation registry, search metadata, pin policy,
  specialist disclosure, and task-first administration home;
- separate personal/administrative navigation projections, progressive pin
  customization, and explicit surface switching;
- the compact context and effective-access presentations plus accessible
  responsive drawer behavior;
- responsive, progressively scoped platform-management adapters under the reserved
  `/admin/platform/` route space;
- the shared administration host, safety mixins, platform navigation, and
  record-oriented visual grammar selected by ADRs 0039 and 0055;
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
- `/admin/platform/organizations/...` owns the purpose-built platform management spine;
  and
- `/admin/<app-label>/<model-name>/...` retains specialist records.

The `platform` segment is reserved so the page spine cannot collide with a
Django application label. Explicit routes must be registered before
`admin.site.urls`. Platform administration home and Create organization remain
platform-administrator setup. The organization, series, and edition record
surfaces use exact organization/edition capability checks. Representation & access has bounded platform,
representation-manager, and exact-invitee policies. The shell mounts:

- Platform administration home and organization inventory;
- Create organization and its Draft command;
- Organization record/update/protected empty-Draft deletion;
- Create convention series;
- Convention series record/update and edition inventory;
- Create event edition;
- Event edition record/update and explicit working-context selection;
- Representation & access, exact controller invitations,
  self-response, and initial Draft-to-Active activation; and
- Organization structure at the exact edition route, with the
  separate Executive Board governance anchor, bounded workforce tree, and
  same-shell template and Department management child pages.

ADR 0055 changes the presentation hierarchy without changing any route or
authorization boundary. The default shell shows a small set of durable tasks,
puts contextual creation commands in the search-only **Actions** group, and
keeps authorized technical model pages searchable behind one collapsed
**Specialist records** disclosure. Navigation search indexes only code-owned
labels, descriptions, and stable generic keywords. The administration home
leads with current work and **Continue setup** and provides one specialist
gateway instead of repeating the complete model directory. Search reports task
matches separately from technical records, clears on Escape, and leaves the
technical results collapsed. Row-level pin controls appear only after the user
opens **Customize navigation**.

My Maru and Administration resolve independent authorized item sets and pins.
The personal home prioritizes registration, applications, and schedule, then
groups lower-frequency self-service links under **More from Maru**. Accounts
with organizer or platform authority receive one explicit Administration/My
Maru switch; the personal menu never reproduces Platform or Specialist records.

The shared page frame mounts one compact **Access** disclosure after the page
heading. Server-rendered workflows use the common template mount; the embedded
Convention work page declares that its active React view owns the disclosure,
preventing duplicate titles, summaries, or landmarks around the application
root.

At 1,100 CSS pixels and below, the sidebar becomes a closed-by-default overlay
drawer with a labelled open control, visible close control, backdrop,
`aria-expanded`/`aria-controls`, Escape handling, focus containment, background
scroll lock, inert and accessibility-hidden background content, and focus
return. Wider layouts retain the persistent sidebar.
The convention-context control uses a compact shrinkable layout so it cannot
force the management page wider than the viewport. Embedded Convention work
uses the host selector as its only visible context control and posts its
authorized initial edition through the existing server action before rendering
scoped records when the host has no selection.

Blocking person, attendee, and access side workspaces share one modal contract:
labelled dialog semantics, close focus, Escape, Tab containment, inert and
accessibility-hidden background content, body scroll lock, and return to the
exact opener.

Sign-out and edition context select/clear are POST actions. The shell creates
no convention relationship for the platform administrator. Convention work
and specialist records use their existing independent policy/model-permission
boundaries; being visible in one menu does not broaden them. Public and
personal HTML routes remain outside `/admin/` according to purpose.

Focused route, authorization, shell/sidebar, Representation & access, and Organization structure backend
verification passes. The management-experience coverage includes the drawer,
task navigation/home, search result hierarchy, progressive customization,
personal/admin separation, shared access placement, User accounts, invitation
status, Board progress continuity, and Registration task naming. Populated and
fresh
migrations, a local populated restore drill, historical desktop/390-pixel
smoke, and the Representation & access sensitive-read/denial audit boundary also pass. The final
consolidated local backend gate passes 792 tests in
329.21 seconds with 90.01 percent coverage and no warnings; a separate behavior
run passes the same 792 tests in 291.86 seconds. Nine focused unified-routing
tests pass, including scoped non-staff account-control routing. A live Board
logout reaches `/accounts/login/`, removes the logged-in banner, and produces no
new console warning or error. A platform-administrator reload renders one
searchable `#nav-filter`, Specialist records and Platform administration
exactly once each, the correct `demo.admin` account, and no new console warning
or error. Authenticated rendered evidence across the complete ADR 0055
width/zoom matrix, keyboard and automated-accessibility checks, complete visual
states, and owner tutorial remain open.

Organization structure appears once beneath an authorized selected edition and is also
discoverable to an ordinary account whose only qualifying edition-wide
capability is `workforce.view_structure`. Its canonical route is
`/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/`.
The former React Convention work structure destination and `?view=structure`
path are removed. The strict GET projection and five template/Department
mutation operations remain supported generated-client boundaries. Separate
same-shell child pages expose the browser mutation controls.

Every mounted page has bounded empty/populated/conflict/failure states. A
database dependency failure produces safe `503` guidance and a server exception
log without exposing the database message. Page adapters call module-owned
queries and commands; `core` does not absorb their business rules.

`StrictInputForm` admits only declared fields plus CSRF, and
`reject_unknown_fields(...)` provides the equivalent API boundary. Errors
report at most five bounded field names. Module services still repeat
security-critical validation because transport validation alone is not an
authority or integrity boundary.

Representation & access reuses that primitive for four closed forms. Provision accepts only a
bounded reason; invite accepts exact email plus reason; self-response accepts a
positive expected invitation version plus `accept|decline`; activation accepts
a positive representation version, exact case-sensitive organization name,
and reason. Organization, person, representation, role, actor, state, scope,
lifecycle, timestamps, and evidence remain code-owned.

Health, build, the OpenAPI schema, and versioned APIs remain authoritative.
`/api/v1/docs/` and `/api/v1/redoc/` are derived discovery/rendering adapters
over that one schema; they do not replace it or add an API behavior contract.
HTML and embedded clients call the same module services; a mounted preserved
screen does not replace those contracts.

## Unified administration implementation

ADR 0039 selects the Django administration boundary and visual grammar for the
canonical `/admin/` home. ADR 0055 replaces its exhaustive model-directory
presentation with Maru's task-first home while retaining the same routes and
security boundary.
API-backed Convention work is embedded inside the same base template at
`/admin/workspace/`; the embedded application does not render another global
menu or workspace selector. Its inner pages use the same record-oriented
heading, module, form, table, button, spacing, and responsive language as
specialist record pages. Existing model URLs remain under `/admin/`. Shared admin mixins remove
destructive bulk deletion and make command-owned records view-only. Shared
navigation links recurring work and contextual access sharing. Durable
destinations may be pinned after fresh authorization. Creation commands are
non-pinnable contextual actions, and authorized technical records remain
available through search and the collapsed specialist disclosure.

The durable attendee-service task is named **Registration desk**. The exact
edition setup record is **Registration**, and its capacity policy is
**Capacity & waitlist**. These labels keep a high-frequency service queue,
low-frequency configuration, and capacity decisions distinct without changing
their routes or permission boundaries.
The durable **Workforce** task reads the existing exact-edition structure
projection and connects Structure, Positions, Assignments, Availability, and
Shifts. It does not create another Department writer; authorized managers reach
the purpose-built Position workspace, and unavailable future stages remain
labelled and noninteractive.
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

The administration home shows current setup and recent work rather than
Django's alphabetical application/model list. Accounts with independent staff/
model permissions retain those authorized destinations through the specialist
gateway and navigation search. Active scoped non-staff accounts still enter the
Maru shell and see only permitted Maru work.
ADR 0027 removes the former global Quick Start because it consumed every
administration page's top chrome. Dependency guidance remains contextually in
Convention work's **Setup guide**; record existence still does not prove
approval, authority, readiness, or completion. ADR 0040 replaces its broad
first-authority ceremony as the normal path with selected-organization Representation & access.
The old bootstrap command/service is recovery evidence only until an explicit
legacy-reconciliation procedure approves a narrower use. Its former web
ceremony and `/api/v1/management/convention-bootstrap` endpoint are not mounted.

Every active authenticated account enters the management product at `/admin/`.
An exact Representation & access invitee may open only their scoped invitation even before they
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
- `/api/v1/schema`
- `/api/v1/docs/`
- `/api/v1/redoc/`

## Security and data

Correlation accepts only UUID input and generates a replacement otherwise.
Logs include an allowlist of technical metadata. Exception type may be logged;
exception message and request payload are not.

Health failures name only the affected dependency class. Liveness deliberately
does not contact external dependencies. Readiness proves that authority
cutover tables are either wholly absent or in the configuration-compatible
dormant/exact state; exact mode also checks PostgreSQL 17, fixed effective
schema order, and absence of runtime `TEMPORARY` privilege without exposing
which check failed.

## Failure and operations

Readiness returns `503` when PostgreSQL cannot answer its minimized catalog or
authority-contract queries, when a false-configured replica sees active or
malformed cutover state, or when the required exact boundary is unavailable.
Independent provider health will be added to an authenticated operator
projection, not the public response.

The schema and both derived references require a current active platform
administrator, fail closed on database lookup failure, use private `no-store`
responses, and are excluded from registration-client CORS. Swagger submit
methods are disabled. The locked sidecar assets must be included by
`collectstatic`; the ReDoc override makes no external font or CDN request.

## Tests

Unit tests cover strict environment parsing, validators, request correlation,
safe log output, problem response shape, health/build behavior, sidecar asset
discovery, and CORS/baseline exclusion. Integration tests cover the platform setup record journey
authorization, progressive/current navigation, strict input, safe failure
behavior, platform non-participation, and the schema/Swagger/ReDoc route,
rendering, stale-authority, read-only, and response-hardening contracts.

Current integration tests cover route collisions, anonymous/inactive/platform/
scoped-nonstaff/staff boundaries, sidebar visibility, Convention work,
specialist-record gating, old-route behavior, Representation & access menu and disclosure,
strict forms, stale/replay behavior, and activation failure. They prove that a
selected edition, Django staff flag, and visible menu never grant organization
authority. Database-level representation tests cover cross-approval,
constraints, atomicity, and platform exclusion. The responsive smoke, local
migration/restore, bounded Representation & access read/denial audit, final local full suite/
coverage gate, nine-test focused routing regression, live Board logout, and
platform-administrator reload pass. The historical Organization structure read projection focused tests
additionally cover
canonical/current navigation, structure-only edition discovery, view/manage
independence, department-only denial, non-participating platform oversight,
explicit overflow, safe dependency failure, and absence of the retired React
destination. Both HTML and API require the minimized structure-read audit to
persist before disclosure. Department management adds 118 targeted adapter and invariant
cases; the definitive repository invocation passes 1,693 tests at 90.50
percent total branch-inclusive coverage.
Focused management-experience tests additionally cover drawer markup and
behavior contracts, collapsed/searchable specialist access, search-only
actions, natural task keywords, the task-first home, User accounts
presentation, invitation next steps, Board progress, personal/admin separation,
compact page-access placement, Registration task naming, the owner-visible
Workforce destination, and embedded context synchronization. Authenticated
rendered
checks at 320, 390, 768, 958, 1,024, 1,280, and 1,920 CSS pixels plus 200
percent zoom, keyboard/automated accessibility, complete visual states, and
owner evidence remain required.

## Limitations

Complete computed effective access, invitation notification discovery,
metrics/tracing export, error capture, rate limiting, and a public status
service remain. The task-oriented shell/home and User accounts-to-Board flow
now include shared framing, Registration-desk orientation, the owner-safe
Workforce read journey, and governed Position management; assignments, Venues,
Logistics, and other
specialist journeys are not yet certified against the same complete state and
browser matrix. Representation & access's root-representation
explanation is only the
first policy-derived slice; Organization structure adds a current principal-specific structure
view/manage summary but not named relationship disclosure or the complete
department/resource/field explanation. Department and Position management use
the structure version fence and strict adapters; assignment approval and the
computed access explanation remain separate. The unified shell,
Representation & access, and Organization structure are implemented backend
milestones, not production-ready release claims.
