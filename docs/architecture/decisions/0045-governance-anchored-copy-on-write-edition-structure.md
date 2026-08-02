# ADR 0045: Governance-anchored copy-on-write edition structure

- Status: Accepted
- Date: 2026-08-02
- Clarifies: ADRs 0007, 0028, 0036, 0039, 0040, 0041, 0042, and 0044
- Requirements: IDN-002, IDN-004, IDN-009, IDN-011, IDN-012, EVT-002,
  EVT-003, HR-007, HR-010, HR-011, UX-019, UX-020, UX-025, AUD-001,
  AUD-005, INT-001, NFR-001 through NFR-004, NFR-008, and NFR-009

## Context

Maru already stores edition-owned Departments, Positions, reporting
relationships, and time-bounded PositionAssignments. It also has a minimized,
read-only structure projection. That projection is useful, but it does not yet
provide the record-oriented Page 9 workflow needed to establish and maintain
an edition's structure without writing through specialist Django model forms.

The Awoostria public organization taxonomy is a useful first reference for a
furry convention. It includes an Executive Board, a Helper Board, operational
departments, nested subdepartments, multiple role holders, and people who may
hold several roles. It is not evidence of private reporting lines or permission
to import identifiable volunteers. ADR 0042 therefore permits department and
workflow shapes but forbids copying the public roster into fixtures, accounts,
or assignments.

There is also an important aggregate boundary. ADR 0040 defines the Executive
Board as the organization's accountable `OrganizationRepresentation`, with
accepted appointments and organization-scoped root authority. ADR 0041 defines
Departments and Positions as edition-owned operational structure whose parent
edges do not confer access. Persisting another Department or Position called
Executive Board would duplicate governance, make the two records drift, and
blur legal representation, operational responsibility, and software
authorization.

The first editable structure milestone must therefore preserve the stronger
domain model while presenting the hierarchy in the way organizers expect. It
must also be safe to repeat through HTML and API clients, leave a durable source
record when a built-in template is copied, prevent concurrent edits from
silently overwriting one another, and retain history once a department has
been used.

## Decision

### Governance anchor and operational tree are separate

Page 9 composes two module-owned projections:

```text
Executive Board (OrganizationRepresentation governance anchor)
  -> Helper Board (top-level edition Department)
       -> operational edition Departments
            -> optional nested Departments
```

The Executive Board row is a presentation anchor sourced through a documented,
minimized `maru.organizations` query. It truthfully reports absent,
Provisioning, Active, or Suspended governance without exposing appointments or
private controller identity. It is never inserted into `Department`,
`Position`, `PositionAssignment`, or a generic group, and it never receives a
workforce parent identifier.

Helper Board is an ordinary top-level Department with no persisted parent. The
Page 9 projector places it visually beneath the governance anchor. Its children
and every deeper edge remain exact same-edition Department relationships. A
missing or malformed representation cannot be repaired by workforce code, and
applying a structure template never provisions or activates governance.

Neither visual edge is an authorization inheritance edge. Executive Board
organization authority continues to cover a narrower target only through ADR
0041's explicit policy containment. A Department does not inherit access from
its parent, and a parent does not inherit access from a child.

### One canonical edition page

Page 9 is **Organization structure** at:

```text
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/
```

It appears once beneath the selected edition in the shared administration
navigation. The organization, series, and edition chain is resolved from
persisted records before any name or structure is disclosed. Selected-edition
session state is display context only and cannot replace route scope.

An active platform administrator has explicit oversight but remains an actor
only. An organizer requires `workforce.view_structure` effective at the exact
edition target to see the complete Page 9 tree. Management controls additionally
require `workforce.manage_structure` at that edition. A department-only grant
does not reveal or manage the complete edition tree. Executive Board status or
visual placement alone is not a workforce permission; Board controllers use
their independently governed authorization capabilities to create an exact
edition role or grant when an organizer should manage structure.

The header computes view and management paths from current persisted authority.
It may show safe role-group labels and people only when the viewer can already
see those relationships. It never maintains a page-local ACL or reveals hidden
principal counts. Navigation and every HTML/API action repeat the same exact
policy decision as the destination.

### Versioned built-in Awoostria reference

Maru ships an immutable, code-reviewed built-in template identified as
`awoostria-reference@1`. A later change is a new version with a new content
digest; an already available version is never edited in place.

