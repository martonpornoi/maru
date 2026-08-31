# Workforce module

Status: Position, hierarchy, opportunity, agreement, authority onboarding,
ADR 0041 containment, version-fenced Department and Position management, and
the owner-safe Position assignment lifecycle with shared strict HTML/API
commands, person-owned deliberately shared Availability, and governed Shift
demand through commitment completion with stopped-writer database enforcement
are implemented in the canonical current tree; Workforce-only assignment no
longer manufactures attendee Participation evidence; complete rendered
accessibility, portability, post-edition Availability disposal, recovery,
deployment, and production acceptance remain gated
Last updated: 2026-08-31

## Purpose and requirements

`maru.workforce` owns the executable HR-007 through HR-014 slices defined by
ADRs 0019, 0028, 0075, 0076, 0077, 0078, and 0080, plus IDN-011,
IDN-014, EVT-006, UX-030, and NFR-013. It turns an edition responsibility into
explicit structure and person-controlled planning input:

```text
department hierarchy
  -> position from an immutable organization template
  -> always-present publishable volunteer opportunity
  -> application and requested agreement evidence
  -> independently approved position assignment
  -> exact role-bundle version and, only for an adopted Participation profile,
     historical participation capacities
  -> private or deliberately shared person-owned availability
  -> Position demand, personal claim, independent confirmation, and locked coverage
```

It does not infer access from a job title, an application, a registration
answer, an uploaded file, or a profile label. Authority remains owned by
`maru.authorization`; convention participation remains owned by
`maru.participation`.

## Workforce-only adoption boundary

`workforce_only@1` is the first executable bounded-adoption profile. It keeps
the complete Structure → Positions → assignments → Availability → Shifts
journey while excluding attendee Participation, Registration, payments,
attendance, and unrelated modules. The guided platform workflow is documented
in the [Set up Workforce contract](../product/page-contracts/workforce-only-adoption-setup.md)
and the [adoption and recovery runbook](../operations/workforce-only-adoption-and-recovery.md).

Assignment remains responsibility plus exact authority evidence in every
profile. The immutable manifest now selects exactly one versioned assignment-
evidence adapter. `full_convention@1` pins
`workforce.assignment.participation-required@1`, which creates or activates
Participation capacities and requires the assignment pointer to be non-null.
`workforce_only@1` pins
`workforce.assignment.participation-excluded@1`, so approval stores no
`Participation` or `ParticipationCapacity` and the nullable pointer remains
empty. An unknown profile or a manifest that pins neither or both adapters
fails closed. Model validation and the PostgreSQL assignment guard require the
resulting evidence shape to match; a null full-convention pointer or non-null
Workforce-only pointer is an integrity conflict. Ending a Workforce-only
assignment revokes authority and retains assignment evidence without touching
Participation. Migration `0014` introduced the profile-matched shape;
additive migration `0015_exact_assignment_adoption_profile` replaces its
code-only database branch with literal `full_convention@1` and
`workforce_only@1` pairs. The installed trigger rejects every unknown pair
before an assignment write. `0015` refuses downgrade after any governed
assignment evidence exists.

Candidate discovery already accepts a purpose-bounded relationship: an active
organization membership, Position application, onboarding request, or prior
Workforce history can make an active person selectable without Participation.
Account existence alone is not sufficient, and selection creates no attendee
state.

Both current exact manifests pin the versioned, copy-on-write
`workforce.structure-template.marucon-reference@1` and
`workforce.position-template.workforce-volunteer@1` catalog entries. The
governed safe-starter provisioning route remains limited to the exact
Workforce-only setup contract. Commands recheck those literal entries against
the edition profile after locking its scope; catalog growth therefore cannot
enter an existing edition implicitly. General partner imports, a complete
continuity export, printable rota, offline/manual reconciliation, and automated
profile removal remain declared production gates rather than hidden promises.

