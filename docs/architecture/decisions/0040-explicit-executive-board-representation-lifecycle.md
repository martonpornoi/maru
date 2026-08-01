# ADR 0040: Explicit Executive Board representation lifecycle

- Status: Accepted
- Date: 2026-08-01
- Supersedes: ADR 0024 for normal establishment of first organization authority;
  its edition-lifecycle controls remain, and its operator command is recovery
  evidence only until a separate legacy-reconciliation procedure is approved
- Clarifies: ADRs 0003, 0031, 0038, and 0039
- Requirements: IDN-002, IDN-004, IDN-005, IDN-007, IDN-009, IDN-011,
  IDN-012, UX-012, UX-013, UX-017, UX-020, UX-024, AUD-001, AUD-005,
  NFR-001 through NFR-004, NFR-008, and NFR-009

## Context

An organization needs accountable human representation before it can exercise
convention authority. A Boolean flag, Django Group, oldest-account convention,
or platform-superuser shortcut cannot represent who accepted that
responsibility, which authority version they hold, who approved it, when it
became effective, or how it is later revoked.

The preserved first-authority ceremony in ADR 0024 creates a broad collection
of organization, edition, workforce, and participation relationships in one
step. That was useful recovery evidence, but it conflicts with ADR 0031's
non-participating platform boundary and the current page-by-page journey. It
also makes it hard to explain the difference between an organizer's legal
representation, a department appointment, edition participation, and access to
software.

M2 therefore needs a smaller first vertical slice: establish the organization's
Executive Board, let each exact person knowingly accept, and activate the
organization with independently controlled root authority. Department
hierarchy and narrower authority then build on that root rather than being
silently manufactured during tenant creation.

## Decision

### A purpose-built representation aggregate

Every organization has at most one code-owned `executive_board`
`OrganizationRepresentation`. It is the accountable representation root, not a
generic access group, department, workforce position, participant capacity, or
public imprint label. Its initial state is `Provisioning`; activation moves it
to `Active`. `Suspended` is reserved for a later reasoned command and must not
be produced by ordinary record editing.

Each human term is a `RepresentationAppointment` with the fixed `Controller`
role and this initial lifecycle:

```text
Invited -> Accepted -> Active -> Ended
        \-> Declined
```

Only `Invited -> Accepted|Declined` and the activation-time
`Accepted -> Active` transition belong to the first M2 slice. Expiry,
withdrawal, replacement, suspension, ending an active term, quorum after
removal, and reactivation require explicit later commands before the broader
lifecycle can be called complete. State, response, activation, end timestamps,
linked authority, and positive versions must agree under database constraints.

### Initial provisioning and invitation

Only an active platform administrator may provision the initial representation
for a Draft organization. Provisioning requires a permanent, normalized reason,
locks the exact organization, creates one representation root, and produces no
membership, appointment, role assignment, edition participation, registration,
or workforce record for the platform administrator.

Controller invitations use the exact normalized email of an existing active
person account whose email is verified. Maru does not create, guess, fuzzy
match, or reveal an account through this form. A platform administrator is
always ineligible as the subject. A uniform error covers missing and ineligible
accounts. One person may have at most one open `Invited`, `Accepted`, or
`Active` term in the representation.

An invitation creates the appointment and, when the person has no compatible
organization relationship, its narrowly labelled invited membership together.
An eligible existing active membership may be reused without weakening its
state. Invitation grants no capability. Only the exact authenticated, active,
verified invitee may accept or decline, using the appointment's expected
invitation version. A decline ends only a still-Invited Executive Board
membership created for that relationship. No controller may accept for another
person.

### Two-person activation and authority

Initial activation is a conspicuous platform-administrator operation, not a
routine lifecycle field edit. It requires:

- the exact Draft organization and its Provisioning representation;
- the current representation aggregate version;
- exact, case-sensitive re-entry of the organization name;
- a normalized reason of 1 through 240 characters;
- at least two distinct accepted Controller appointments;
- no unanswered controller invitation; and
- every accepted controller to remain active, verified, non-platform, and free
  of a suspended membership at the locked activation instant.

The transaction creates the reserved organization-scoped `executive-board`
role-bundle version, activates every accepted appointment and membership,
creates one durable assignment per controller, changes the representation to
Active, and changes the organization from Draft to Active. Either all of those
facts and their success evidence commit or none do.

The role-bundle version is immutable. Each initial assignment is granted by the
attributed platform operator and independently approved by another accepted
controller; with two controllers they approve one another, and with more they
form a deterministic cycle. No controller approves their own assignment. The
platform administrator is never the assignment principal, member, appointee,
participant, or approver. Future changes create a new role version or revoke
and replace an assignment; they never rewrite historical authority in place.

The initial root bundle contains only these code-reviewed organization-level
capabilities:

- organization basic view, profile change, series creation, and series change;
- Executive Board representation management;
- edition basic view and creation;
- bounded authorization delegation, root grant, immediate revocation, and
  role management; and
- minimized security-audit view.

