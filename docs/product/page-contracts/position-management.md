# Position management contract

- Status: Creation, complete edit, opportunity publication, protected closure,
  direct reason history, shared HTML/API commands, and stopped-writer database
  enforcement are implemented locally; complete rendered accessibility,
  recovery, deployment, and owner acceptance remain pending
- Overview route:
  `/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/positions/`
- Requirements: HR-007, HR-010, HR-011, HR-012, UX-005 through UX-008,
  UX-012, UX-020, UX-029, AUD-001, AUD-005, INT-001, NFR-001 through
  NFR-004, and NFR-008
- Decisions: ADRs 0019, 0028, 0041, 0044, 0045, 0055, and 0075

## Purpose and primary users

Position management lets an authorized organizer turn a Department structure
into understandable responsibilities and truthful volunteer opportunities for
one event edition. It answers:

- what work exists and why;
- where that responsibility belongs;
- which Position it reports to;
- how many people may hold it;
- what immutable role meaning an eventual assignment would carry;
- whether and when volunteers may apply; and
- why each organizer changed or closed it.

The workflow serves an organizer with both `workforce.view_structure` and
`workforce.manage_structure` at the exact edition. Active platform
administrators may exercise explicit oversight as attributed actors. A
view-only organizer continues to see the minimized Position projection in
Workforce and Organization structure but receives no mutation form.

This is not an assignment-approval inbox, person directory, availability form,
shift planner, generic access editor, or generic model form.

## Placement and navigation

**Workforce** presents Structure, Positions, Assignments, Availability, and
Shifts as one dependent journey. Its Positions stage opens this workspace when
the fresh structure response says the viewer may manage Positions; otherwise
it moves to the read-only Position summary already on the page. The destination
authorizes again, so the boolean is an action hint rather than authority.

Organization structure also exposes **Manage Positions** after at least one
current Department exists. The Position pages retain the same selected-edition
trail, one H1, page-local **Access** disclosure, no secondary global menu, and
private `no-store` response contract as Department management.

The browser route family is:

```text
GET  .../structure/positions/
GET  .../structure/positions/new/
POST .../structure/positions/create/
GET  .../structure/positions/{position_id}/
POST .../structure/positions/{position_id}/update/
POST .../structure/positions/{position_id}/opportunity/
POST .../structure/positions/{position_id}/close/
```

GET and POST responsibilities are separate. Successful commands use
POST/Redirect/GET. Every form is CSRF protected, rejects query parameters, and
keeps tenant/edition locators out of the visible content until the complete
persisted route chain and both capabilities are authorized.

## Overview and creation

The bounded overview groups Positions beneath their human Department names and
shows title, purpose, reporting label, status, approved headcount, current
holder count, opportunity state, and whether applications are currently
accepted. It shows a clear empty state and one **Create Position** action. Raw
UUIDs remain transport links and are not rendered as human labels.

Creation requires:

- one published Position template owned by the organization and backed by a
  historically valid immutable RoleBundle issuance;
- one active Department in the exact edition;
- an optional current same-edition reporting Position;
- a required normalized title and plain-language purpose;
- headcount from 1 through 500;
- the current structure aggregate version;
- a canonical retry UUID; and
- a required retained reason.

The template and Department selectors are bounded and ordered. The template
label explains its version, RoleBundle, and default headcount. The Department
help text makes its permanence explicit. Reporting is operational presentation
only and never grants authority.

One successful command creates the Position in `planned` state, its private
`draft` volunteer opportunity, and its exact typed resource binding. Code,
RoleBundle, and capacity codes come from the template. An identical retry
returns the original minimized result; reuse for a different request conflicts.
Failure of any paired write, audit, event, outbox message, or binding rolls the
whole command back.

The preserved legacy empty-organization recovery bootstrap has one internal,
non-HTTP exception for its first Convention Chair because historical RoleBundle
issuance cannot predate that ceremony. The command verifies the exact
platform-administrator, empty-Position, structure-version-1,
`convention-chair` template and independent template-role approval state. It
still writes the complete governed Position/opportunity/binding and version-2
evidence set; no owner form or API field can request this exception.

## Position details

Organization, edition, Department, template, RoleBundle, code, capacity codes,
creator, and creation version are immutable. A current Position may replace:

- title;
- purpose and responsibilities;
- approved headcount; and
- its optional reporting Position.

The complete replacement must preserve a bounded acyclic reporting graph.
Headcount cannot be lower than the count of proposed and active assignments.
Normalized no-ops do not advance the structure version or write evidence.

The detail summary keeps immutable authority meaning next to current operations:
Department, reporting label, assignment occupancy, template version, future
RoleBundle version, opportunity state, and retained application count. This
does not imply that editing a Position grants the RoleBundle to anyone.

## Volunteer opportunity

Every Position has one separately publishable opportunity. Its editable
applicant-facing fields are headline, description, optional opening and closing
times, visibility after headcount is filled, and lifecycle state.

