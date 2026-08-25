# Availability management

- Status: Implemented focused slice; complete deployment retention and UX-029
  evidence remain gated
- Last updated: 2026-08-25
- Requirements: HR-006, HR-009, HR-014, SCH-001, SCH-003, SCH-005, PRI-001,
  PRI-003, PRI-005, AUD-001, AUD-005, UX-005 through UX-008, UX-020, UX-029,
  and NFR-001 through NFR-004
- Decisions: ADRs 0016, 0019, 0041, 0049, 0053, 0055, 0075, 0076, and 0077

## Purpose and outcome

Availability management lets a person communicate when organizers may plan
work for their current exact-edition Position. The person owns the complete
statement, may keep a private draft, and deliberately chooses whether to share
it. An independently authorized organizer receives only the current planning
consequence needed for people with proposed or active assignments.

The outcome is an unambiguous input to later Shift planning:

- no submitted plan means **unknown**, not available and not unavailable;
- a private draft remains visible only to its owner;
- a submitted empty plan means **not available for this edition**;
- submitted periods are the complete current availability set, so time outside
  those periods is unavailable; and
- withdrawal removes every exact current period immediately.

Availability is not a shift, promise, reservation, attendance record, time
record, authority grant, or organizer-authored HR note.

## Placement and navigation

The durable Workforce sequence is:

```text
Structure -> Positions -> Assignments -> Availability -> Shifts
```

The Staff Console makes **Availability** interactive when the current structure
response includes `can_view_availability`; otherwise it says **Access
required** and exposes no link. Assignment management provides the organizer
continuation after current responsibilities. Every destination authorizes
again, so the action hint is not authority.

**My Workforce** gives a related person one Availability continuation for each
edition in which they retain assignment history. It names the current state
and open Position titles. A person may open an existing plan after the final
assignment ends, but may replace it only while at least one assignment remains
proposed or active.

The browser routes are:

```text
/my/workforce/<organization>/<series>/<edition>/availability/
/my/workforce/<organization>/<series>/<edition>/availability/save/
/my/workforce/<organization>/<series>/<edition>/availability/withdraw/

/admin/platform/organizations/<organization>/series/<series>/
    editions/<edition>/structure/availability/
```

The owner route remains in the personal surface. The organizer route remains
inside the selected-edition administration frame with one H1, one page-local
**Access** disclosure, and no second global menu or context selector.

## State model

One person owns at most one plan per organization and edition. Its optimistic
command version begins at one and advances exactly once for each committed
replacement or withdrawal.

| Persisted state | Owner meaning | Organizer consequence | Exact current periods |
| --- | --- | --- | --- |
| No plan | Not started | Not shared | None |
| `draft` | Private draft | Not shared | Visible only to owner |
| `submitted` with periods | Shared with organizers | Shared | Current submitted periods |
| `submitted` without periods | Not available for this edition | Not available | None |
| `withdrawn` | Withdrawn | Withdrawn | Deleted immediately |

Draft and absent plans are deliberately indistinguishable to organizers.
Organizers must not infer a person's behavior or availability from **Not
shared**. Superseded period values are not history records.

## Person-owned workflow

An active person may create or replace a plan only when they have a proposed
or active Position assignment in the exact edition. The browser page explains
the complete-set meaning before the editor and offers two primary outcomes:

- **Save private draft** replaces the current set without disclosure; and
- **Share with organizers** replaces and deliberately publishes the current
  set.

Each period has an inclusive start, exclusive end, and one planning signal:
**Available** or **Preferred**. Preferred is a soft preference only. The
browser uses the edition's named IANA time zone, shows the inclusive edition
date horizon, and never asks the person to choose an offset manually.

The editor is a progressively enhanced repeatable form. Every row has a
fieldset and numbered legend, explicitly associated controls, and a keyboard-
operable remove/undo action. JavaScript may add and focus another row, but the
server-rendered form remains a valid one-period or empty-plan workflow without
JavaScript. Saving always replaces the complete set; a removed or omitted
period is not retained implicitly.

An owner may withdraw any non-withdrawn existing plan while the organization
and edition still permit withdrawal, including after the open assignment
relationship ends. Withdrawal requires an explicit checkbox and immediately
deletes current exact periods. It is not account deletion or a request to
erase required minimized command evidence.

## Exact interval and time-zone contract

Canonical periods are aware, half-open intervals `[starts_at, ends_at)`. A
complete set must:

- contain no more than 64 periods;
- use only `available` or `preferred`;
- have an end strictly after its start;
- remain inside the inclusive local dates from `edition.starts_on` through
  `edition.ends_on` in `edition.time_zone`; and
- contain no overlaps. Touching boundaries are valid.

Browser local times are converted only when they identify one real instant in
the edition time zone. Daylight-saving gaps and folds are rejected with a
field error rather than guessed. API timestamps require `Z` or an explicit
numeric UTC offset. Storage and interval exclusion use normalized instants;
presentation returns to the edition time zone.

The first contract has no recurrence rule, free-text constraint, calendar
import, or all-day shorthand. A later convenience editor may expand repeated
input into the same explicit intervals, but may not create a second canonical
representation.

## Organizer projection

