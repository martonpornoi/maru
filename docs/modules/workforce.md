# Workforce module

Status: Position, hierarchy, opportunity, agreement, authority onboarding,
ADR 0041 containment, and Page 9a.0 bounded read projection implemented;
Page 9a.1 Department mutations remain pending
Last updated: 2026-08-02

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

Page 9a.0 mounts one read-only **Organization structure** page at the exact
selected-edition route and backs other clients with:

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

The current read executes several bounded queries without the future structure
aggregate/version fence. A concurrent Department, Position, assignment,
identity, or governance write could therefore yield a coherent but
cross-version composition. Page 9a.1 must introduce the accepted version fence
and retry/conflict behavior before mounting Department mutations. The fresh
final authorization check closes mid-read authority expiry/revocation; it does
not solve this separate data-snapshot risk.

After the fresh final decision, HTML and API append one minimized
`workforce.structure.read` sensitive-read audit with exact scope, source
channel, outcome, obligation, and only policy version, route name, and HTTP
method as safe metadata. Audit persistence
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
  -> Helper Board — top-level edition-owned Department
       -> operational and nested edition Departments
```

Executive Board is never copied into Department, Position, PositionAssignment,
or a generic group. Helper Board has no persisted Department parent; the page
places it visually beneath the organization-owned governance anchor. Every
other parent edge remains an exact same-organization, same-edition Department
relationship. Neither visual nor Department ancestry implies authority.

The accepted next management slice introduces one workforce-owned edition
structure aggregate with monotonic optimistic versioning and shared HTML/API
application services for built-in-template application plus Department create,
update, reparent, order, retire, and protected delete. The design is accepted;
those mutation services and schema are not implemented yet. Page 9a.0's route,
read projector, governance composition, strict GET API, exact navigation, and
focused backend verification are implemented independently of them.

### Built-in reference and independent copy

The immutable built-in `awoostria-reference@1` contains Helper Board plus 21
operational Department definitions: Art, Charity, Ceremonies, Dealers' Den,
Decorations, Events & Programming, Front Desk, Fursuit Support, Graphics
Design, Human Resources, IT, Legal & Compliance, Logistics, Maid Café,
Multimedia, PEER, Registration, Security, Social Media, Stage Tech, and Story.

The code-owned catalog is implemented and pinned. It is immutable, accepts only
the exact versioned identifier, validates unique bounded fields and one
parent-before-child root graph, rejects any Executive Board Department, and
computes canonical UTF-8 JSON plus pinned SHA-256 content evidence. Helper
Board is the sole root and all 21 operational records are direct children. Its
nine focused unit tests are included in the current 52-test Page 9 slice. The
catalog is not yet an application service: Page 9a.1 still owns receipt,
idempotent copy, structure-version, audit/event/outbox, and rollback behavior.

Page 9a.1 will let an authorized manager apply that exact version only to an
empty Draft or Preparing edition workforce structure. One atomic, idempotent application
copies 22 independent Department rows and retains immutable source code,
version, digest, actor, retry, correlation, and resulting-version provenance.
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

Retirement preserves used Departments and is refused while a current child,
open Position, effective assignment or authority, or another live dependency
would become misleading. Hard deletion requires exact current-name
confirmation and an unused leaf with no cross-module or operational history;
it never cascades. Ready, Live, Closing, Archived, and Cancelled editions remain
read-only until a separate structure change-control design is accepted.

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

Page 9 API surface; only the GET route is currently mounted:

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
The old React structure destination is removed, so the generated API contract
does not imply a duplicate browser workflow. New mutation routes must use the
same application services as HTML, strict problems, route-owned scope, UUID
`Idempotency-Key` for create/application, and deterministic OpenAPI/client
generation.

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

These specialist routes are not the accepted Page 9 mutation contract. Once
the shared commands and migration fence are active, Department mutations
covered by Page 9 become inspection-only here. Position writes remain a
separate Page 9b decision rather than an implicit exception.

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

ADR 0045's future Page 9a.1 additive migration must preserve every existing
Department identifier and parent edge, create at most one structure-control aggregate for
each populated edition, and mark it as legacy-existing without inventing a
template receipt. It must never infer Executive Board, Helper Board, a person,
Position, assignment, authority, or template version from names. Preflight and
database checks cover exact scope, cycles, immutable source receipt, monotonic
aggregate version, incompatible direct writers, non-cascading retirement, and
downgrade/recovery behavior. This paragraph is an accepted mutation/migration
contract, not evidence that the structure-control schema exists. Page 9a.0
adds no migration and does not change current Department write compatibility.

## Page 9a.0 verification

Focused Page 9, structure API, capability-catalog, and template tests pass 52
tests. They cover the exact access matrix, denial before name lookup,
fresh final authorization, current exact-role and active-person holder checks,
all code-owned ceilings, depth and expanded-edge bounds, recursive OpenAPI,
safe `400`/`403`/`503` problems, governance minimization, audit-before-
disclosure and audit-failure `503`, stable query-count ceilings, and the
explicit no-partial-tree overflow. The standalone populated
query-count regression also passes. Adjacent navigation/shell/admin/
representation coverage passes 65 tests. OpenAPI validation, generated-client
regeneration, TypeScript type checking, 19 Vitest tests, Vite production build,
focused Ruff, strict mypy for the changed source boundary, Django system check,
and whitespace checks pass. The definitive full repository gate also passes
1,239 tests at 90.35 percent branch coverage. Reliable responsive-browser
evidence for this slice remains pending.

## Current limitations

Qualifications, availability, shifts, time records, acceptance decisions,
position ending/replacement UX, approval notifications, document download
through the REST API, Page 9a.1 Department management, Page 9b Position
editing, and a separately authenticated approval inbox remain work. Page
9a.0's read-only HTML route, GET API, bounded query, exact access/discovery
behavior, governance anchor, generated schema, and focused backend tests are
implemented. Its concurrent multi-query structure-version fence, browser/
accessibility matrix, and owner walkthrough remain open. ADR 0045 and the Page
9 contract define the Department editor but do not claim its schema, commands,
mutation routes, migration rehearsal, or recovery evidence are complete. The
implemented first assignment slice continues to prove the safe path from a
known person and reviewed agreement to scoped working access.
