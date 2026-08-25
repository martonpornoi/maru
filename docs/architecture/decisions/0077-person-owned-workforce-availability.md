# ADR 0077: Keep Workforce availability person-owned and deliberately shared

- Status: Accepted
- Date: 2026-08-25
- Extends: ADRs 0016, 0019, 0041, 0049, 0055, 0053, 0075, and 0076
- Requirements: HR-006, HR-009, HR-014, SCH-001, SCH-003, SCH-005, PRI-001,
  PRI-003, PRI-005, AUD-001, AUD-005, UX-005 through UX-008, UX-020, UX-029,
  and NFR-001 through NFR-004

## Context

Position assignments now establish a person's responsibility and scoped
authority, but intentionally say nothing about when that person can work. Shift
planning cannot safely begin from assignment dates, a registration answer, or
an organizer's assumption. A person needs a low-friction way to communicate
their own workable times, while an organizer needs only the operational
consequence needed to plan coverage.

Availability is personal data. Draft behavior, free-text explanations, and
superseded exact times would create unnecessary disclosure and retention risk.
Recurring calendar rules would also introduce avoidable daylight-saving and
exception ambiguity. Event editions are already bounded to at most 31 days, so
the canonical first slice can use explicit intervals without losing practical
coverage.

## Decision

### Treat absence, unavailability, and availability as different facts

One person may own one availability plan per organization and edition. The
plan has an optimistic command version and one of three states: private draft,
submitted, or withdrawn.

- no submitted plan means the organizer does not know;
- a submitted plan with no windows means the person explicitly reports that
  they are not available;
- a submitted plan with windows is the complete planning set, so time outside
  those windows is unavailable for that plan version; and
- a withdrawn plan exposes only the withdrawal consequence and no exact time.

Saving a draft never releases its windows. Sharing is an explicit action. A
person may replace a shared plan directly, but every replacement is a complete
new current statement rather than a patch whose omissions are ambiguous.

### Use exact edition-local intervals

Canonical availability is a bounded set of non-overlapping, half-open aware
intervals. Each interval is labelled **Available** or **Preferred**. The latter
is a soft planning preference, not a commitment or entitlement. The interval
must fall within the inclusive edition calendar dates in the edition's IANA
time zone. Browser controls reject daylight-saving gaps and folds; strict API
timestamps require `Z` or an explicit numeric UTC offset.

The canonical model contains no recurrence rule. The edition's maximum span
makes explicit intervals understandable, makes exceptions visible, and gives
future conflict checks exact instants. A later convenience control may expand a
repeating input into the same explicit windows, but recurrence never becomes a
second source of truth.

### Bind writing to the person and reading to purpose

Only an active person who has a proposed or active Position assignment in the
exact edition may create or replace a plan. An existing owner can still read or
withdraw it after that open relationship ends. Organizers cannot write on the
person's behalf.

The personal route and API use relationship-derived self authority. The
organizer projection requires the separate persistable
`workforce.view_availability` capability at the exact edition. It starts from
bounded proposed and active assignments, releases only display label,
Department and Position labels, shared state, and current submitted windows,
and performs a fresh final decision plus minimized sensitive-read audit before
disclosure. Draft and absent plans both appear as **Not shared**.

### Minimize retained evidence

Replacing a plan removes its superseded window rows in the same transaction;
withdrawing removes all current exact windows immediately. Receipts retain the
actor, action, version, state, count, idempotency key, keyed fingerprints, and
request provenance, but not exact times or free text. Audit and domain events
contain state, count, and changed-field names only.

Exact windows are C2 current operational data. Their purpose ends after the
edition and staffing-support period. A reviewed organization retention policy,
legal-hold behavior, and disposal worker must choose and enforce the maximum
post-edition period; code does not invent a jurisdiction-independent duration.
Until that deployment policy exists, production retention readiness remains
explicitly gated. Withdrawal does not wait for that later job.

### Keep availability separate from shifts

Availability is planning input, not a reservation, promise, assignment, shift,
attendance record, or authorization grant. The next Shift contract must still
own demand, suitability, claims, confirmation, overlap and rest enforcement,
publication, completion, locking, and recovery. It may compare a proposed
shift to the current submitted availability version, but cannot reinterpret an
older plan or silently override hard policy.

## Consequences

- People control what is shared and can distinguish “not available” from “I
  have not answered.”
- Organizers receive enough current information for coverage planning without
  receiving draft behavior, explanations, or superseded calendars.
- Explicit intervals avoid recurrence and DST ambiguity and are directly
  usable by the future conflict model.
- Full replacement, optimistic versioning, idempotency, immutable receipts,
  database interval constraints, and command evidence make concurrent edits
  deterministic.
- A person may need to enter split periods explicitly. The browser therefore
  supplies an accessible repeatable-period editor as progressive enhancement.
- Qualifications, rest needs, shift demand, commitments, notifications,
  calendar import, recurrence helpers, and post-edition disposal automation
  remain separate outcomes.

## Alternatives considered

### Infer availability from assignment dates

Rejected because responsibility dates are not a person's workable times and
would turn absence of information into a false staffing promise.

### Let organizers enter or edit a volunteer's availability

Rejected because it removes subject control, obscures provenance, and invites
sensitive explanations into an ordinary planning record.

### Store free-text constraints or reasons

Rejected for the first slice because free text easily accumulates medical,
accessibility, family, travel, or conduct details that ordinary workforce leads
should not receive. Separate purpose-specific workflows own those facts.

### Store recurring weekly rules as the canonical model

Rejected because recurrence, exceptions, edition boundaries, and daylight-
saving transitions make the planning fact less explicit. A bounded edition can
store the expanded intervals directly.

### Preserve every historical window version

Rejected because exact superseded whereabouts and routines have little audit
value compared with their privacy cost. Minimized receipts prove the command
without preserving the old calendar.
