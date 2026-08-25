# Governed Workforce Shift journey

- Date: 2026-08-25
- Outcome: Implemented the first complete Shift planning and personal Shift
  commitment journey, from Position demand through locked and completed work
- Requirements: HR-006, HR-009, HR-012 through HR-014, SCH-001, SCH-003,
  SCH-005, SCH-007, SAF-010, PRI-001, PRI-003, AUD-001, AUD-005, UX-005
  through UX-008, UX-020, UX-029, and NFR-001 through NFR-004
- Decision: ADR 0078

## Delivered outcome

The Workforce journey now has a usable fifth stage:

```text
Organization structure
  -> Position management
  -> Assignment management
  -> person-owned Availability
  -> Shift demand
  -> suitable personal work
  -> claim
  -> independent organizer confirmation
  -> locked coverage
  -> completed work record
```

**Shift planning** lets an exactly authorized organizer create private Position
demand, publish it, review claims, confirm or remove them with reasons, lock
accountable coverage, reopen it, complete ended work, cancel work, and inspect
the newest-first reason history where each decision is made. **My shifts**
lets a person find suitable open work and retain the full operational details
and truthful status of their own claims and commitments.

Availability remains person-owned planning input. It is never rewritten by a
Shift command, treated as a reservation, or used as proof that the person
accepted work. A Position assignment remains responsibility and authority
evidence rather than scheduled time.

## Product and navigation experience

- The durable organizer sequence is now **Structure**, **Positions**,
  **Assignments**, **Availability**, and **Shifts**. Every continuation stays in
  the selected organization, series, and edition and reauthorizes at its own
  destination.
- The Staff Console exposes **Plan shifts** or **Review shifts** only from fresh
  exact-edition action hints. The server-rendered Workforce pages provide the
  same continuation without making the React surface authoritative.
- **My Workforce** is now a first-class personal Work destination rather than a
  link hidden behind Administration. It is searchable, pinnable, and remains
  current across Positions, Availability, and Shifts.
- Shift cards lead with purpose, state, edition-local date and time, report
  location, coverage, Position, briefing, break, required rest, and
  supervision or handover. Singular and plural coverage language is correct.
- A locked Shift explains when completion will become available; it does not
  offer an executable completion control before the work ends.
- The shared admin-card and baseline heading styles now preserve readable
  contrast and compact 44-pixel continuation targets on narrow screens.

## State, suitability, and human decisions

A demand is Draft, Open, Locked, Completed, or Cancelled. A person's retained
commitment is Claimed, Confirmed, Removed, or Completed. Only Draft demand is
editable. Opening requires work that has not ended. Completion requires a
locked Shift whose end is in the past.

Suitable open work requires all of the following current facts:

- the demand is open, unended, and below capacity;
- the person has an active exact-Position assignment spanning the work;
- a submitted current Availability period fully covers it;
- the person has no active commitment to the same demand; and
- neither the work nor its minimum post-Shift rest overlaps another active
  commitment and rest envelope.

Preferred Availability sorts first but creates no entitlement. Confirmation
freshly rechecks Position, Availability version and coverage, overlap, rest,
and transactional capacity. A later Position or Availability change does not
silently rewrite a commitment; organizers and the person see a review warning.

Locking requires every active claim to be confirmed and current. Underfilled
coverage additionally requires an explicit acknowledgement and a reason.
Locked coverage must be reopened before a person can be removed or withdraw.
Position closure is blocked while Draft, Open, or Locked demand depends on it.

## Authorization, disclosure, and privacy

Authorization migration `0018_workforce_shift_capabilities` adds independent
exact-edition `workforce.view_shifts` and `workforce.manage_shifts`
capabilities, plus the relationship-derived self boundary. The organizer read
has a complete field ceiling and mandatory minimized sensitive-read audit.
Mutation authority never substitutes for read authority.

The organizer projection is bounded to 1,024 demands and 4,096 commitments,
runs in one repeatable read-only snapshot, repeats authorization before
disclosure, and returns complete or unavailable rather than truncating. The
personal projection exposes only suitable work and the person's own retained
commitments. It excludes other people, organizer identity and rationale,
private planning reasons, and exact Availability values.

A person may withdraw a Claim or Confirmation while planning is open. The
control requires affirmative confirmation and deliberately asks for no reason.
The receipt and organizer history retain only the fixed fact **The person
withdrew their own open Shift commitment.** This avoids turning a routine
self-service action into collected free text.

