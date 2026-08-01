# ADR 0041: Exact department and typed-resource authorization scope

- Status: Accepted
- Date: 2026-08-01
- Clarifies: ADRs 0003, 0037, 0038, and 0040
- Requirements: IDN-002, IDN-004, IDN-005, HR-004, HR-006, HR-010,
  UX-020, AUD-001, AUD-005, NFR-001 through NFR-004, and NFR-008

## Context

Maru's current authorization records persist organization or edition scope.
That is sufficient for the organization, series, edition, and initial Executive
Board journeys, but it cannot safely distinguish one department from another
or limit authority to one exact operational record. Department-owned mutation
pages remain blocked under ADR 0038 for this reason.

The current policy input is also a freely constructed collection of UUIDs and
optional owner and state values. Request adapters generally resolve records
carefully, but the policy boundary itself cannot distinguish a target derived
from persisted records from a caller-asserted combination. Adding more nullable
UUIDs to that input would enlarge this trust problem.

Maru needs one authority lattice that can express:

```text
organization -> edition -> department -> exact resource
```

without creating page access-control lists, treating department hierarchy as
implicit authority, trusting selected-edition state, or coupling the policy to
every future domain model. It must preserve the meaning of existing grants and
role assignments and keep immediate revocation and delegation containment.

## Decision

### One persistent scope lattice

`CapabilityGrant` and `RoleAssignment` gain nullable exact department and typed
resource-binding references in addition to their existing organization and
edition references. Scope level is derived from the populated references; it
is not a separately editable field.

The only valid persistent shapes are:

| Scope | Organization | Edition | Department | Resource binding |
| --- | --- | --- | --- | --- |
| Organization | required | empty | empty | empty |
| Edition | required | required | empty | empty |
| Department | required | required | required | empty |
| Exact resource | required | required | required | required |

Every populated child must belong to the exact parent chain. A malformed or
partially populated tuple is invalid in the model, command, policy, and
database.

The capability catalog adds `Department` as a scope level and distinguishes a
capability's broadest persistable scope from whether it may be persisted at
all. Existing self/owner capabilities remain relationship-derived and cannot
be converted into grants merely because `Resource` is now a stored scope
level. An edition-capable operation may be assigned more narrowly to a
department or exact resource when the owning module can resolve that target.

The capability code remains the function dimension of a decision. Requested
fields continue to intersect the code-owned field ceiling. A scope record does
not contain a page, URL, menu item, template name, or editable list of page
actions.

### Exact department semantics

A department-scoped authority covers only that exact department and resources
bound to it. It does not automatically cover the department's parent,
siblings, children, or other descendants.

The workforce reporting tree is an organizational projection, not an
authorization inheritance tree. Executive Board organization authority
already covers narrower same-tenant targets. Any later requirement for a lead
to administer several departments must use explicit assignments, an edition
scope, or a separately accepted inheritance design with its own revocation and
explanation rules.

### Typed resource bindings

`maru.authorization` owns an immutable `ScopedResourceBinding` containing:

```text
stable binding UUID
code-owned resource kind
owning-domain object UUID
exact organization
exact edition
exact department
creation timestamp
```

The pair of resource kind and owning-domain object identifier is unique. The
first supported exact resource is a workforce position. A future module adds
a resource kind only with an owning-module resolver, database validation,
tenant-isolation tests, and migration/recovery evidence.

An untyped UUID, Django `ContentType`, or generic foreign key is not a valid
resource scope. Bindings are technical authorization anchors rather than page
ACLs or a second copy of the domain record. The owning module remains the
source of truth for the resource and must prevent its scope from being moved
after a binding exists.

Shared future records may expose department-owned operational layers as their
own typed resources. Maru does not make one department inherit another
department's access merely because both contribute to a shared item.

### Trusted target contract

Policy and authority commands receive a server-resolved authorization target,
not an arbitrary tuple of request UUIDs. Owning modules construct that target
from persisted records through explicit resolvers for organization, edition,
department, typed resource, and owner/self relationships.

For a department-owned resource, resolution proves the complete chain before
the final decision:

