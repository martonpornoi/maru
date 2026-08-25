# Assignment management contract

- Status: Proposal, independent stepped-up approval or rejection, active
  assignment ending, direct reason history, subject self-service, shared strict
  HTML/API commands, and stopped-writer database enforcement are implemented
  locally; complete rendered accessibility, recovery, deployment, and owner
  acceptance remain pending
- Overview route:
  `/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/assignments/`
- Personal route: `/my/workforce/`
- Requirements: HR-004, HR-007, HR-008, HR-010, HR-013, UX-005 through
  UX-008, UX-012, UX-020, UX-029, AUD-001, AUD-005, INT-001, NFR-001 through
  NFR-004, and NFR-008
- Decisions: ADRs 0019, 0028, 0041, 0044, 0045, 0049, 0055, 0075, and 0076

## Purpose and primary users

Assignment management lets an authorized organizer connect one known person to
one current Position without confusing intent with access. It answers:

- which Position and approved headcount are involved;
- why and for what interval a person is proposed;
- which onboarding prerequisites are ready or blocked;
- whether a genuinely different current controller has decided the proposal;
- which role and participation evidence approval activates; and
- why an active responsibility and its authority ended.

The organizer workflow requires `workforce.view_structure` and
`workforce.manage_assignments` at the exact edition. Proposal, approval, and
rejection also require `authorization.manage_roles`; ending instead requires
`authorization.revoke`. Active platform administrators may exercise explicit,
attributed oversight but cannot be assignment subjects.

A signed-in person uses **My Workforce** to see only their own Position,
Department, organization, edition, state, and intended dates. They do not see
organizer reasons, controller identities, authority provenance, candidate
lists, or another person's assignments.

This is not a general people directory, application-acceptance shortcut,
onboarding-document reviewer, availability collector, shift planner, generic
role editor, or specialist model form.

## Placement and navigation

**Workforce** presents Structure, Positions, Assignments, Availability, and
Shifts in dependency order. The Assignments stage opens this workspace only
when the fresh structure response says the viewer has both assignment and role
authority. Position management also links directly to the assignment queue and
to proposal for a current Position. Every destination authorizes again; action
hints are not authority.

The browser route family is:

```text
GET  .../structure/assignments/
GET  .../structure/positions/{position_id}/assignments/new/
POST .../structure/positions/{position_id}/assignments/propose/
GET  .../structure/assignments/{assignment_id}/
POST .../structure/assignments/{assignment_id}/approve/
POST .../structure/assignments/{assignment_id}/reject/
POST .../structure/assignments/{assignment_id}/end/
GET  /my/workforce/
```

GET and POST responsibilities are separate. Successful commands use
POST/Redirect/GET. Organizer pages retain the selected-edition trail, one H1,
page-local **Access** disclosure, and private `no-store` response contract.
Forms are CSRF protected and reject query parameters.

## Assignment queue and Position entry

The bounded queue lists proposed records first, followed by active and retained
history. Each row uses human person, Department, and Position labels; state,
intended start, and Position-specific onboarding progress; and a clear review
action. A proposer sees that another controller must decide their proposal.
Raw UUIDs remain transport identifiers and never become visible labels.

The same page lists current Positions with purpose, active occupancy, approved
headcount, a Position-detail link, and **Propose a person** where lifecycle and
authority permit it. Empty, read-only, Closing-edition, no-Position, and
oversized-projection states explain the next valid action without exposing a
specialist record fallback.

## Relationship-bounded proposal

Proposal starts from a current Position. Its selector contains only active
person accounts already related through at least one of:

- a current or historical organization relationship;
- non-cancelled participation in the edition;
- a submitted, under-review, or accepted application for that Position;
- an onboarding request in the organization and edition; or
- retained Workforce assignment history in the organization and edition.

The complete candidate set is capped at 512 and excludes a person who already
has a proposed or active assignment for the Position. Candidate labels show
the relationship source and the count or completion of that Position's current
onboarding requirements. Maru accepts no arbitrary account identifier from the
browser and exposes no global email or account search.

The proposer supplies an aware effective start, optional later ending, and a
required normalized reason. Browser times use the edition's IANA time zone and
reject nonexistent or ambiguous daylight-saving minutes. API timestamps need
`Z` or an explicit numeric UTC offset.

A proposal reserves one approved headcount place and records immutable command
evidence at version 1. It deliberately creates no participation, capacity,
RoleAssignment, capability, or schedule commitment. Incomplete onboarding is
shown but allowed at proposal time so the intended responsibility can guide the
remaining work.

## Independent decision

Only a different currently authorized controller may approve or reject a
proposal. The server derives the actor from their authenticated session; there
is no approver field. Both actions require a fresh step-up check before parsing
the submitted reason, retry key, or expected version.

Approval is available only when every required onboarding item is currently
approved. Under one transaction it rechecks exact scope, lifecycle, Position
state, headcount, person identity, immutable RoleBundle provenance, and both
controllers' authority. It then:

1. activates the authorization-owned scoped RoleAssignment;
2. activates edition participation and Position capacity evidence;
3. changes the proposal to active at the next assignment version;
4. retains the independent actor, time, and reason; and
5. writes audit, domain-event, outbox, and exact receipt evidence.

