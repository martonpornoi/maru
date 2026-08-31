# ADR 0076: Govern Position assignments through independent decisions

- Status: Partially superseded by ADR 0080 (unconditional Participation
  activation and completion only)
- Date: 2026-08-24
- Extends: ADRs 0019, 0028, 0041, 0044, 0045, 0049, 0055, and 0075
- Requirements: HR-004, HR-007, HR-008, HR-010, HR-013, UX-005 through
  UX-008, UX-012, UX-020, UX-029, AUD-001, AUD-005, INT-001, NFR-001 through
  NFR-004, and NFR-008

## Context

Maru already had the domain service that could activate a Position assignment
after two controllers approved it. The only management surface was a generic
specialist record form in which one signed-in operator selected another account
as approver. That was useful implementation evidence, but it did not prove an
independent human decision, provide a separate approval session, explain
onboarding readiness, or give organizers and assignment subjects a coherent
journey.

Position management now provides immutable responsibility and RoleBundle
meaning, explicit headcount, a typed Position resource, and protected closure.
The next user-visible boundary must connect a known person to that Position
without turning application acceptance into authority, exposing a general
people directory, or making a proposal itself an access grant. Approval must
remain safe if headcount, onboarding evidence, lifecycle, identity, or either
controller's authority changes after proposal.

Ending is part of the same lifecycle. A row marked ended while its linked role
remained effective would mislead both the person and organizers. Conversely,
ending one of several assignments must not remove shared participation
capacities still justified by another active assignment.

## Decision

### Separate proposal from decision

One exact-edition **Assignment management** workspace owns a bounded queue,
Position-specific proposal page, and assignment detail page. Proposing requires
current `workforce.view_structure`, `workforce.manage_assignments`, and
`authorization.manage_roles` authority. It records the selected person,
effective interval, reason, version 1 receipt, audit, and
`workforce.position_assignment.proposed.v1` event, but grants nothing.

Approval and rejection are separate POST decisions. The actor must be different
from the proposer, must independently hold the same three current capabilities,
and must complete a fresh step-up authentication check before the browser or API
parses the decision body. The server does not accept an approver identity as
input. The proposal page and detail page explain this two-person handoff, and a
proposer sees that another controller must continue.

### Use a closed, relationship-bounded candidate set

The proposal form lists only active person accounts already known through a
current or historical organization relationship, edition participation,
Position application, onboarding request, or Workforce assignment. The read is
bounded, tenant scoped, and label minimized. It excludes anyone who already has
a proposed or active assignment for that Position. No arbitrary account UUID,
email search, platform administrator subject, or cross-tenant lookup is
accepted.

For each candidate, the form shows only the status of onboarding documents
required by the selected Position. Incomplete evidence is visible as a blocker
but does not prevent a proposal: the interval and intent can be recorded while
the candidate completes onboarding. Approval rechecks every requirement and
fails atomically unless all are currently approved.

### Treat proposals as non-authoritative headcount reservations

A proposed assignment occupies one approved headcount place so concurrent
organizers cannot over-promise a Position. The proposal still creates no
Participation, ParticipationCapacity, RoleAssignment, CapabilityGrant, or
schedule commitment. Approval rechecks the Position, open assignment set,
candidate kind and activity, effective interval, and current headcount under
the canonical edition and Department lock order.

Approval invokes the existing authorization-owned dual-control role command.
The original proposer and current approver must both retain the required
authority at activation time. The immutable Position RoleBundle version and
typed scope remain server owned. The same transaction activates edition
participation, adds the configured capacity codes and stable
`position.<position-code>` capacity, marks the assignment active, records the
second-controller decision, and publishes audit/event/outbox evidence.

### Make rejection and ending explicit retained states

Rejection is a final decision on a proposal, not deletion. It records the
independent actor, time, reason, next assignment version, audit, receipt, and
`workforce.position_assignment.rejected.v1` event while granting nothing.

