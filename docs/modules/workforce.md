# Workforce module

Status: Position, hierarchy, opportunity, agreement, authority onboarding,
ADR 0041 containment, and Page 9a.1's version-fenced read, aggregate, commands,
stopped-writer database core, and strict HTML/API Department mutation adapters
are accepted in the canonical current tree; responsive, recovery, deployment,
and production acceptance remain gated
Last updated: 2026-08-11

## Purpose and requirements

`maru.workforce` owns the executable HR-007, HR-008, and HR-010 slices defined
by ADRs 0019 and 0028, the accepted HR-011 edition-structure boundary, and
IDN-011's non-participation boundary. It turns an edition responsibility into
explicit structure:

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
establish first organization authority. A new Draft organization uses Page 8's
purpose-built Executive Board lifecycle. The service below remains preserved
recovery evidence for legacy reconciliation only; it must not compete with Page
8 or be used without a separately approved procedure.

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
Page 9 structure command used by every supported Department writer. Its
correlation identifier is also the deterministic retry key and request
identifier, so the immutable receipt ties the attributed platform actor to
structure version 1. Before creating the Department, Position, or assignment,
the service joins the canonical edition write scope; Position and assignment
writes additionally lock the active Department target. This keeps recovery
bootstrap inside the Page 9, provenance, retirement, and edition-mutex lock
order without turning the platform administrator into a convention subject.

The former browser ceremony and
`/api/v1/management/convention-bootstrap` endpoint are not mounted. Their old
tests and implementation remain historical recovery evidence; they are not a
second setup path beside Page 8. Candidate reads and mutations must use an
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

Page 9a.1 mounts one **Organization structure** overview with same-shell
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

ADR 0045 defines Page 9 **Organization structure** at the selected-edition
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

Page 9 reads require `workforce.view_structure` effective at the exact edition;
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

Position editing is Page 9b. It must first define immutable PositionTemplate
and RoleBundle selection, ADR 0044 dual-control provenance, typed binding,
opportunity, lifecycle, reporting-cycle, and recovery behavior. The built-in
Department template creates no Lead, Deputy, or Volunteer Positions.

## Positions and published opportunities

A department belongs to exactly one organization and edition and may have one
same-edition parent. A position belongs to one department, may report to
another same-edition position, pins one template and role bundle, and has an
explicit headcount. PostgreSQL rejects cross-organization or cross-edition
relationships even when ORM validation is bypassed.

Creating a position automatically creates its one-to-one volunteer
opportunity. Organizers may publish, close, or withdraw the opportunity and
set application dates. A published filled position remains in the public list
when `visible_when_filled` is enabled, but it no longer accepts applications.
Headcount greater than one supports roles with multiple holders.

The Position specialist-record save and preserved workforce bootstrap also
call authorization's explicit typed-binding service after the Position is
saved. The service re-reads the locked row instead of trusting submitted scope,
and the surrounding transaction rolls Position creation back if its exact
immutable authorization binding cannot be established. Any future production
import or application service that creates Positions must make the same call;
direct ORM creation is only a low-level building block, not a complete live
creation workflow.

Operational Position and PositionAssignment writers join one canonical
identifier-only edition write boundary before taking either row lock or
performing either write. The order is the outer Page 9 generation barrier,
authority-provenance barrier, retired-Department barrier, then locked
Organization, ConventionSeries, EventEdition, exact-edition mutex, current
Department, Position, and PositionAssignment where applicable. Every tenant
edge and retirement state is rechecked from persisted identifiers without
loading a label. Position specialist saves, assignment proposal saves, and
assignment activation use this boundary; activation also locks an identified
proposal and the current assignment set before issuing authority or
participation evidence. A retired
Department cannot receive a new Position, proposal, activation, or binding.
The locks live through the outer transaction so nested authority and binding
services only rejoin already-held outer barriers.

The local/test synthetic fixture follows the same production writer boundary.
On a fresh database it creates each current-edition demo Department through a
deterministic Page 9 retry receipt while the edition is still Draft or
Preparing, then creates the Position and assignment under the edition mutex
and installs the Position resource binding. Reruns replay the receipt and may
verify the already-complete workforce example after the edition has moved to a
read-only lifecycle; they cannot create a missing or partial example there.
An older deterministic demo Department is preserved as legacy data rather than
renamed or replaced.

An application is an expression of interest only. Accepting or reviewing it
does not grant a role, capacity, or access.

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

Mounted Page 9 API surface:

```text
GET    /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/structure
POST   /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/structure/template-applications
POST   /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/departments
PUT    /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/departments/<department_id>
POST   /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/departments/<department_id>/retire
DELETE /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/departments/<department_id>
```

The structure GET now returns the bounded complete-tree and minimized
governance-anchor response used by Page 9a.0. It accepts no query parameters.
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

These specialist routes are not the accepted Page 9 mutation contract. The
shared commands and migration fence are active, so Department records are
inspection-only here. Managers use the strict Page 9 HTML/API mutation
adapters. Position writes remain a separate Page 9b decision rather than an
implicit exception.

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
downgrade behavior. Production readiness fingerprints all 14 Page 9 trigger
functions and all 28 exact attachments, requires both Workforce migration
recorder rows, and verifies the exact 13-reference Department FK inventory;
the runtime login cannot invoke those helpers directly, disable them, or
bypass their stopped-writer protocol. Reversing `0008` restores the exact
`0007` helper, which safely refuses deletion while any successor reference is
still installed.

## Page 9 verification

The historical Page 9a.0 projection focus covered 52 Page 9, structure API,
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
and runtime-role suites now verify the Page 9a.1 core. The adapter API focus
passes 48 tests covering strict inputs and types, exact authorization and
non-disclosure, idempotent replay/conflict, lifecycle/version/dependency
conflicts, rollback, CSRF/method handling, and the declared OpenAPI surface.
A fresh isolated PostgreSQL combined gate passes 159 tests in 102.89 seconds
across core/forms, Page 9 read and HTML mutations, mutation and adjacent
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
It does not certify responsive Page 9 mutation-role behavior, representative
recovery, deployment, authority cutover, or production operation.

## Current limitations

Qualifications, availability, shifts, time records, acceptance decisions,
position ending/replacement UX, approval notifications, document download
through the REST API, Page 9b Position editing, and a separately authenticated
approval inbox remain work. The HTML/API Page 9 read and Department mutation
adapters use the implemented aggregate/version fence, bounded retry, shared
commands, stopped-writer migration, and runtime trigger catalog. Reliable
browser/accessibility states, the owner
walkthrough, ordinary production authority reconciliation, real cutover, and
representative restore/PITR evidence remain open. The implemented first
assignment slice continues to prove the safe path from a known person and
reviewed agreement to scoped working access.