After an accountable operator creates the first Department, a fresh
Workforce-only organization may still lack the immutable Position meaning
required by Position creation. The Positions workspace can create one
code-owned **Workforce volunteer** starter under a different accountable
controller's approval and a retained reason. Its RoleBundle contains only
`events.view_basic` and `workforce.view_structure`; the template carries the
semantic `volunteer` label. The action grants nobody authority and creates no
Position, opportunity, person relationship, assignment, RoleAssignment,
Participation, Registration, payment, Availability, or Shift. Incompatible
organization templates are filtered from the Workforce-only editor rather than
letting an unadopted capability enter through reusable configuration.

Exact routed editions drive the management menu and workspace selector even
without saved session context. Public Workforce pages use a Volunteer-only
shell, and personal Workforce pages focus navigation on My Maru and My
Workforce. Public opportunity discovery requires an exact profile that adopts
Workforce. Assignment, Availability, Shift, onboarding-document, and personal
route discovery additionally require the versioned `workforce.self@1` adapter;
both current v1 profiles pin it, while an unknown future version fails before
policy or relationship data is projected. These focused surfaces make the
purpose boundary legible while policy and database controls remain
authoritative.

A platform administrator may initiate or review bootstrap work as an attributed
actor, but cannot be the subject of a volunteer application, onboarding request,
position assignment, or Availability plan. Model validation and PostgreSQL
reject the platform-only subject classification without rejecting
`reviewed_by`, `requested_by`, `proposed_by`, or `approved_by` actor provenance.

## Legacy empty-organization bootstrap

ADR 0040 supersedes this broad workforce ceremony as the normal way to
establish first organization authority. A new Draft organization uses
Representation & access's purpose-built truthful representation lifecycle
under ADR 0080. The service below remains preserved
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
Accountable representation — minimized truthful OrganizationRepresentation anchor
  -> Convention Coordination — top-level edition-owned Department
       -> operational and nested edition Departments
```

The accountable representation is never copied into Department, Position, PositionAssignment,
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

All five stages summarize implemented records: active Departments,
Position purpose/reporting/state, approved headcount, vacancies, minimized
current holders, governed assignments, and deliberately shared current
Availability. **Open structure**
reaches Department management; **Manage positions**, **Create Position**, and
per-Position **Manage** actions reach the purpose-built Position workspace when
a fresh exact-edition policy decision permits it. **Manage assignments** opens
the separate queue only when the same fresh projection confirms both assignment
and role authority. **Review availability** opens the minimized organizer page
only after the separate exact-edition Availability capability and field ceiling
pass. **Plan shifts** or **Review shifts** opens the governed organizer
projection only after its own Shift action hint passes. Every destination
authorizes again. Public opportunities, the assigned person's **My Workforce**
assignment, Availability, and **My shifts** views, and their onboarding
documents remain separate continuation paths. Non-staff organizers are never
sent to specialist Assignment, Availability, or Shift model records.

The Shift journey follows
[ADR 0078](../architecture/decisions/0078-governed-workforce-shift-journey.md)
and the
[Shift planning and My shifts](../product/page-contracts/shift-planning-and-my-shifts.md)
contract. No assignment is treated as Availability, and no Position or
Availability period is treated as a commitment. Exact Position assignment is
the first qualification baseline; broader qualifications, maximum hours,
lone-work, accommodations, check-in, timekeeping, notifications, and schedule
publication remain separate work.

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
does not grant a role, capacity, or access. Assignment proposal and independent
decision are the separately governed HR-013 workflow described below.

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

ADR 0076 and HR-013 mount one purpose-built **Assignment management** workspace
for a complete retained lifecycle:

```text
known person -> proposed -> independently approved -> active -> ended
                         \-> independently rejected