Edition-specific profile or lifecycle authority, restricted-case access,
department positions, registration, participation, and workforce capacity are
not implied. Any later change to this root capability set requires a new
immutable role version, migration/review plan, and independent approval.

### Page 8 and authority boundaries

`/admin/platform/organizations/<organization-slug>/representation/` is Page 8,
**Representation & access**, inside the one ADR 0039 shell. POST-only child
routes own provisioning, invitation, self-response, and activation. Route
scope and selected-edition context never grant authority.

An active platform administrator may oversee the initial handoff. An account
with exact organization-scoped `organizations.view_basic` may view the bounded
record. An exact invitee may view only their own open appointment and answer
only that invitation. Appointment directories and account email are disclosed
only to representation managers. Mutations require either the explicit
platform bootstrap rule or `organizations.manage_representation` at the exact
organization scope. Denial happens without cross-tenant existence or principal
disclosure.

This page is the first concrete access explanation, but it is not the complete
UX-020 access editor. It may explain platform oversight, exact invitation
ownership, representation state, and active root assignments. Department,
resource, field, exceptional-access, and page-specific effective-access
explanations remain later M2 work.

### Strict input, concurrency, evidence, and replay

Every form has a closed input contract and accepts only its documented fields
plus CSRF. Organization, representation, appointment, actor, state, scope,
authority bundle, timestamps, and evidence identifiers are server-owned.
Unknown fields fail before mutation.

Provisioning and invitation are serialized under the representation or
organization lock. A duplicate provision or duplicate open invitation fails
safely and creates no second relationship. Invitation responses compare a
positive `invitation_version`; activation compares the positive representation
`aggregate_version`. A stale response, answered-invitation replay, stale
activation, or concurrent activation fails without overwriting the winning
change. Database uniqueness and state constraints are the final guard against
application-level races.

Every successful privileged change appends value-minimized, security-extended
audit evidence and a registered
`organizations.representation.changed.v1` domain event with transactional
outbox delivery. The event payload contains only the action, fixed
representation code, and resulting state; invitation email, display name,
reason text, organization profile values, and role capability list do not enter
the event payload. Assignment creation and final activation retain correlated
approval evidence. Sensitive reads and denied privileged attempts still need
explicit verification against AUD-001 before this slice is complete.

No API endpoint is declared by this ADR. Browser adapters call the same
module-owned commands that a future strict `/api/v1/` adapter must use. An API
must not be added until its idempotency, enumeration resistance, projection,
error, authentication, and approval semantics are documented in OpenAPI and
tested.

### Migration and recovery

The schema migration must add representation and appointment records without
inventing a real-person assignment or changing an existing organization's
lifecycle. Preflight must report every non-Draft organization without an active
representation and every conflict with the reserved `executive-board` bundle.
Those records require an explicit reconciliation plan; they must not be
silently demoted, auto-enrolled, or treated as compliant.

Old application nodes do not understand the activation invariant and are not
compatible after an M2 authority write. Before deployment, migration drift,
database constraints, forward upgrade, populated-data preflight, and a fresh
upgrade must pass. After the first successful provisioning or activation,
recover by retaining compatible code and fixing forward, or restore the whole
database to a mutually consistent pre-write point. Do not reverse only the new
tables while memberships, role assignments, audit events, or outbox records
refer to the governance change.

A failed transaction leaves no partial authority; an already committed domain
change with pending delivery is recovered by replaying the outbox, not by
repeating the governance command. Identity deactivation, verification loss,
suspended membership, an unanswered invitation, or a reserved-bundle conflict
blocks activation for human resolution.

## Consequences

- Tenant activation becomes an explainable human handoff instead of a hidden
  superuser side effect.
- At least two distinct people control root organization authority from the
  first active state.
- Organization profile and series services can authorize active Board
  assignments through the existing capability policy while keeping platform
  oversight separate.
- Page 8 adds personal invitation state and therefore requires tighter list,
  email, denial, audit, and tenant-isolation tests than Pages 1 through 7.
- Existing active demo, rehearsal, or imported organizations are migration
  debt until reconciled; test-only convenience must not weaken deployed
  invariants.
- Department hierarchy, appointment expiry/replacement/removal, complete
  effective-access explanations, invitation notification delivery, and a
  public API remain explicit follow-up work.

## Alternatives considered

### Automatically appoint the platform administrator

Rejected. It violates ADR 0031 and makes platform support appear in organizer
membership, authority, and convention history.

### Let one person activate themselves

Rejected. Root authority needs independent human control from its first
effective assignment; self-approval would make the audit trail ceremonial.

### Reuse Django Groups or an editable organization role field

Rejected. Neither carries tenant scope, immutable capability versions,
effective terms, exact acceptance, independent approval, or immediate
revocation semantics.

### Create the Board automatically with the organization

Rejected. Organization creation may be name-only and must not guess real
people or imply accepted authority. An explicit Draft-to-Active handoff is
easier to understand and recover.

### Keep the broad ADR 0024 bootstrap as the normal path

Rejected. It conflates legal representation, software authority, department
structure, workforce position, participation, and edition context. It remains
only recovery evidence until a separately reviewed reconciliation procedure
defines where it is still safe.