Browser forms interpret and redisplay those times in the edition's persisted
IANA time zone and reject nonexistent or ambiguous daylight-saving minutes.
API timestamps require an explicit `Z` or numeric UTC offset; server-local or
offset-free timestamps are rejected.

The allowed lifecycle is:

```text
draft -> published -> closed -> published
  |           |          |
  +-----------+----------+-> withdrawn (final)
```

Draft is private. Publishing a planned Position moves that Position to `open`
in the same structure version. A published opportunity appears in the public
volunteer list only inside its date window and stops accepting applications at
approved headcount. `visible_when_filled` controls whether it remains
discoverable then. Closed may be republished while the Position is current;
withdrawn cannot be reopened.

Publication creates no application, acceptance, participation, assignment,
RoleAssignment, capability grant, or schedule commitment.

## Protected closure

Closure requires the exact current Position title and a reason. It is refused
while any of these remain:

- a proposed or active PositionAssignment;
- a direct report whose Position is not closed; or
- current or future Position-scoped CapabilityGrant or RoleAssignment
  authority.

The owning assignment, reporting, or access workflow must end that dependency;
Position management does not silently revoke it. Successful closure is
one-way, records actor and time, retains every related row, and closes a paired
opportunity unless it is already closed or withdrawn. The page becomes a
read-only historical record and cannot reopen through update or publication.

## Directly inspectable history

The Organization structure overview shows recent structure reasons to an
authorized manager. Each Position detail shows its own newest-first command
history with human action label, aggregate version, time, actor label, and full
organizer-entered reason. The reason is intentionally absent from minimized
domain events and public projections, but it is not hidden in an unrelated
security log or backend-only receipt.

Existing legacy Positions receive no invented creation history. Their first
governed change begins directly inspectable evidence at the real resulting
version.

## API contract

The mounted strict API mutations are:

```text
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/positions
PUT  /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/positions/{position_id}
PUT  /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/positions/{position_id}/opportunity
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/positions/{position_id}/close
```

Create requires a canonical `Idempotency-Key`; first success returns `201` and
replay returns `200`. Other successful operations return `200`. Inputs are
closed JSON objects with strict strings, integers, booleans, canonical UUIDs,
and timestamps carrying an explicit UTC offset. Responses contain only
`position_id` and the resulting aggregate version.

Authorization precedes header and body parsing. Denied or unavailable route
scope uses the uniform name-free `403`; an authorized unavailable Position or
relationship uses `404`; validation uses `400`; stale version, retry, lifecycle,
state, dependency, and bound conflicts use `409`; unavailable canonical
dependencies use `503`. OpenAPI and generated TypeScript types are checked in.

The structure GET adds `can_manage_positions`. It still requires the complete
view projection and repeats fresh view authorization before disclosure. The
management hint is computed at the same final instant and neither discloses a
hidden actor nor bypasses destination authorization.

## Database evidence and recovery

Workforce migration `0010_position_structure_commands` installs Position and
opportunity structure-version fields, closure evidence, affected-Position
receipts, and stopped-writer guards. It refuses a pre-existing Position whose
template and RoleBundle disagree. Existing internally consistent Positions
remain readable with null creation versions. Their first real governed Position
or opportunity change records only its actual resulting version; no false
creation receipt or actor is backfilled.

For governed writes, PostgreSQL requires the current aggregate version and
exactly one immutable receipt whose action, Position, changed fields, actor,
Department scope, and resulting version match the row transition. It rejects
identity/scope/template/role/capacity mutation, invalid reporting graphs,
invalid opportunity windows or transitions, direct deletion, and changed rows
without command evidence. Recovery fixes forward or restores the complete
database to a mutually consistent pre-write point; it does not reverse this
guard independently after live Position writes.

## Accessibility and acceptance

The workflow must retain one H1, logical H2/H3 sections, visible labels and help
text, status words independent of color, keyboard-native links/forms/details,
focus visibility, and error summaries near their owning action. A server-
rendered mutation failure moves focus to its programmatically focusable summary
while retaining field-local errors and entered values. The page must also
support 320-pixel and 200-percent-zoom reflow without page-level horizontal
scrolling. Stale forms must say that a reload is required and keep the submitted
values available for review.

Current automated evidence covers command normalization/idempotency,
authorization-before-lookup, tenant scope, reporting cycles, headcount and
dependency fences, opportunity publication, one-way closure, atomic rollback,
first-change adoption of internally consistent legacy rows, the tightly bounded
initial-Chair bootstrap exception, raw database-write rejection, strict API
objects and method routes, owner HTML
creation-through-closure, newest-first visible reasons, private caching, and
view-only denial. Complete rendered keyboard, screen-reader, responsive,
failure-state, representative recovery, and owner-browser acceptance remains a
release gate.

## Deliberate non-goals

This slice does not add Position-template authoring, assignment proposal or
independent approval, onboarding-document review, person availability, shift
demand/claim/confirmation, timekeeping, notification, or bulk operations.
Assignment records remain a temporary staff-only specialist workflow until a
separate owner-safe dual-control journey is accepted.