Rejection also requires the different controller and fresh step-up. It grants
nothing, records a final rejected state and decision evidence, and frees the
reserved headcount. Neither outcome can be reopened or overwritten.

## Retained ending

An active assignment may be ended by a currently authorized revoker after a
fresh step-up check. The command revokes the linked RoleAssignment immediately,
records actor, time, and reason, and completes only Position-specific or
configured participation capacities that no other active assignment for that
person still needs. It recalculates the Position's filled or open state and
retains all assignment history.

An expiry timestamp communicates the intended interval but is not silent
authority revocation. An active record past its planned ending is labelled
**Expired — ending required** until an authorized human completes the retained
ending command.

## Directly inspectable manager history

The assignment detail shows newest-first proposal, approval, rejection, and
ending reasons with action, version, time, and actor label to an authorized
manager. These private reasons are absent from minimized domain events and the
subject's **My Workforce** view. Legacy records receive a truthful no-history
state; Maru does not invent prior reasons or actors.

## Personal state

**My Workforce** is separate from Administration. A person sees proposed,
active, rejected, ended, and expired states only for their own account and an
already permitted organization/edition relationship. A proposal explicitly
says it grants no access until independently approved. Active records link to
the person's own onboarding documents. Each related edition also exposes the
person-owned Availability state and
purpose-built editor from the
[Availability management](availability-management.md) contract. Editing
requires a current proposed or active assignment; an existing plan remains
reviewable and withdrawable after that open relationship ends. Shifts remain a
separate continuation: [My shifts](shift-planning-and-my-shifts.md) uses only a
current active exact-Position assignment as the first qualification fact, and
never turns the assignment itself into scheduled work.

The personal route accepts no query parameters, is private and non-cacheable,
and returns a generic state when its complete bounded projection is unavailable.

## API contract

The mounted strict API mutations are:

```text
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/positions/{position_id}/assignments
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/assignments/{assignment_id}/approve
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/assignments/{assignment_id}/reject
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/assignments/{assignment_id}/end
```

Every mutation requires a canonical `Idempotency-Key`. Proposal returns `201`
on first success and `200` on identical replay; decisions return `200`.
Proposal input contains `account_id`, `effective_from`, optional `expires_at`,
and `reason`. Decision input contains `expected_version` and `reason`.
Responses contain only `assignment_id`, `assignment_version`, `status`, and
`replayed`.

Inputs are closed JSON objects with strict canonical UUIDs, strings, positive
versions, and offset-bearing timestamps. Authorization precedes header and body
parsing. Denied or unavailable route scope uses a uniform name-free `403`; an
authorized unavailable Position, candidate, or assignment uses `404`;
validation uses `400`; stale version, retry, lifecycle, readiness, headcount,
or state conflicts use `409`; unavailable canonical dependencies use `503`.
OpenAPI and generated TypeScript types are checked in.

## Database evidence and recovery

Workforce migration `0011_owner_assignment_commands` adds assignment command
versions, explicit rejection, decision and ending evidence, and immutable
`PositionAssignmentCommandReceipt` rows. It installs stopped-writer functions
and exact trigger attachments, extends runtime readiness fingerprints, and
keeps receipt helpers unreachable by the runtime login.

For a governed row, PostgreSQL requires the next assignment version and exactly
one receipt whose action, assignment, Position, tenant scope, actor, reason,
and resulting version match the state transition. It rejects direct deletion,
scope/identity/Position/interval/proposer mutation, skipped transitions,
incomplete approval or ending evidence, altered authority links, receipt
mutation, and writes without command evidence.

The migration preserves internally consistent legacy rows without fabricating
versions, decisions, or reasons. After governed writes, recovery fixes forward
or restores the complete database to a mutually consistent pre-write point; it
does not reverse this guard independently.

## Accessibility and acceptance

The workflow must retain one H1, logical section headings, visible labels and
help, status words independent of color, keyboard-native links/forms/details,
focus visibility, and action-local error summaries. A server-rendered mutation
failure focuses its summary while retaining field errors and submitted values.
Fresh-authentication return targets must remain local and return the user to
the exact assignment action.

The pages must reflow at 320 CSS pixels and 200 percent zoom without page-level
horizontal scrolling. Decision controls need understandable disabled states;
stale forms must require reload without losing the entered reason; and the
independent-controller handoff must remain clear to screen-reader users.

Current automated evidence covers command idempotency and atomicity, exact
authorization and tenant isolation, candidate bounding, lifecycle, headcount,
onboarding, dual control, role/capacity activation and revocation, retained
history, subject minimization, step-up before body parsing, strict API inputs,
browser proposal-through-ending, raw database-write rejection, and runtime
readiness. Complete rendered width/zoom, keyboard, screen-reader, recovery,
deployment, and two-human owner acceptance remain release gates.

## Deliberate non-goals

This slice does not add arbitrary people search, bulk assignment, assignment
replacement, approval notifications, onboarding-review orchestration,
availability, shifts, timekeeping, or schedule publication. An active
assignment is responsibility and authority evidence, not proof of when someone
can work or a scheduled shift.
