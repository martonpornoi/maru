# Shift planning and My shifts

- Status: Implemented first complete journey; full UX-029, recovery,
  deployment, and broader scheduling evidence remain gated
- Last updated: 2026-08-25
- Requirements: HR-006, HR-009, HR-012, HR-013, HR-014, SCH-001, SCH-003,
  SCH-005, SCH-007, SAF-010, PRI-001, PRI-003, AUD-001, AUD-005, UX-005
  through UX-008, UX-020, UX-029, and NFR-001 through NFR-004
- Decisions: ADRs 0041, 0049, 0053, 0055, 0075, 0076, 0077, and 0078

## Purpose and outcome

**Shift planning** lets an authorized organizer state what work is needed,
publish it to suitable people, review claims, lock accountable coverage, and
retain completion or cancellation evidence. **My shifts** lets one person see
only work they can currently claim and the full instructions and status of
their own retained claims and commitments.

The first complete outcome is:

```text
Position demand -> open suitable work -> personal claim
  -> independent organizer confirmation -> locked coverage
  -> completed work record
```

Availability is an input, not a reservation. A Position assignment is
responsibility and authority, not scheduled time. A claim is a request, not a
confirmation.

## Placement and routes

The durable Workforce sequence is:

```text
Structure -> Positions -> Assignments -> Availability -> Shifts
```

The Staff Console shows **Shifts** as **Available** and links to **Plan shifts**
or **Review shifts** only when the current exact-edition structure response
contains the corresponding action hint. The destination authorizes again.
Assignment and Availability pages provide the same continuation. **My
Workforce** links each related person to **My shifts**.

Canonical browser route families are:

```text
/admin/platform/organizations/<organization>/series/<series>/
    editions/<edition>/structure/shifts/
/admin/platform/organizations/<organization>/series/<series>/
    editions/<edition>/structure/shifts/<demand>/

/my/workforce/<organization>/<series>/<edition>/shifts/
```

The organizer pages remain inside Administration; the person-owned page
remains inside My Maru. Both use purpose names, one H1, the host's one `main`
landmark, edition-local times, and ordinary links and forms.

## Demand and coverage states

An organizer draft records Position, Shift name, report location, start and
end, required headcount, break, minimum post-Shift rest, briefing, optional
supervision/handover instruction, and a private planning reason. Only a draft
may be edited.

| Demand state | Meaning | Available actions |
| --- | --- | --- |
| Draft | Private work expectation | Edit, open before it ends, or cancel |
| Open | Suitable people may claim | Confirm/remove claims, lock, or cancel |
| Locked | Confirmed coverage is frozen | Reopen, complete after end, or cancel |
| Completed | Ended planned work retained | Read history |
| Cancelled | Work will not proceed | Read history |

One person's retained row is **Claimed**, **Confirmed**, **Removed**, or
**Completed**. Removal distinguishes person withdrawal, organizer removal, and
demand cancellation. Organizer confirmation/removal and demand lifecycle
actions require a reason; current decision rationale is visible in the Shift
detail alongside newest-first demand command history.

## Suitable work and personal privacy

A Shift appears under **Suitable open work** only when all current facts pass:

- the demand is open, has not ended, and retains capacity;
- the person has one active exact-Position assignment spanning the work;
- one current submitted Availability window fully covers the work;
- the person has no active commitment to that demand; and
- the work plus required post-Shift rest does not overlap another active
  commitment or its rest envelope.

Preferred Availability sorts before ordinary Available time; it is not a
promise or entitlement. The first slice does not rank by interests or infer a
general qualification profile beyond exact Position assignment.

**Your claims and commitments** retains the Shift name, Position, Department,
time, report location, briefing, supervision/handover, break, required rest,
state, and current suitability warnings. It excludes other people, organizer
identity, organizer rationale, planning reason, and private Availability
values. If the person's Availability or Position changes, the commitment stays
truthful but is marked for review rather than silently rewritten.

A person may withdraw a claimed or confirmed commitment while demand planning
is open. The form requires an affirmative checkbox and no explanation. Maru
retains a fixed withdrawal fact rather than user-authored text. Locked coverage
must first be reopened by an organizer.

## Organizer decisions and hard boundaries

The organizer projection requires `workforce.view_shifts` with the complete
Shift field ceiling. Mutation requires `workforce.manage_shifts`. Reads are
bounded to 1,024 demands and 4,096 commitments, return complete or fail with a
generic unavailable state, run in one repeatable read-only snapshot, repeat
full authorization at response time, and persist a minimized sensitive-read
audit before disclosure.