```

The queue and detail routes require `workforce.view_structure` and
`workforce.manage_assignments` at the exact edition. A proposal or decision
also requires `authorization.manage_roles`; ending requires
`authorization.revoke`. The route is resolved and authorized before any
name-bearing lookup, idempotency header, or body parsing. Platform oversight is
explicit and attributed, but a platform-only account cannot be the subject.

### Relationship-bounded proposal

A manager starts from one current Position and may select only an active person
already known through an organization relationship, non-cancelled edition
participation, a current Position application, an onboarding request, or
retained Workforce history. The complete set is capped at 512, contains no
arbitrary account lookup, and excludes anyone who already has a proposed or
active assignment for that Position. Each choice shows its relationship source
and the current status of only that Position's required onboarding documents.

The proposal records a normalized reason, aware effective start, optional later
ending, immutable version-1 receipt, audit, and registered proposed event. It
reserves one approved headcount place so concurrent intent cannot exceed the
Position, but creates no participation, capacity, RoleAssignment, capability,
or shift. Incomplete onboarding is therefore visible and allowed at proposal
time; it remains a hard approval blocker.

After required current route authorization, exact retry replay resolution
precedes the horizon check for a new proposal or reservation. Workforce then
asks Authorization to prove that one exact current proposer control source
covers the complete requested interval. Equal source and proposal boundaries
are accepted; a bounded source cannot cover an unbounded proposal. An uncovered
start or ending is returned as a field-local validation result without
proposal, reservation, audit, event, outbox, authority, or Participation
effects. An identical successful retry still returns its original immutable
receipt after a source-interval replacement while the caller retains the
required current route capabilities; loss of route authority remains a denial.

Browser times use the edition's IANA time zone and reject ambiguous or
nonexistent local minutes. Strict API timestamps require `Z` or an explicit
numeric UTC offset.

### Independent approval or rejection

Approval and rejection derive the decision maker from a separately
authenticated session. They never accept an approver identifier. The decision
maker must differ from the proposer, hold current assignment and role authority,
and complete fresh step-up authentication before input parsing.

Approval rechecks all of the following under the canonical edition,
Department, Position, and assignment locks:

- exact organization, series, edition, and current lifecycle;
- open Position and approved headcount;
- active person subject and unchanged proposal interval;
- every current Position onboarding requirement;
- immutable RoleBundle and typed-resource provenance; and
- one exact current source covering the proposal's full immutable interval for
  both the original proposer and current approver.

The transaction invokes the authorization module's dual-control role command,
activates only the Participation and capacity evidence required by the adopted
profile, changes the assignment to active, updates Position occupancy, and
persists decision, audit, event, outbox, and exact receipt evidence. A
Workforce-only edition creates no Participation or capacity row. Failure rolls
everything back. Rejection instead creates a final retained decision, frees
reserved headcount, and grants nothing.

ADR 0081 generalizes this boundary: every exact adoption profile that includes
Workforce but excludes attendee Participation must keep the assignment's
Participation-capacity pointer null and create no Participation evidence.
`programme_operations@1` is the first accepted successor, but it is not yet an
executable profile. Programme staffing demand must enter Workforce through an
explicit idempotent adapter tied to a Programme occurrence and Position; it
may create or reconcile owned draft demand but must never silently rewrite an
open, locked, cancelled, or completed `ShiftDemand`, or a claimed, confirmed,
removed, or completed `ShiftCommitment`. Scheduling consumes minimized
commitment envelopes and conflict facts rather than Workforce-private writers.

An interval recheck failure is a dedicated non-disclosing conflict. Browser
recovery stays beside the approval action; the strict API returns stable `409`
machine-readable recovery. Neither surface reveals which controller failed,
controller or source identities, source or grant identifiers, source
timestamps, or raw provenance. The proposal remains proposed and truthfully
reserves headcount, while access, RoleAssignment, Participation, assignment
version, receipt, audit, event, outbox, and other success effects remain
unchanged except for any separately classified failure evidence. Recovery is to
reload, reject the immutable proposal, and recreate it within current
authority, never edit, backfill, silently rebind, or replace its interval.

### Retained ending

Ending an active assignment requires current assignment and revocation
authority, fresh step-up, the exact assignment version, and a reason. One
transaction revokes the linked RoleAssignment through `maru.authorization`,
marks the assignment ended, and recalculates Position occupancy. Under
`full_convention@1`, it completes only Position-specific and configured
Participation capacities no other active assignment for that person needs.
Under `workforce_only@1`, it leaves the required null capacity pointer in place
and creates or touches no Participation evidence. Both paths write immutable
command, audit, event, and outbox evidence. An intended expiry does not silently
revoke authority; an overdue active record is shown as **Expired — ending
required** until this command succeeds.

The organizer detail presents newest-first reasons, versions, times, and actor
labels. **My Workforce** separately shows a person only their own Position,
Department, organization, edition, state, and dates. It omits reasons,
controller identities, authority provenance, candidates, and other people's
records. PositionAssignment specialist administration is inspection-only.

## Interfaces

Reference web routes:

```text
/admin/workspace/?view=workforce
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/positions/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/positions/new/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/positions/<position-id>/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/assignments/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/positions/<position-id>/assignments/new/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/assignments/<assignment-id>/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/availability/
/my/workforce/
/my/workforce/<organization-slug>/<series-slug>/<edition-slug>/availability/
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