Version 1 contains exactly 22 Department definitions: top-level **Helper
Board**, followed by **Art**, **Charity**, **Ceremonies**, **Dealers' Den**,
**Decorations**, **Events & Programming**, **Front Desk**, **Fursuit Support**,
**Graphics Design**, **Human Resources**, **IT**, **Legal & Compliance**,
**Logistics**, **Maid Café**, **Multimedia**, **PEER**, **Registration**,
**Security**, **Social Media**, **Stage Tech**, and **Story** beneath Helper
Board. Stable code-owned codes, descriptions, and display order belong to the
template version. The arrangement is an editable starting point, not a claim
about Awoostria's private legal or authority structure.

Application is copy-on-write. It creates independent edition Departments and
an immutable application receipt containing exact organization and edition,
template code, version and digest, actor, retry key, resulting structure
version, timestamp, and correlation identifier. Editing the edition copy does
not alter the built-in definition, another edition, or the receipt.

The template may be applied only while the organization is Draft or Active,
the edition is Draft or Preparing, and its workforce structure is empty. Empty
means there is no Department, Position, PositionAssignment, typed workforce
resource binding, or prior structure-template receipt in that exact edition.
An absent zero-version structure-control row does not make a non-empty legacy
tree eligible. Other edition-owned configuration, such as registration or
venue planning, neither authorizes nor blocks this workforce-only command.

One successful application creates only the 22 Departments plus the structure
control, receipt, audit, event, and outbox evidence. It creates no account,
membership, representation, appointment, capability grant, role bundle,
Position, volunteer opportunity, application, onboarding request,
PositionAssignment, Participation, registration, or public-roster fact.

### Edition structure aggregate and application services

`maru.workforce` owns one edition structure control aggregate with exact
organization and edition identity and a positive monotonic
`aggregate_version`. A truly absent structure is represented to command
callers as version zero. Existing populated editions receive an explicit
legacy-existing control during migration; they are never labelled as having
used the Awoostria template.

The first Page 9 slice exposes application services equivalent to:

- `project_edition_structure`;
- `apply_builtin_structure_template`;
- `create_department`;
- `update_department` and `reparent_department`; and
- `retire_department` or `delete_unused_department`.

HTML and API adapters call these same services. Every command begins with
trusted route scope, re-resolves and locks the exact organization, series,
edition, structure aggregate, and affected Department rows in stable order,
repeats authorization and lifecycle checks, and validates the complete model.
Client-supplied organization, edition, actor, code, lifecycle, template source,
version result, timestamp, audit, or event fields are rejected.

Every changed command compares an expected aggregate version under lock and
advances it exactly once. A stale command fails without mutation. A normalized
no-op advances nothing and emits no success evidence. Create and template
application use a UUID retry key; a same-actor, same-scope, same-key,
same-normalized-payload retry returns the original outcome, while reuse with
different input conflicts. HTML preserves a server-created hidden key and API
clients use `Idempotency-Key`, which is rejected as a JSON field.

Successful changes atomically append value-minimized administrative audit,
publish a registered `workforce.structure.changed.v1` fact, and enqueue its
outbox delivery. Evidence records action, exact scope, resulting structure
version, template code/version when applicable, changed field names, and stable
technical correlation only. It does not copy entered names, descriptions,
reason text, people, capabilities, or private governance data. Audit, event, or
outbox failure rolls the whole command back.

### Closed inputs and bounded projection

The first slice accepts only these organizer-entered values:

- department name: required Unicode text, 1 through 160 characters after
  outer-whitespace trimming and ordinary whitespace normalization;
- description: optional Unicode text, at most 1,000 characters;
- parent: absent or the stable identifier of one current, non-retired
  Department already resolved in the same organization and edition;
- display order: an integer from 0 through 65,535;
- expected structure version: an integer of zero or greater;
- reason: required normalized Unicode text, 1 through 240 characters; and
- exact current name confirmation for hard deletion, or exact edition-name
  confirmation for applying all 22 reference Departments.

Template code and version are selected from the code-owned allowlist. Unknown
fields, malformed identifiers, control characters, impossible parent chains,
self-parenting, cycles, cross-tenant parents, and out-of-range values fail
before mutation. Department codes are stable, lower-case, bounded, generated by
the service with deterministic collision handling, and are not editable input.

The read query has code-owned ceilings for Departments, Positions, and holders,
stable ordering, and an explicit overflow state rather than silent truncation.
It exposes only the HR-010 operational projection. Technical identifiers used
by links or API commands are not rendered as human content. Email, private HR
evidence, account state, appointment detail, raw authority provenance, and
unrelated tenant data remain excluded.

### Retirement, deletion, and lifecycle