## Shared command and API boundary

Browser and versioned API adapters call the same demand and commitment
commands. They authorize exact scope before parsing private input or loading
names, reject unknown fields and coercion, require optimistic versions, and use
UUID idempotency keys. Demand and organizer decision commands require a bounded
reason; claim and withdrawal expose only their purpose-specific fields.

Every successful mutation writes aggregate state, immutable minimized command
receipt, audit, registered domain event, and outbox message in one transaction.
Stable HTTP boundaries distinguish malformed input, non-disclosing denial,
authorized missing targets, lifecycle or concurrency conflict, and unavailable
canonical dependencies. OpenAPI and generated TypeScript definitions cover the
new organizer and personal routes.

## Database, concurrency, and recovery

Workforce migration `0013_shift_journey` installs demand and commitment
aggregates, append-only receipts, exact-scope and subject checks, version-step
and final-receipt evidence, protected deletion and truncate, a one-active-claim
constraint, and a PostgreSQL exclusion over each active work/rest envelope.
Demand writes take the applicable locks in canonical edition, Department,
Position or demand, and commitment order. Capacity is decided in that same
transaction.

Raw Position closure and concurrent demand creation cannot race around the
dependency fence: both join the Position lock. Runtime provisioning and
readiness cover every new relation, function fingerprint, and exact trigger
attachment while denying direct runtime execution of guard functions.

A fresh disposable PostgreSQL database applied all migrations, reversed the
unused Workforce Shift and authorization capability migrations, and reapplied
them successfully. A second reversal against the synthetic walkthrough with
durable demand and receipt evidence failed at the intended fix-forward fence;
the transaction left migration `0013` applied and its data intact. The empty
rehearsal database was then removed.

## Verification

Completed locally:

- 77 focused unit and integration regressions pass across Shift lifecycle,
  commands, browser adapters, strict API, projections, raw database guards,
  demo data, navigation, existing Assignment and Availability behavior, and
  responsive shell/style contracts;
- the expanded runtime-role, exact function-fingerprint, trigger-attachment,
  authority-provenance, Organization structure, and retired-Department
  readiness gate passes all 453 cases in 863.84 seconds;
- a real two-connection PostgreSQL claim race proves that capacity cannot be
  oversubscribed;
- Staff Console generated API types, strict TypeScript checking, all 28 Vitest
  component/accessibility tests, and the production Vite build pass, with host
  assets refreshed;
- Django system check reports only the expected local invitation-encryption
  warning, and migration drift is zero;
- OpenAPI regenerates and validates without schema errors, and a repeated API
  client and production frontend build leaves all six generated contract and
  host artifacts byte-for-byte unchanged;
- documentation policy, full PyDocLint, the semantic Python-docstring
  validator, and warning-fatal Sphinx/AutoAPI all pass; and
- an authenticated synthetic owner-and-volunteer rehearsal passes at 1,280 and
  390 CSS pixels. It covers discovery, claim, independent confirmation,
  explicit underfilled lock, pre-end completion guidance, reopen, reasonless
  self-withdrawal, privacy-minimized retained history, drawer background
  isolation, Escape/focus return, one H1 and one `main`, no duplicate IDs, no
  unlabeled controls in the inspected forms, no horizontal overflow, and no
  browser console warning or error.

## Remaining gates

- Complete UX-029 at 320, 768, 958, 1,024, and 1,920 CSS pixels, 200 percent
  zoom, full keyboard paths, representative screen readers, reduced motion,
  and every empty, failure, stale, read-only, disclosure, and mutation-role
  state.
- Rehearse with two real human accounts, including stepped-up organizer
  confirmation and role transitions; synthetic sessions and automated
  separation are implementation evidence, not owner acceptance.
- Specify the next scheduling slice before implementation. General
  qualifications, maximum-hours and lone-working policy, public schedule
  publication, recurrence, notifications, calendar synchronization, check-in,
  lateness or absence escalation, actual time, handover acceptance, and
  replacement staffing are not provided by this journey.
- Approve and implement post-edition Availability disposal, legal holds,
  observability, and recovery before production personal data is allowed.
- Perform representative stopped-writer cutover, restore/PITR, deployment,
  privacy, load, security, operator training, and external acceptance before
  release.