```text
edition belongs to organization
department belongs to organization and edition
resource belongs to organization, edition, and department
typed binding names that exact resource and scope
```

Route identifiers may narrow queries but never establish ownership or grant
authority. Request bodies, hidden form fields, selected-edition sessions, and
client-provided owner or lifecycle values are not policy facts. Self authority
uses the owner derived from the locked domain record.

An existence-blind candidate-authority check may precede target lookup to
avoid cross-tenant disclosure. It is only a non-disclosure gate; the command
must still resolve the exact target and repeat the complete policy decision
inside its transaction.

### Policy containment

For an exact target, an active authority source matches only when its stored
scope is an ancestor of or equal to that target:

- organization scope covers same-tenant editions, departments, and resources;
- edition scope covers departments and resources in that exact edition;
- department scope covers that exact department and its bound resources; and
- resource scope covers that exact typed binding only.

The decision order remains deny by default: active account, known capability,
trusted target, explicit self relationship, explicit platform policy where
allowed, valid direct-grant chains, and active immutable-role assignments.
Field ceilings and obligations are returned with stable reason codes.
Authoritative lifecycle restrictions remain in the owning domain service and
are combined with the policy result for presentation; caller-provided state is
not trusted.

The platform administrator retains explicit oversight policy but gains no
membership, representation term, department position, participation, or
self/owner relationship. Django staff status, Django Groups, navigation, and
working-edition context remain outside convention authority.

### Delegation containment

A delegated capability retains the same capability and organization as its
parent. Its scope may remain equal or move only downward through the lattice.
It cannot move to another edition, department, or resource, begin before its
parent, outlive its parent, or broaden a field ceiling. The parent principal
must be the child grantor.

In particular:

- organization authority may delegate within the same organization;
- edition authority may delegate only within that edition;
- department authority may delegate to the same department or one exact
  resource bound to it; and
- resource authority may delegate only the same exact resource.

Policy validates the complete chain at evaluation time, so expiry or
revocation of any ancestor invalidates every descendant immediately.
PostgreSQL rejects scope mismatch and recursive delegation cycles even when
ORM validation is bypassed.

### Commands, adapters, and access explanation

Root grant, role assignment, delegation, replacement, and revocation commands
accept a resolved target. They lock and revalidate the target, authority
record, and relevant delegation chain before writing. Audit and domain-event
scope comes from the resolved target, never from request data.

Organization and edition access adapters remain compatible. Department and
resource access adapters use fully nested trusted routes. Their closed payloads
contain the exact existing person, immutable role version, independent
approver, effective term, and reason; scope remains server-owned. Unknown,
foreign, and unauthorized targets use bounded non-disclosing failures.

The UX-020 effective-access query consumes:

```text
viewer
resolved target
operation intents and capability codes
requested projection fields
owning-module lifecycle result
evaluation time
relationship-disclosure policy
```

It returns the current viewer's available actions, obligations, lifecycle
limits, and bounded source categories such as platform oversight, direct
grant, immutable role, self relationship, or workforce relationship. The
ordinary header shows human scope and role labels rather than technical IDs or
emails. Named people are disclosed only inside an independently authorized
relationship or access view, and sensitive reads remain audited. An enabled
**Manage access** action changes the underlying audited assignment at the
resolved scope; it does not edit a page ACL.

## Migration and recovery

Scope v2 is delivered as one milestone through ordered additive migrations:

1. add the typed-binding table, nullable department/resource references,
   catalog scope rule, checks, and indexes;
2. harden workforce Department and Position scope integrity; and
3. preflight and backfill typed bindings, replace authorization triggers,
   validate constraints, and install a downgrade fence.

Preflight reports or rejects cross-tenant scope mismatches, department cycles,
position scope mismatches, unknown role capabilities, malformed or cyclic
delegation ancestry, and other invalid existing authority. It separately
reports edition-wide role assignments linked to workforce positions.

Existing grants and assignments are not silently narrowed or broadened. The
migration may create reproducible resource bindings for existing positions,
but it does not infer that a historical edition-wide role was intended to be
department-wide. Such authority requires an explicit, audited reconciliation.