Mounted Assignment management API surface:

```text
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/positions/<position_id>/assignments
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/assignments/<assignment_id>/approve
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/assignments/<assignment_id>/reject
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/assignments/<assignment_id>/end
```

Every Assignment mutation requires a canonical `Idempotency-Key`. Proposal
returns `201` on first success and `200` on replay; decisions return `200`.
Proposal contains one known `account_id`, aware effective interval, and reason.
Decision input contains only `expected_version` and reason. Approval, rejection,
and ending require fresh step-up before input parsing. Responses expose only
assignment identifier, version, status, and replay state. The same strict
`400`/`403`/`404`/`409`/`503` disclosure boundary as Position management
applies, with readiness, headcount, stale assignment version, and lifecycle
represented as conflicts. A controlling-authority interval failure during
approval is the dedicated non-disclosing `409`; proposal-time interval failure
remains field-local `400` validation.

Mounted Availability management API surface:

```text
GET  /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/availability/me
PUT  /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/availability/me
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/availability/me/withdraw
GET  /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/availability
```

The owner GET includes the owner's private draft and current editability. PUT
replaces the complete current period set as either private draft or submitted
and requires a canonical `Idempotency-Key`, an optimistic expected version,
and aware timestamps with an explicit offset. POST withdraws the plan and
deletes every exact current period under the same retry and version contract.
The organizer GET requires the independent complete
`workforce.view_availability` field ceiling, audits the read before disclosure,
and projects only open-assignment people, operational Position context, the
current shared consequence, and submitted periods. Draft and absent remain
indistinguishable. Inputs are closed, query parameters are unsupported, and
the strict `400`/name-free `403`/`409`/`503` boundary applies.

Mounted Shift planning and My shifts API surface:

```text
GET|POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/shifts
GET|PUT  /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/shifts/<demand_id>
POST     /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/shifts/<demand_id>/<open|lock|reopen|complete|cancel>
POST     /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/shift-commitments/<commitment_id>/<confirm|remove>
GET      /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/shifts/me
POST     /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/shifts/<demand_id>/claim
POST     /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/shift-commitments/<commitment_id>/withdraw
```

