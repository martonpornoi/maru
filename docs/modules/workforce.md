# Workforce module

Status: Position, hierarchy, opportunity, agreement, authority onboarding,
ADR 0041 containment, and version-fenced Department and Position management
with shared strict HTML/API commands and stopped-writer database enforcement
are implemented in the canonical current tree; assignment approval,
availability, shifts, complete rendered accessibility, recovery, deployment,
and production acceptance remain gated
Last updated: 2026-08-23

## Purpose and requirements

`maru.workforce` owns the executable HR-007, HR-008, HR-010, HR-011, and HR-012
slices defined by ADRs 0019, 0028, and 0075, plus IDN-011's non-participation
boundary. It turns an edition responsibility into explicit structure:

```text
department hierarchy
  -> position from an immutable organization template
  -> always-present publishable volunteer opportunity
  -> application and requested agreement evidence
  -> independently approved position assignment
  -> exact role-bundle version and participation capacities
```

It does not infer access from a job title, an application, a registration
answer, an uploaded file, or a profile label. Authority remains owned by
`maru.authorization`; convention participation remains owned by
`maru.participation`.

A platform administrator may initiate or review bootstrap work as an attributed
actor, but cannot be the subject of a volunteer application, onboarding request,
or position assignment. Model validation and PostgreSQL reject the
platform-only subject classification without rejecting `reviewed_by`,
`requested_by`, `proposed_by`, or `approved_by` actor provenance.

## Legacy empty-organization bootstrap

ADR 0040 supersedes this broad workforce ceremony as the normal way to
establish first organization authority. A new Draft organization uses Representation & access's
purpose-built Executive Board lifecycle. The service below remains preserved
recovery evidence for legacy reconciliation only; it must not compete with
Representation & access or be used without a separately approved procedure.

An empty organization cannot use its own scoped permission commands before it
has a controller. The preserved one-shot, trust-on-first-use service was the
former **Establish convention leadership** workflow.
It requires:

- an existing active platform administrator as bootstrap controller;
- a different active account as Convention Chair;
- an active organization and matching non-closed edition;
- an exact repeated organization slug and reason;
- no existing grants, role assignments, or role bundles in the organization.

It creates organization-scoped authority-controller and edition-scoped
Convention Chair authority only for the distinct Chair account, plus the first
leadership department, chair position, and ten furry-convention position
templates. The platform administrator remains an attributed actor and receives
no organizer membership, convention role, participation, or workforce
position. A second run fails closed.

The preserved service now creates that first Department through the same
Organization structure command used by every supported Department writer. Its
correlation identifier is also the deterministic retry key and request
identifier, so the immutable receipt ties the attributed platform actor to
structure version 1. It then creates the first Convention Chair Position,
private draft opportunity, and exact resource binding through the governed
Position command at version 2. Because this ceremony necessarily predates
historical RoleBundle issuance, a non-HTTP exception accepts only the exact
platform-administrator-created, independently approved `convention-chair`
template at version 1 while no Position exists. Every ordinary Position still
requires historical provenance. Before creating the Department, Position, or
assignment, the service joins the canonical edition write scope; Position and
assignment writes additionally lock the active Department target. This keeps
recovery bootstrap inside the Organization structure, provenance, retirement,
and edition-mutex lock order without turning the platform administrator into a
convention subject.

The former browser ceremony and
`/api/v1/management/convention-bootstrap` endpoint are not mounted. Their old
tests and implementation remain historical recovery evidence; they are not a
second setup path beside Representation & access. Candidate reads and mutations must use an
approved operator reconciliation procedure and retain the service's existing
audit and atomicity boundaries.

`bootstrap_convention` remains the recovery/operator fallback. In PowerShell,
set the database in a separate statement and invoke the virtual-environment
Python with `&`:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_walkthrough"
& ".\.venv\Scripts\python.exe" src/manage.py bootstrap_convention `
  --organization ORGANIZATION_SLUG `
  --edition EDITION_SLUG `
  --controller-email ADMIN_EMAIL `
  --chair-email CHAIR_EMAIL `
  --reason "Establish the first accountable convention leadership." `
  --confirm-organization ORGANIZATION_SLUG