Confirmation is independent from the claimant and freshly rechecks Position,
Availability plan version and covering period, overlap, and rest. Capacity is
transactional. Locking fails while an active claim is unconfirmed or stale.
If confirmed coverage is below requested headcount, the organizer must both
select the explicit underfill option and record why the risk is accepted.

Completion is available only after an ended locked Shift and completes its
confirmed commitments atomically. Cancellation removes active commitments and
retains cancellation evidence. A Position cannot close while draft, open, or
locked demand still depends on it.

## API contract

The strict route families are:

```text
GET|POST /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/shifts
GET|PUT  /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/shifts/{demand_id}
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/shifts/{demand_id}/{open|lock|reopen|complete|cancel}
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/shift-commitments/{commitment_id}/{confirm|remove}
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/shifts/me
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/shifts/{demand_id}/claim
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/shift-commitments/{commitment_id}/withdraw
```

Every mutation requires a canonical UUID `Idempotency-Key`. Inputs are closed
JSON objects: strings, integers, booleans, and canonical UUIDs are never
coerced, and demand timestamps require `Z` or an explicit numeric offset.
Demand and organizer decision commands require a reason. Claim accepts only
`expected_version`; withdrawal accepts only `expected_version` and an
affirmative JSON boolean `confirm`.

The stable response boundary is `400` malformed or unsupported input,
name-free `403` absent exact authority, authorized target-only `404`, `409`
version/retry/lifecycle/state/qualification/Availability/capacity/overlap
conflict, and generic `503` unavailable canonical policy, projection, audit,
or database dependency. Query parameters are unsupported. Browser adapters use
the same commands and equivalent private, non-cacheable responses.

## Data, concurrency, and recovery

Demand and commitment commands take the applicable locks in canonical exact-
edition, active-Department, Position or demand, and commitment order. Claim
capacity and overlap/rest use the same transaction as the commitment and its
command evidence. PostgreSQL adds one-active-claim uniqueness and a person/time
exclusion over the Shift through required rest.

Workforce migration `0013_shift_journey` adds demand and commitment aggregates,
immutable receipts, scope and subject guards, exact state-evidence checks,
deferred receipt consistency, protected deletion/truncate, a Position closure
dependency, and a fix-forward downgrade fence. Authorization migration
`0018_workforce_shift_capabilities` adds separate organizer and person-owned
capabilities. Runtime ACL and provenance readiness include every new relation,
function fingerprint, and exact trigger attachment while withholding direct
trigger-function execution from the runtime login.

Successful commands write aggregate state, immutable receipt, minimized audit,
registered domain event, and outbox message atomically. Recovery fixes forward
or restores the complete database; it does not remove Shift guards after
durable evidence exists.

## Accessibility and acceptance

Cards use headings rather than styling alone. Status, suitability, and stale
evidence are readable text. Forms retain explicit labels, help, native
checkboxes, keyboard-operable details, and action-local alert errors. Times are
rendered in the edition's named zone, and narrow layouts must stack without
changing reading order or causing page-level horizontal scrolling.

Automated coverage includes complete lifecycle, stale Availability review,
capacity, overlap/rest, underfill, withdrawal privacy, tenant and person
isolation, strict API types, audited organizer reads, bounded query counts, raw
database guards, OpenAPI/client generation, and Staff Console navigation. An
authenticated owner-and-volunteer rehearsal passes at 1,280 and 390 CSS pixels:
it covers discovery from each home, claim, independent confirmation, explicit
underfilled locking, pre-end completion guidance, reopen, privacy-minimized
self-withdrawal, retained organizer history, responsive drawer focus and Escape
return, one H1 and one `main`, no duplicate identifiers, and no page-level
horizontal overflow. The remaining UX-029 widths, 200 percent zoom,
representative screen-reader behavior, and the complete empty, failure, stale,
read-only, and mutation-role matrix remain required before release acceptance.

## Explicit non-goals

- A general qualification/certification or interest-ranking engine.
- Maximum-hours, travel, lone-working, or sensitive accommodation decisions.
- Organizer-authored Availability or exposure of exact Availability in My
  shifts history.
- Notifications, calendar synchronization, recurrence, public schedule
  publication, or change acknowledgement.
- Check-in, lateness/absence escalation, actual time, handover acceptance,
  benefits, recognition, payroll, or timekeeping.
- Automatic replacement staffing, bulk scheduling, or silent safety override.