The organizer page and API start from a bounded complete set of people with a
proposed or active assignment in the exact edition. Each row may include only:

- the current account display label;
- current Department and Position labels;
- proposed or active assignment state;
- current shared consequence;
- sharing time for a submitted plan; and
- current submitted periods with Available or Preferred labels.

The projection excludes drafts, reasons, notes, superseded periods, unrelated
people, application content, onboarding documents, account security state,
authority provenance, and other HR data. It is complete-or-unavailable: a
cardinality or integrity bound returns a generic failure instead of a partial
people list.

The organizer route requires the independently persistable
`workforce.view_availability` capability at exact edition scope with the
complete `availability_consequences`, `availability_windows`, and
`holder_display_labels` field ceiling. The read runs in a repeatable read-only
snapshot, repeats the full policy decision at response time, and appends a
minimized sensitive-read audit before values are released. Audit failure means
no disclosure.

## API contract

The strict versioned routes are:

```text
GET|PUT /api/v1/organizations/{organization_id}/editions/{edition_id}/
    workforce/availability/me
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/
    workforce/availability/me/withdraw
GET /api/v1/organizations/{organization_id}/editions/{edition_id}/
    workforce/availability
```

`PUT` is a complete replacement with `expected_version`, `status`, and a
bounded `windows` list. Withdrawal accepts only `expected_version`. Mutations
require a canonical `Idempotency-Key` UUID header. Top-level and nested
objects are closed; unknown or repeated fields are rejected. Query parameters
are unsupported.

Adapters authorize the exact person relationship or organizer capability
before parsing private mutation input or loading display labels. Successful
first replacement returns `201`; replay and later replacements return `200`.
An identical retry returns the prior minimized result, while reusing its key
for different input is a conflict.

Stable failure classes are:

- `400` for malformed, unsupported, ambiguous, overlapping, or out-of-horizon
  input;
- name-free `403` for absent identity, relationship, capability, or exact
  tenant/edition scope;
- `409` for stale versions, changed retry input, incompatible lifecycle, or
  current-state conflict; and
- generic `503` when a canonical policy, projection, audit, or database
  dependency cannot safely complete.

Browser adapters use the same commands and equivalent private, non-cacheable
responses. Failed mutations preserve entered values, present an action-local
error summary, and identify when a reload is required.

## Data, evidence, and recovery

Current exact periods are C2 personal operational data. The current plan shell
and minimized receipts retain person, exact tenant/edition, state, version,
count, digests, command actor, idempotency, correlation, and source evidence.
Receipts, audit events, and domain events contain no exact period values or
free-text explanation. Mutation audits use a generic nonnegative target count;
organizer-read audits contain no person identifier or result count.

Workforce migration `0012_person_owned_availability` installs:

- one-plan-per-person exact-scope and person-kind guards;
- current-version and edition-horizon period guards;
- a PostgreSQL non-overlap exclusion constraint;
- replacement-only period mutation;
- immutable exact-version command receipts;
- deferred final plan, period-count, digest, and receipt consistency;
- protected deletion and truncate fences with the repository's test-only reset
  boundary; and
- the IDN-011 prohibition against converting a retained Workforce subject into
  a platform administrator.

Authorization migration `0017_workforce_availability_capability` adds the
organizer capability and preserves the database scope catalog. Runtime ACLs
allow select/insert/update on plan aggregates, select/insert on receipts, and
select/insert/delete but not update on replacement-only periods. Trigger
functions are fingerprinted and not directly executable by the runtime role.

After a governed write exists, recovery fixes forward or restores the complete
database to a mutually consistent point. The availability migration has a
downgrade fence and is not independently reversed through live retained data.

Exact current periods need an organization-approved maximum post-edition
retention policy, legal-hold behavior, and disposal worker. That deployment
policy is not invented as a global code constant. Production retention
readiness remains gated until it exists; owner withdrawal already removes
current exact values immediately.

## Responsive and accessibility contract

The owner and organizer pages inherit the shared shell's single `main`
landmark and render one H1. State is always text, with color only redundant.
Periods use fieldsets, legends, labels, help text, and ordinary date-time
controls. Errors use alert semantics; stale failures provide a direct reload
action. Dynamic add/remove controls are buttons, preserve formset semantics,
move focus to a new row, and remain operable by keyboard. Organizer lists use
semantic headings and labelled Position and period lists.

At narrow widths, headings, summaries, period controls, actions, Position
rows, and period rows stack without changing reading order or requiring a
different workflow. UX-029 still requires the full authenticated width/zoom,
keyboard, representative screen-reader, reduced-motion, empty/failure/stale/
read-only, and mutation-role matrix before release acceptance.

## Explicit non-goals

- Organizer-authored or edited availability.
- Inferring availability from assignment dates, registration, applications,
  onboarding, profile values, or a missing plan.
- Storing medical, accessibility, family, travel, conduct, or other explanatory
  notes in ordinary Workforce availability.
- Qualifications, demand, claims, assignment to time, overlap or rest policy,
  publication, attendance, completion, locking, or shift recovery. These belong
  to the next Shift contract.
- Calendar synchronization, recurrence, notification delivery, bulk organizer
  editing, historical exact-period browsing, or production disposal automation.