Ending requires `workforce.view_structure`,
`workforce.manage_assignments`, and `authorization.revoke`, plus fresh step-up
authentication and the exact current version. It revokes the linked
RoleAssignment through the authorization module, records ending evidence,
completes Position-specific and configured capacities only when no other active
assignment still needs them, recalculates Position occupancy, and publishes
`workforce.position_assignment.ended.v1`. Rejected and ended records remain
inspectable history and cannot be reopened or deleted.

### Share commands and enforce their evidence in PostgreSQL

Browser and strict versioned API adapters call the same proposal, approval,
rejection, and ending commands. Every request is closed, tenant and edition
scoped, idempotent through a canonical retry UUID, and version fenced after
proposal. Authorization and route resolution precede header or body parsing.
Denied scope remains name free; unavailable authorized targets use `404`;
validation uses `400`; stale version, retry, lifecycle, readiness, and headcount
conflicts use `409`; dependency failure uses `503`.

Workforce migration `0011_owner_assignment_commands` adds command versions,
decision and ending evidence, immutable receipts, and stopped-writer triggers.
PostgreSQL requires exactly one same-version receipt whose action, actor, scope,
reason, and resulting state match every governed transition. It rejects direct
deletion, immutable proposal changes, skipped or reversed states, malformed
authority evidence, and receipt mutation. Existing internally consistent
assignments remain readable as legacy rows until their owning recovery path is
explicitly reconciled; the migration does not invent historical decisions.

### Minimize the subject view

**My Workforce** shows a signed-in person only their own assignments in scopes
where they have an existing relationship. It includes organization, edition,
Department, Position, state, and effective interval, with truthful links to
their onboarding documents or public opportunities where applicable. It does
not disclose proposal, approval, rejection, or ending reasons; controller
identities; candidate lists; authority provenance; or another person's row.
This is a self-service read, not an organizer action surface.

### Preserve Availability and Shifts as separate contracts

An assignment establishes responsibility and scoped authority. It does not
assert when a person is available or create scheduled work. Availability and
Shifts retain their labelled places in Workforce but remain noninteractive
until their privacy, conflict, commitment, and recovery contracts are accepted.

## Consequences

- Non-staff organization owners can complete the real assignment lifecycle
  without specialist model administration.
- A second authenticated person makes the decision; selecting another person's
  name in one session is no longer presented as dual control.
- Organizers can plan against bounded headcount while onboarding is incomplete,
  but no authority exists until every approval-time check passes.
- Assignment reasons are directly inspectable by authorized managers while the
  subject view remains deliberately reason minimized.
- Ending is operationally complete: the assignment, linked authorization, and
  no-longer-needed capacities converge in one transaction.
- Position closure can now be unblocked through the owning assignment workflow
  instead of through direct database or specialist-record mutation.
- Database guards increase migration and recovery coupling. After live `0011`
  writes, recovery fixes forward or restores the complete mutually consistent
  database; the guard is not reversed independently.
- Availability, shift planning, notifications, bulk assignment, replacement,
  and onboarding-review orchestration remain later outcomes.

## Alternatives considered

### Keep the specialist form and select an approver

Rejected because one session choosing another identity is not an independent
decision and cannot provide fresh approver authentication or a trustworthy
inbox.

### Require all onboarding before proposal

Rejected because a proposal is non-authoritative planning intent. Showing
readiness early lets organizers and candidates resolve prerequisites, while the
transactional approval check remains the grant boundary.

### Search every platform account from the proposal form

Rejected because it would disclose unrelated identities, create cross-tenant
risk, and bypass the meaningful relationship that makes a person a plausible
candidate.

### Count only active assignments against headcount

Rejected because multiple pending proposals could promise more places than a
Position permits and force arbitrary rejection after onboarding work.

### End only the Workforce row

Rejected because retaining effective linked authority would make the visible
assignment state false. Authorization revocation and unused-capacity completion
are part of the command transaction.