```

Starter templates cover Convention Chair, Vice Chair, Board Member, Department
Lead, Registration Lead, Front Desk, Treasurer, Profile Media Moderator, Staff
Member, and Volunteer. Templates pin an exact immutable role-bundle version,
default headcount, and capacity codes.

## Organization structure projection

Workforce mounts one **Organization structure** overview with same-shell
management child pages at the exact selected-edition route and backs other
clients with the strict API described below. The read projection is:

```text
GET /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/structure
```

The projection requires `workforce.view_structure` effective at the exact
edition. Department- or resource-only authority is too narrow for the complete
tree, and `workforce.manage_structure` by itself does not imply read. Active
platform-administrator oversight is explicit and creates no convention
relationship. Route scope is resolved and policy-filtered before organization
or edition names are loaded, and both the HTML and API adapters repeat a fresh
final decision before returning the name-bearing result.

The response composes nested Department relationships, Positions, reporting
labels, current minimized holders, and each holder's other current operational
roles. It deliberately excludes login handle, email, account state/kind,
assignment identifiers, document/application/profile data, reason text, and
authority provenance. Identity labels are queried only after the workforce
relationship is time-effective, the linked RoleAssignment agrees with one of
the supported exact edition/Department/resource scope shapes, authorization
confirms the assignment's current pinned lineage, and identity confirms the
account is an active person. A missing, malformed, revoked, or stale lineage
therefore releases no holder name.

The projector owns fixed ceilings of 256 Departments, 1,024 Positions, 4,096
effective holder relationships, depth 32 for both Department and Position
reporting graphs, and 16,384 expanded `other_roles` edges. Row-limited queries
use limit-plus-one. The output is either one complete, stably ordered tree or
`structure_limit_exceeded` with no Department rows; it never silently
truncates. Cycles and unavailable parents fail through a generic dependency
boundary rather than being repaired, promoted, or partially shown.

The current read executes every Department, Position, assignment,
identity-label, and governance query inside one short repeatable-read,
read-only snapshot. It returns the exact edition structure version observed in
that snapshot, then compares it with a fresh read-committed control probe. One
movement retries the complete read exactly once; a second movement fails
through the generic name-free dependency boundary instead of releasing a
mixed-version tree. The fresh final authorization check remains independently
required because snapshot coherence is not proof of current authority.

After the fresh final decision, HTML and API append one minimized
`workforce.structure.read` sensitive-read audit with exact scope, source
channel, outcome, obligation, and only policy version, route name, and HTTP
method as safe metadata. Child GET pages and audited POST validation/conflict
rerenders preserve their actual route and method provenance. Audit persistence
precedes disclosure; failure returns a generic name-free `503` and releases no
holder label or partial hierarchy.

ADR 0042 removed the former public-roster rehearsal. Repository fixtures and
tutorials use synthetic people only; public labels never become accounts,
appointments, assignments, or authority.

ADR 0045 defines **Organization structure** at the selected-edition
route documented in
[`09-organization-structure.md`](../product/page-contracts/09-organization-structure.md).
Its governance-anchored projection is deliberately composed from two sources:

```text
Executive Board — minimized OrganizationRepresentation anchor
  -> Convention Coordination — top-level edition-owned Department
       -> operational and nested edition Departments