Template application and the first structural editor are limited to Draft and
Preparing editions. Ready, Live, and Closing structure changes require a later
explicit change-control contract; Archived and Cancelled editions are always
read-only. A Suspended or Closed organization is read-only from this workflow.

Department retirement is a one-way, reasoned command in this slice. It retains
the stable record and history and prevents new children, Positions, or access
targets beneath it. A Department cannot retire while it has a current child,
open Position, an active assignment whose term has not ended, or unclosed
authority that is effective now or scheduled for later; those dependencies
must be moved or ended through their owning commands first. Historical closed
relationships, including immutable Position bindings, remain attached and
visible only to authorized historical projections.

Hard deletion is exceptional. It requires expected version, exact current-name
confirmation, reason, and proof under lock that the Department has no child,
Position, assignment, resource binding, authority, cross-module reference, or
operational history beyond its own creation. It never cascades. When that proof
is unavailable the service returns a protected conflict and offers retirement
when retirement is valid. Reparenting preserves organization, edition, stable
code, audit history, and exact authorization target identity; it cannot silently
move or widen any CapabilityGrant or RoleAssignment.

### Position editing is a later Page 9 substep

Page 9 continues to read existing Positions, reporting relationships, and
current permitted holders, but its first management slice edits Departments
only. Creating or changing a Position also selects an immutable PositionTemplate
and RoleBundle, creates a typed resource binding and volunteer opportunity, and
can affect future assignment authority. ADR 0044 forbids the platform operator
from manufacturing ordinary organizer authority provenance.

Position editing therefore follows as Page 9b only after its strict role-bundle
selection, dual-control provenance, reporting-cycle, opportunity, lifecycle,
and recovery contract is accepted. The Awoostria reference template does not
pre-create Lead, Deputy, or Volunteer Positions. Multiple holders and one
person's multiple departmental roles remain supported by the existing Position
and PositionAssignment model when those records are deliberately created.

### Migration and recovery

The implementation uses additive schema and a populated-data preflight. It
must preserve existing Department identifiers and trees, create at most one
structure-control row per populated edition, classify those rows as legacy
existing without template provenance, and report malformed scope, cycles, or
unsupported references for explicit reconciliation. It never infers a Board,
Helper Board, template version, person, assignment, or authority from a name.

Database enforcement retains exact organization/edition parent agreement and
cycle prevention, protects immutable scope/code/template receipts, and guards
monotonic aggregate versions. Once a structure-control or receipt write exists,
old direct Department writers are incompatible. Recovery fixes forward or
restores the workforce, authorization bindings, audit, events, and outbox to one
consistent point; it does not reverse only the new control tables or fabricate
receipts for existing data.

## Consequences

- Organizers see the familiar Executive Board -> Helper Board -> departments
  story without duplicating governance in the workforce model.
- A new edition can receive a useful 22-department starting structure in one
  accountable action and then diverge independently.
- Applying a template never enrolls people or grants access, so structure and
  authority remain explainable.
- All structure edits become versioned, audited application operations rather
  than informal specialist-model saves.
- Page 9a intentionally does not complete workforce Position creation,
  assignment lifecycle, or the general access-management experience.
- One edition-wide aggregate serializes structural edits. This favors clear
  conflict behavior over concurrent writes to separate branches; a future ADR
  may introduce compatible finer-grained versions if measured use requires it.

## Alternatives considered

### Create an Executive Board Department

Rejected. It duplicates `OrganizationRepresentation`, can drift from controller
terms and root authority, and would make a reporting edge look like an access
rule.

### Mirror representation appointments into workforce positions

Rejected. Governance consent and organization authority are not edition
participation or staffing. The mirror would synthesize assignments and violate
the non-participating and explicit-provenance boundaries.

### Share one mutable template tree among editions

Rejected. A template edit could rewrite current and historical edition meaning.
Immutable source versions plus an edition-owned copy preserve provenance
without live coupling.

### Apply the template to a partially populated tree

Rejected for the first slice. Automatic merging needs conflict, rename,
reparent, omission, and rollback semantics. Empty-only application is
predictable; an explicit preview-first import/merge may be designed later.

### Include Lead, Deputy, and Volunteer Positions in version 1

Rejected for Page 9a. Position creation necessarily selects access-bearing role
definitions and typed resource bindings. Department-only creation delivers the
requested structure without silently manufacturing organizer authority.

### Keep using specialist Department records for writes

Rejected. Generic model forms cannot provide the shared HTML/API command,
optimistic concurrency, idempotency, lifecycle, audit/outbox, or protected
retirement guarantees required for a production workflow.