PostgreSQL guards enforce valid scope shape and parent agreement, immutable
scope identity, typed-binding agreement, Department cycle prevention,
Position scope stability after binding, delegation containment, and immutable
resource bindings. Fresh and populated forward migration, database-bypass
tests, and rollback/fix-forward rehearsal are required.

This is a maintenance-window writer change. Old application nodes can create
only organization/edition authority and are incompatible once department or
resource writes are enabled. After the first scoped authority write, downgrade
must refuse; retain compatible code and fix forward, or restore the whole
database to a mutually consistent pre-write point.

## Compatibility

- Existing organization grants and assignments retain organization-wide
  meaning.
- Existing edition grants and assignments retain edition-wide meaning.
- Initial Executive Board assignments remain organization-scoped.
- Existing workforce-linked assignments remain edition-scoped until an
  explicit reconciliation or an immutable template policy selects a narrower
  target.
- Existing role-bundle versions remain immutable and unchanged.
- Current organization/edition APIs and decisions retain their behavior.
- Department/resource authority may make an edition available as navigation
  context without granting access to its parent record.
- Specialist Django records remain separately protected by staff and model
  permission.
- The retired browser bootstrap and management API remain retired; the
  operator recovery command keeps its explicit legacy scope.

## Unresolved actor and approver provenance

This decision extends delegated-grant ancestry and controller-horizon checks
to exact department and resource targets. It does not solve a separate existing
IDN-005 risk: ordinary root grants and role assignments record actor and
approver identities and issuance-time expiry ceilings, but do not retain the
exact authority records through which those controllers acted. Later
revocation of a controller's unrelated source therefore cannot always be
proven to invalidate the issued root authority dynamically.

Scope v2 must not be described as completing that provenance invariant. A
later accepted decision must define durable actor/approver authority-source
links, cycle handling, legacy reconciliation, and how the special initial
Executive Board activation relates to controller-term loss and quorum
recovery. This separation keeps the current milestone implementable without
hiding a production security gate.

## Consequences

- Department-owned tools can deny sibling, parent, child, foreign-edition, and
  foreign-tenant access before mounting mutations.
- One role bundle can retain stable capability meaning while each assignment
  receives an exact organization, edition, department, or resource scope.
- Resource kinds require deliberate module integration and database evidence
  rather than generic polymorphic shortcuts.
- Every list, search, count, export, file, realtime subscription, and bulk
  command must scope candidates before evaluation.
- Revocation remains immediate; authorization caching is request-local until a
  proven invalidation design exists.
- Sensitive access reads and every privileged mutation or denial retain
  minimized security audit evidence.
- Department hierarchy no longer risks becoming an undocumented authority
  inheritance mechanism.
- Existing broad authority remains visible migration debt instead of being
  silently reinterpreted.

## Alternatives considered

### Add department and resource UUIDs only to the policy input

Rejected. It would not persist assignment scope, enforce tenant agreement, or
distinguish resolved records from caller claims.

### Use page ACLs or route names

Rejected. Page visibility cannot safely represent view, edit, comment,
approve, field, lifecycle, expiry, delegation, and resource differences. It
would create a second authority system.

### Use Django Groups, staff status, or selected-edition context

Rejected. None carries tenant, department, resource, field, term, approval, or
revocation semantics, and platform administration must remain
non-participating.

### Use GenericForeignKey or an untyped resource UUID

Rejected. Neither provides database-enforced ownership, exact tenant scope, or
safe resolver registration.

### Let department parents inherit all child authority

Rejected. The existing workforce hierarchy is editable operational structure,
not a reviewed authorization closure. Implicit inheritance would make moves
and reparenting silently change access.

### Automatically narrow existing workforce assignments

Rejected. Existing role bundles contain edition-global functions and the
historical intent cannot be inferred safely. Reconciliation must be explicit
and audited.

### Refactor all authority into a new generic base record

Rejected for this milestone. It would widen migration and recovery risk beyond
the department/resource prerequisite. Additive scope references preserve the
tested grant and immutable-role model.