```

Executive Board is never copied into Department, Position, PositionAssignment,
or a generic group. Convention Coordination has no persisted Department parent; the page
places it visually beneath the organization-owned governance anchor. Every
other parent edge remains an exact same-organization, same-edition Department
relationship. Neither visual nor Department ancestry implies authority.

The implemented management slice owns one
workforce-owned edition structure aggregate with monotonic optimistic
versioning and shared application services for built-in-template application
plus Department create, complete update/reparent/order, retire, and protected
delete. Browser creation and reparenting append within the selected sibling
level under the aggregate lock, a normal edit preserves its unique placement,
and saving an old duplicate placement moves the edited Department into the
nearest following free position. The browser neither renders nor accepts the
numeric rank; the strict API retains bounded explicit ordering for deliberate
integration clients. Workforce `0006` adds the aggregate and append-only
command receipts;
the stopped-writer `0007` migration reconciles legacy trees and installs the
complete writer/evidence boundary. Additive Workforce `0008` follows every
current cross-module Department-FK creator and extends the closed deletion
contract to Applications, Charities, Logistics, Registration, and Venues. The
overview, three child GET page shapes, five POST actions, strict GET plus five
API mutations, and exact navigation now mount those shared services without
reopening specialist Department writes.

### Workforce task workspace

Convention work exposes `/admin/workspace/?view=workforce` as a task-oriented
reader over the same strict exact-edition projection. It is not a duplicate
Department writer and does not revive the retired `?view=structure` page. It
presents five dependent stages:

```text
Structure -> Positions -> Assignments -> Availability -> Shifts
```

The first three stages summarize implemented records: active Departments,
Position purpose/reporting/state, approved headcount, vacancies, and minimized
current holders. **Open structure** reaches Department management; **Manage
positions**, **Create Position**, and per-Position **Manage** actions reach the
purpose-built Position workspace when a fresh exact-edition policy decision
permits it. Public opportunities and the signed-in person's onboarding
documents remain separate continuation links. Non-staff organizers receive no
link to Django PositionAssignment records they cannot access; Django staff with
independent model permission may still receive a clearly labelled temporary
assignment-record link.

Availability and Shifts are deliberately noninteractive **Not available yet**
steps. No assignment is treated as availability, and no Position is treated as
a shift. Their placement records the intended HR-009/SCH-001/SCH-005 sequence
without adding a model, writer, authority, or schedule projection before those
transactional contracts are accepted.

### Built-in reference and independent copy

The immutable built-in `marucon-reference@1` is a repository-owned fictional
starter. Convention Coordination is its root. Its 21 operational Departments
are Attendee Services, Registration, Programme, Stage Production, Venue
Operations, Logistics, Volunteer Support, Safety, Accessibility, Technology,
Communications, Design & Publications, Exhibitors, Charity, Guest Relations,
Accommodation, Hospitality, Finance & Procurement, Partnerships, Live
Operations, and Archive & Handover.

The code-owned catalog and its application command are implemented and pinned.
The catalog is immutable, accepts only the exact versioned identifier,
validates unique bounded fields and one parent-before-child root graph, rejects
any Executive Board Department, and computes canonical UTF-8 JSON plus pinned
SHA-256 content evidence. Convention Coordination is the sole root and all 21
operational records are direct children.

The mounted command adapters let an authorized manager apply that exact version only
to an empty Draft or Preparing edition workforce structure. One atomic,
idempotent application copies 22 independent Department rows and retains
immutable source code, version, digest, actor, retry, correlation, request
digest, and resulting-version provenance in the aggregate and receipt.
It does not create or infer representation, people, membership, participation,
roles, capabilities, Positions, opportunities, applications, onboarding,
assignments, registration, or public-roster relationships. A later built-in
version never mutates an earlier source or an already copied edition.

### Department command boundary

Organization structure reads require `workforce.view_structure` effective at the exact edition;
department-only authority is too narrow for the complete tree. Mutations also
require `workforce.manage_structure`, except for explicit non-participating
platform oversight. Board representation or hierarchy position by itself is
not that capability. The exact access header and navigation repeat those same
decisions and disclose no foreign tenant or hidden principal.

Commands accept only bounded name, optional description, exact same-edition
parent, display order, expected structure version, reason, and operation-
specific retry or exact-name confirmation. Scope, code, actor, lifecycle,
template digest, timestamps, output version, audit, and event fields are
server-owned. Unknown fields, stale versions, cross-tenant parents, cycles, and
silent truncation fail closed. Successful changes advance the aggregate once
and commit minimized audit, `workforce.structure.changed.v1`, and outbox
evidence together; normalized no-ops write nothing.

Browser mutations use closed strict forms, CSRF, private `no-store` rendered
form/responses, separate GET and POST routes, and POST/Redirect/GET on success. Validation or
conflict rerenders retain the submitted expected version and browser retry key
and require an explicit reload when stale. The overview truthfully changes its
source summary from **Built-in reference applied** to **Reference copy
changed** after an edition copy diverges.

Retirement preserves used Departments and is refused while a current child,
open Position, active assignment whose term has not ended, current-or-future
unclosed authority, or another live dependency
would become misleading. Hard deletion requires exact current-name
confirmation and an unused leaf with no cross-module or operational history;
it never cascades. An immutable Position resource binding is retained history,
not a live retirement dependency: it survives retirement and continues to
block hard deletion, while the binding service rejects every new binding below
a retired Department. Ready, Live, Closing, Archived, and Cancelled editions
remain read-only until a separate structure change-control design is accepted.

Position management is now the separate HR-012 workflow described below. The
built-in Department template still creates no Lead, Deputy, or Volunteer
Positions; a manager deliberately creates each responsibility from a published
organization Position template.

## Positions and published opportunities

A Department belongs to exactly one organization and edition and may have one
same-edition parent. A Position belongs to one Department, may report to
another current same-edition Position, pins one published Position template
and exact historically valid RoleBundle issuance, and has explicit approved
headcount. PostgreSQL rejects cross-organization or cross-edition relationships
and reporting cycles even when ORM validation is bypassed.

The purpose-built Position workspace requires both
`workforce.view_structure` and `workforce.manage_structure` at the exact
edition, except for explicit attributed platform oversight. The overview is
bounded and groups Positions beneath human Department names. Creation offers
only active Departments, current reporting Positions, and published
organization templates whose RoleBundle provenance is valid. Route scope and
authorization are resolved before input parsing or name disclosure.

One idempotent creation transaction persists all of the following or none:

- a `planned` Position with immutable organization, edition, Department,
  template, RoleBundle, code, capacity codes, creator, and creation version;
- its one-to-one private `draft` volunteer opportunity;
- its exact typed `workforce.position` resource binding;
- one aggregate version step and immutable command receipt containing the
  retained reason; and
- minimized audit, domain event, and outbox evidence.

Current Positions may completely replace title, purpose/responsibilities,
approved headcount, and optional reporting Position. Headcount cannot fall
below proposed and active assignments. Normalized no-ops advance no version and
write no evidence. The detail view keeps immutable role meaning next to current
operational details and shows its own newest-first command reasons; the
Organization structure overview shows recent structure reasons. Existing
legacy Positions receive no invented creation actor or receipt; their first
real governed Position or opportunity change records its actual resulting
version while leaving the unknown creation version null.

The paired opportunity separately owns applicant-facing headline, description,
optional opening/closing times, visibility when filled, and lifecycle. Its
allowed transitions are draft to published, published to closed, closed back to
published, and any non-withdrawn state to final withdrawn. Publishing a planned
Position opens it in the same structure version. A published filled Position
may remain discoverable when `visible_when_filled` is enabled but accepts no
further applications. Publication creates no application, assignment,
participation, RoleAssignment, capability grant, or schedule commitment.
HTML forms use the edition's IANA time zone and reject ambiguous or nonexistent
local minutes. API timestamps must carry `Z` or an explicit numeric UTC offset.

Position closure is one-way, requires the exact current title and a retained
reason, and closes the paired opportunity unless it is already closed or
withdrawn. It refuses a proposed or active assignment, a non-closed direct
report, or current/future Position-scoped CapabilityGrant or RoleAssignment.
The owning assignment, reporting, or access workflow must resolve the
dependency; Position management never silently revokes or deletes it. The
closed Position remains a readable historical record and cannot be edited,
published, reopened, or deleted.

Position and VolunteerOpportunity specialist records are inspection-only. The
preserved bootstrap and local synthetic fixture can retain internally
consistent legacy rows, but every governed mutation uses the shared commands.
Workforce `0010` requires an exact same-version Position command receipt for
governed Position/opportunity changes and rejects direct deletion, immutable
identity/scope/template/role/capacity changes, invalid opportunity transitions
or windows, invalid reporting graphs, and changed governed rows without
evidence.

Operational Position and PositionAssignment writers join one canonical
identifier-only edition write boundary before taking either row lock or
performing either write. The order is the outer structure-generation barrier,
authority-provenance barrier, retired-Department barrier, then locked
Organization, ConventionSeries, EventEdition, exact-edition mutex, current
Department, Position, and PositionAssignment where applicable. Every tenant
edge and retirement state is rechecked from persisted identifiers without
loading a label. Governed Position commands, assignment proposal saves, and
assignment activation use this boundary; activation also locks an identified
proposal and the current assignment set before issuing authority or
participation evidence. A retired Department cannot receive a new Position,
proposal, activation, or binding.
The locks live through the outer transaction so nested authority and binding
services only rejoin already-held outer barriers.

The local/test synthetic fixture follows the same edition writer boundary.
On a fresh database it creates each current-edition demo Department through a
deterministic Organization structure retry receipt while the edition is still Draft or
Preparing, then creates the Position and assignment under the edition mutex
and installs the Position resource binding. Reruns replay the receipt and may
verify the already-complete workforce example after the edition has moved to a
read-only lifecycle; they cannot create a missing or partial example there.
An older deterministic demo Department is preserved as legacy data rather than
renamed or replaced.

An application is an expression of interest only. Accepting or reviewing it
does not grant a role, capacity, or access. Position management deliberately
ends before assignment proposal and independent approval.

## Reviewed onboarding documents

An onboarding document type is an edition-owned, versioned agreement such as a
Volunteer NDA. Activating it freezes its wording, size limit, and retention
notice; replacement requires a new version.

Staff creates a document request for an exact account and document version.
The account can upload a PDF from its convention profile or API. Maru limits
size, verifies PDF signature and media type, computes a SHA-256 digest, and
requires malware-scanner evidence. The exact submitted file stays private.
Review requires `workforce.manage_documents` and a reason.

Local debug settings deliberately provide an unscanned rehearsal adapter so a
developer can exercise the workflow without ClamAV. It is labelled
`local_rehearsal_clean_unscanned`, cannot activate outside `DEBUG`, and does
not weaken production's fail-closed scanner requirement.

Approved evidence is immutable at the database layer. A rejected request may
receive a replacement; a new agreement version needs a new request.

## Assignment and authority

Position activation requires:

- a non-closed position below its headcount;
- every document type attached to the position approved for the recipient;
- two distinct controllers who both hold
  `workforce.manage_assignments` and `authorization.manage_roles`;
- an explicit reason and effective interval; and
- the recipient, role bundle, organization, and edition to agree.

The transaction invokes the authorization module's dual-control role command,
activates the person's edition participation, adds the configured
`staff`/`volunteer` capacities and a stable `position.<position-code>`
capacity, records the position assignment, updates filled/open state, writes
both controller audits, and publishes a registered domain event. A failure
rolls the whole operation back.

The current position-assignment Advanced-record form identifies the second
controller and checks their live authority. A production approval inbox with a
separate approver session and step-up remains future work; selecting an
identity in the local rehearsal must not be represented as that future UX.

## Interfaces

Reference web routes:

```text
/admin/workspace/?view=workforce
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/positions/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/positions/new/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/positions/<position-id>/
/volunteer/<edition_id>/
/volunteer/<edition_id>/<opportunity_id>/apply/
/volunteer/<edition_id>/documents/
/volunteer/<edition_id>/documents/<request_id>/upload/
```

Versioned client routes:

```text
GET  /api/v1/public/editions/<edition_id>/volunteer-opportunities
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/opportunities/<opportunity_id>/applications/me
GET  /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/documents/me
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/documents/me/<request_id>/upload
```

Mounted Organization structure API surface:

```text
GET    /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/structure
POST   /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/structure/template-applications
POST   /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/departments
PUT    /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/departments/<department_id>
POST   /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/departments/<department_id>/retire
DELETE /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/departments/<department_id>
```

Mounted Position management API surface:

```text
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/positions
PUT  /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/positions/<position_id>
PUT  /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/positions/<position_id>/opportunity
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/positions/<position_id>/close
```

Position creation requires a canonical `Idempotency-Key`; first success returns
`201` and identical replay returns `200`. Other successful mutations return
`200`. Inputs are closed strict JSON objects. Authorization precedes header and
body parsing; denied scope is name-free `403`, an authorized unavailable
Position or relationship is `404`, validation is `400`, state/version/retry or
dependency conflict is `409`, and an unavailable canonical dependency is
`503`. Responses expose only `position_id` and resulting structure version.

The structure GET now returns the bounded complete-tree and minimized
governance-anchor response used by Organization structure read projection. It accepts no query parameters.
OpenAPI declares its `200` response and typed RFC 9457 `400`, `403`, and `503`
problems; generated TypeScript types retain the recursive Department schema.
The response `source` is a closed, `kind`-discriminated four-variant union.
`empty`, `manual`, and `legacy_existing` expose only `kind`; the
`builtin_template` variant additionally requires `template_code` and a
positive `template_version`. Optional template fields never leak into the
non-template variants.
The old React structure destination is removed, so the generated API contract
does not imply a duplicate browser workflow. New mutation routes must use the
same application services as HTML. Template application and Department create
require a caller-supplied canonical UUID `Idempotency-Key`; an identical replay
returns `200`, while the first successful creation returns `201`. Update,
retire, and protected delete return `200`. DELETE has a required closed JSON
body. Mutation problems declare `400`, non-disclosing `403`, authorized
target-only `404` where applicable, `409`, and `503`; template application has
no `404`. Authorization precedes header/body parsing; every route locator is
untrusted and is resolved and authorized from persisted scope. Generated
OpenAPI/client output remains deterministic.

Specialist records:

```text
/admin/workforce/department/
/admin/workforce/positiontemplate/
/admin/workforce/position/
/admin/workforce/volunteeropportunity/
/admin/workforce/volunteerapplication/
/admin/workforce/onboardingdocumenttype/
/admin/workforce/onboardingdocumentrequest/
/admin/workforce/positionassignment/
```

These specialist routes are not the accepted product mutation contract. The
shared commands and migration fences are active, so Department, Position, and
Volunteer opportunity records are inspection-only here. Managers use the
strict Organization structure and Position management HTML/API adapters.
PositionAssignment remains a temporary staff/model-permission-gated specialist
workflow until separate proposal and independent-approval pages are accepted.

## Database integrity and recovery

Workforce `0004` is the stopped-writer integrity stage of ADR 0041. It installs
database enforcement before its count-only preflight and provides these
guarantees even when model validation is bypassed:

- every department and parent share the exact organization and edition;
- department reparenting is serialized within that scope, so raw, bulk, and
  concurrent writes cannot create a hierarchy cycle;
- every position agrees with its edition, department, organization template,
  role bundle, and reporting scope, while serialized raw or concurrent writes
  cannot create a reporting-line cycle;
- a `workforce.position` resource binding freezes that position's
  organization, edition, and department identity; and
- linked position-assignment role evidence remains valid in both write
  directions. Existing exact-edition evidence with no department or resource
  remains edition-wide. A narrower assignment must name the position's exact
  department or its exact typed position binding; organization-wide, sibling,
  foreign-edition, and foreign-position evidence is rejected.

The migration reports the number of retained edition-wide workforce role
assignments separately and does not insert resource bindings or reinterpret
their historical intent. Reproducible binding backfill and the final downgrade
fence belong to the following authorization migration. After the first
scope-v2 write, retain compatible writers and fix forward or restore the whole
database to a mutually consistent pre-write point; do not reverse this guard
layer independently.

Workforce `0005` hardens the directly executable role-evidence matcher and both
persistent trigger callers. It validates code-owned pre/post source hashes,
uses `CREATE OR REPLACE` to preserve OID, owner, and ACL, fixes
`pg_catalog, public, pg_temp`, qualifies every events, workforce,
authorization, and participation relation plus internal helper calls, restores
the exact `0004` definitions only while dormant, and keeps an owning-module
activation fence even if authorization `0009`'s recorder row is missing.

Workforce `0003` installs IDN-011 guards for volunteer applications,
onboarding-document requests, and position assignments. Each insert or update
locks the exact subject identity row before checking that it remains a person.
A deferred identity trigger prevents person-to-platform reclassification while
any of the three subject relationships survives. The transactional migration
creates those guards before its final count-only legacy-data preflight, so a
concurrent writer cannot enter between the scan and protection becoming
effective.

These checks complement the existing department, document-type, position,
onboarding-evidence, and assignment-scope guards. They do not turn applications
or requests into authority and do not inspect actor/provenance foreign keys.
Use the maintenance-window, reconciliation, and fix-forward procedure in
[`idn011-convention-subject-migration-and-recovery.md`](../operations/idn011-convention-subject-migration-and-recovery.md).

Workforce `0006` additively creates the structure control and immutable command
receipt schema. Workforce `0007` runs under a stopped-writer boundary,
preserves every existing Department identifier and parent edge, creates at
most one `legacy_existing` control for each populated edition, and never
manufactures a template receipt. It does not infer Executive Board, Helper
Board, people, Positions, assignments, authority, or template provenance from
names. Its preflight and database triggers enforce exact scope, bounded acyclic
hierarchy, one aggregate version step per evidenced command, immutable source
and retry receipts, non-cascading retirement/deletion rules, and fix-forward
downgrade behavior. Production readiness fingerprints all 19 Organization
structure trigger functions and all 33 exact attachments, requires the current Workforce
migration recorder chain through `0010`, and verifies the exact 13-reference
Department FK inventory;
the runtime login cannot invoke those helpers directly, disable them, or
bypass their stopped-writer protocol. Reversing `0008` restores the exact
`0007` helper, which safely refuses deletion while any successor reference is
still installed.

Workforce `0010_position_structure_commands` extends that aggregate protocol to
Position and VolunteerOpportunity rows. Its preflight refuses a pre-existing
Position whose template and RoleBundle disagree. Internally consistent legacy
rows remain readable with null Position-command versions; the migration does
not invent an actor, reason, or receipt. A first governed change may set only
the real last-changed version while retaining a null unknown creation version.
Governed writes require the current
structure version and exactly one immutable receipt whose action, Position,
changed fields, actor, Department scope, and resulting version match the row
transition. The database rejects immutable identity/scope/template/role/
capacity mutation, reporting cycles, invalid opportunity windows or lifecycle
transitions, direct deletion, and changed governed rows without exact command
evidence. After live Position writes, recovery fixes forward or restores the
complete database to a mutually consistent pre-write point; it does not reverse
this guard independently.

## Organization structure verification

The 2026-08-23 owner rehearsal adds focused evidence for the read journey: the
non-staff convention chair reached Workforce from Registration, retained the
exact MaruCon 2026 host context, saw the complete five-stage orientation and
current Position/vacancy projection, received no staff-only specialist links,
and followed **Open structure** to canonical Department management. The 390 CSS-pixel view
had one H1, one `main`, no duplicate identifiers, and no horizontal overflow.
Frontend tests cover the populated journey, non-staff link boundary,
non-disclosing `403`, and automated axe analysis. Position command, API, and
HTML tests separately cover the manager mutation role; the owner-safe
assignment journey and last two stages remain unimplemented.

The Position management focus covers normalized idempotent creation, paired
opportunity and typed binding, immutable provenance, complete updates,
publication and republishing, newest-first direct reason history, legacy-row
first-change adoption, the bounded initial-Chair recovery exception, reporting
cycles, headcount, assignment/direct-report/authority closure fences, one-way
closure, atomic audit/event/outbox rollback, authorization-before-lookup,
cross-edition isolation, strict API objects and route methods, private HTML
responses, a non-staff owner creation-through-closure journey, view-only denial,
and direct database-write rejection. OpenAPI validation, generated TypeScript
types, frontend type checking/build, migration drift, Ruff, mypy, documentation
validation, and rendered owner-browser evidence remain part of the same change
gate rather than being inferred from command tests.

The historical Organization structure read-projection focus covered 52
Organization structure, structure API,
capability-catalog, and template tests. They covered the exact access matrix,
denial before name lookup,
fresh final authorization, current exact-role and active-person holder checks,
all code-owned ceilings, depth and expanded-edge bounds, recursive OpenAPI,
safe `400`/`403`/`503` problems, governance minimization, audit-before-
disclosure and audit-failure `503`, stable query-count ceilings, and the
explicit no-partial-tree overflow. The standalone populated
query-count regression also passes. Adjacent navigation/shell/admin/
representation coverage passes 65 tests. OpenAPI validation, generated-client
regeneration, TypeScript type checking, 20 Vitest tests, Vite production build,
focused Ruff, strict mypy for the changed source boundary, Django system check,
and whitespace checks pass. The definitive full repository gate also passes
1,239 tests at 90.35 percent branch coverage. Reliable responsive-browser
evidence for that read milestone remains pending. The later focused aggregate,
snapshot, command, migration, writer-boundary, trigger-readiness, concurrency,
and runtime-role suites now verify the Department management core. The adapter API focus
passes 48 tests covering strict inputs and types, exact authorization and
non-disclosure, idempotent replay/conflict, lifecycle/version/dependency
conflicts, rollback, CSRF/method handling, and the declared OpenAPI surface.
A fresh isolated PostgreSQL combined gate passes 159 tests in 102.89 seconds
across core/forms, Organization structure read and HTML mutations, mutation and adjacent
workforce APIs, exact-lineage navigation, and unified routing. The definitive
adapter-expanded repository invocation passes 1,693 tests in 1,653.43 seconds
at 90.50 percent total branch-inclusive coverage. Authenticated responsive,
keyboard, and automated-accessibility evidence is still pending. This remains
local repository evidence, not a production cutover or recovery certification.

The later Department-FK successor correction passes 9 focused PostgreSQL
cases for forward/reverse behavior, readiness, exact installed references,
successful protected deletion, raw tombstone deletion, and unknown-reference
failure. Six representative Registration historical-migration cases also pass
with graph-consistent Workforce targets. Focused Ruff, strict mypy,
byte-compilation, migration drift, and the migration-target unit matrix are
green.

The final canonical current-tree repository gate passed all 4,067 tests in
15,558.23 seconds (4:19:18) at 90.78 percent coverage. This is the current
repository acceptance result; the earlier focused and historical full-run
figures above remain milestone evidence rather than competing current totals.
It does not certify responsive Organization structure mutation-role behavior, representative
recovery, deployment, authority cutover, or production operation.

## Current limitations

Qualifications, person-owned availability, shifts, time records, assignment
proposal/ending/replacement UX, approval notifications, document download
through the REST API, and a separately authenticated approval inbox remain
work. Organization structure and Position management use the implemented
aggregate/version fence, bounded retry, shared commands, stopped-writer
migrations, and runtime trigger catalog. The focused owner read walkthrough and
automated Position mutation journey pass, but the complete width/zoom,
screen-reader, failure, and mutation-role matrix, ordinary production authority
reconciliation, real cutover, and representative restore/PITR evidence remain
open. The implemented assignment domain continues to prove the safe path from
a known person and reviewed agreement to scoped working access; its temporary
specialist form is not the accepted owner experience.