The organizer list is a bounded complete, audited snapshot with current
coverage counts, people labels, suitability consequences, and current decision
rationale. Demand writes and organizer actions require reasoned versioned
input. Claim accepts only the current demand version. Person withdrawal
requires the current commitment version and affirmative confirmation and never
collects an explanation. Every mutation requires a canonical
`Idempotency-Key`; inputs use exact JSON primitive types and offset-bearing
demand timestamps. The full `400`/name-free `403`/authorized-target `404`/`409`/
generic `503` boundary is documented in the purpose-specific page contract.

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
/admin/workforce/shiftdemand/
/admin/workforce/shiftdemandcommandreceipt/
/admin/workforce/shiftcommitment/
/admin/workforce/shiftcommitmentcommandreceipt/
```

These specialist routes are not the accepted product mutation contract. The
shared commands and migration fences are active, so Department, Position,
Volunteer opportunity, and PositionAssignment records are inspection-only
here. Managers use the strict Organization structure, Position management, and
Assignment management, Shift planning, and My shifts HTML/API adapters.

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
downgrade behavior. Production readiness fingerprints all Organization
structure, Assignment, Availability, and Shift guard, evidence, and truncate
functions and their exact attachments, requires the current Workforce migration
recorder chain through `0014`, including the profile-matched nullable
assignment-capacity guard and downgrade fence, and verifies the
exact 13-reference Department FK inventory;
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

Workforce `0011_owner_assignment_commands` adds assignment versions, explicit
rejection, decision and ending evidence, and immutable
`PositionAssignmentCommandReceipt` rows. The stopped-writer guard allows only
`proposed -> active`, `proposed -> rejected`, and `active -> ended`, with an
exact next-version receipt and state-specific actor, reason, role, capacity, and
time evidence. It rejects direct deletion; immutable Position, scope, person,
proposer, interval, and linked-authority mutation; skipped or reversed states;
and receipt update, deletion, or truncation. Existing internally consistent
legacy assignments remain readable without invented command versions or
reasons. Runtime readiness fingerprints the assignment row guard, receipt
guard, deferred evidence assertion, and exact trigger attachments, and confirms
that the runtime role cannot invoke or bypass them. After governed assignment
writes, recovery fixes forward or restores the complete database to a mutually
consistent pre-write point; `0011` is not independently reversible in live use.

Workforce `0012_person_owned_availability` adds one optimistic current plan per
person and edition, non-overlapping half-open current periods, and immutable
minimized `PersonAvailabilityCommandReceipt` rows. Draft and submitted writes
require a proposed or active exact-edition assignment; withdrawal remains
possible for an existing owner after that relationship ends and deletes every
current exact period. PostgreSQL rejects platform-account ownership, scope or
time-zone mismatch, stale period versions, interval overlap or horizon escape,
isolated period mutation, plan deletion, malformed receipts, missing final
evidence, and destructive truncate outside the narrow test reset. Trigger
functions are not runtime-executable and their definitions and attachments are
fingerprinted. The migration ensures `btree_gist` without claiming ownership
of an extension already used by Venue constraints, and its downgrade fence
refuses removal after durable Availability data exists.

Workforce `0013_shift_journey` adds versioned Shift demand and person-owned
commitment aggregates plus immutable exact-version receipts. PostgreSQL checks
exact organization/edition/Position/assignment/Availability scope, person
subject kind, immutable published work, legal state transitions, complete
actor/time/reason evidence, one active claim per person and demand, and one
non-overlapping person work/rest envelope. Deferred checks require exact
command evidence; deletion and truncate remain protected. A complementary
Position trigger blocks closure while draft, open, or locked demand exists,
and the demand guard takes a Position lock so raw concurrent creation cannot
race closure. Runtime readiness fingerprints every function and attachment;
the downgrade fence refuses removal once durable demand, commitment, or receipt
evidence exists.

## Workforce verification

The 2026-08-25 Shift focus covers draft creation and immutability, open/lock/
reopen/complete/cancel transitions, personal suitability and minimization,
claim/withdraw, independent confirmation/removal, stale Availability review,
transactional capacity, overlap and post-Shift rest, explicit underfill,
ended-work boundaries, directly inspectable organizer rationale, strict API
primitive and timestamp input, idempotent receipts, audited bounded snapshots,
tenant and person isolation, fixed privacy-minimized withdrawal evidence,
Position closure protection, raw database tampering, runtime ACL/readiness, and
query-count ceilings. A 77-test focused Workforce/navigation/style regression
passes on freshly migrated PostgreSQL test databases. The expanded runtime-
role, exact function-fingerprint, trigger-attachment, authority-provenance,
Organization structure, and retired-Department readiness gate passes all 453
cases. OpenAPI/generated client, Staff Console, whole-tree quality, migration
recovery, and authenticated rendered evidence are recorded in the current
checkpoint rather than inferred here.

The 2026-08-25 Availability focus covers private draft isolation, deliberate
sharing, explicit zero-period unavailability, withdrawal after assignment
closure, current-period deletion, retry replay/conflict, optimistic versions,
DST gaps and folds, offset-required API input, overlap and horizon rejection,
owner and organizer minimization, tenant and edition isolation, authorization
before parsing, audited organizer reads, no-cache HTML/API responses, and raw
database evidence, replacement, subject-kind, receipt, and truncate guards.
All five end-to-end command/browser-adapter/API/database cases pass, strict
interval/formset unit cases pass, the complete 271-case runtime database-role
suite passes after adding the exact period write profile, and a fresh database
applies the corrected migration contract. The OpenAPI/TypeScript contract,
Staff Console component suite, strict mypy, and repository-wide Ruff checks
also pass. The visual and complete UX-029 evidence is recorded separately and
does not remove the deployment retention gate.

The 2026-08-24 Assignment management focus, then exercised under the
full-convention compatibility profile, covers relationship-bounded
candidates, incomplete-readiness proposal, headcount reservation, a genuinely
different decision actor, approval-time authority and onboarding rechecks,
strict lifecycle and assignment versions, retry replay/conflict, atomic
role/participation activation, rejection, linked-role revocation, shared-
capacity retention, Position occupancy, retained reasons, subject-view
minimization, authorization and step-up before parsing, cross-edition isolation,
private HTML, strict API objects and methods, raw database-write rejection,
immutable receipts, exact trigger readiness, and runtime-role containment. All
five end-to-end command/browser-adapter/API/database cases pass in 71.28
seconds, including a separate authenticated proposer and approver; the direct
lifecycle case passes again in 54.01 seconds. The focused executable
database-role and hardening gate passes 264 tests. A fresh two-human visual
browser rehearsal and the complete UX-029 state matrix remain acceptance work,
not outcomes inferred from those automated cases.

The later cross-profile regression retains that full-convention
Participation-capacity activation and completion, proves its pointer cannot be
cleared from governed ended evidence, and separately proves Workforce-only
approval and ending activate then revoke only the RoleAssignment while keeping
the capacity pointer null and Participation absent.

The 2026-08-23 owner rehearsal adds focused evidence for the read journey: the
non-staff convention chair reached Workforce from Registration, retained the
exact MaruCon 2026 host context, saw the complete five-stage orientation and
current Position/vacancy projection, received no staff-only specialist links,
and followed **Open structure** to canonical Department management. The 390 CSS-pixel view
had one H1, one `main`, no duplicate identifiers, and no horizontal overflow.
Frontend tests cover the populated journey, non-staff link boundary,
non-disclosing `403`, and automated axe analysis. Position command, API, and
HTML tests separately cover the manager mutation role. The owner-safe
Assignment, Availability, and Shift continuations are now implemented as
distinct workflows.

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

General qualifications, maximum-hours/lone-work/accommodation policy,
check-in, time records, schedule publication, assignment replacement and bulk
UX, approval notifications, onboarding-review orchestration, Availability
post-edition disposal automation, and document download through the REST API
remain work. Organization structure, Position management, Assignment
management, Availability management, and Shift planning use bounded reads, shared strict
commands, stopped-writer migrations, and the runtime trigger catalog. The
focused owner journeys and automated tests do not replace the complete
width/zoom, screen-reader, failure, two-human mutation-role, ordinary
production-authority reconciliation, real cutover, or representative
restore/PITR evidence. An assignment is responsibility and authority evidence;
Availability is person-owned planning input; neither implies a scheduled
Shift.

The Programme Operations contract also leaves check-in, lateness/absence,
Shift actual-time recording, dispute handling, and Shift handover exclusively with
issue #24. A published Programme/personal timetable may show an assigned Shift
commitment, but publication is not check-in or proof of work.
