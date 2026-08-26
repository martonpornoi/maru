# ADR 0078: Govern Shift demand, self-claim, and coverage as one journey

- Status: Accepted
- Date: 2026-08-25
- Extends: ADRs 0016, 0019, 0041, 0049, 0053, 0055, 0075, 0076, and 0077
- Requirements: HR-006, HR-009, HR-012, HR-013, HR-014, SCH-001, SCH-003,
  SCH-005, SCH-007, SAF-010, PRI-001, PRI-003, AUD-001, AUD-005, UX-005
  through UX-008, UX-020, UX-029, and NFR-001 through NFR-004

## Context

Maru now distinguishes an edition's Position structure, an approved person's
responsibility, and that person's deliberately shared Availability. None of
those facts says that a particular period of work is needed or accepted. The
next useful user outcome must connect them without turning Availability into a
promise, exposing one person's calendar to another volunteer, or letting two
concurrent claims silently exceed coverage.

A first Shift slice also needs a truthful stopping point. Check-in, actual time,
maximum-hours policy, lone-working rules, accommodations, schedule publication,
notifications, and live escalation are larger contracts. Treating them as
implicitly implemented would make the interface unsafe and the roadmap
misleading.

## Decision

### Use separate demand and commitment aggregates

An organizer creates one exact-edition `ShiftDemand` against a current
Position. A draft carries the human-recognizable name, report location,
briefing, optional supervision or handover instruction, aware start and end,
required headcount, planned break, and minimum rest after the work. It follows
this explicit lifecycle:

```text
draft -> open -> locked -> completed
   \       \       \
    +-------+-------+-> cancelled
                 locked -> open
```

Only a draft may change its work expectation. Opening publishes an immutable
expectation; an ended Shift cannot newly open. Reopening is a recovery action
that returns locked coverage to planning without rewriting the original work.
Cancellation retains the demand and removes every active claim or confirmation
with cancellation evidence.

A person's `ShiftCommitment` is separate and follows:

```text
claimed -> confirmed -> completed
   \           \
    +-----------+-> removed
```

The commitment snapshots the demand interval, required post-Shift rest,
matching Position assignment, and Availability plan version used by the
decision. Historical removed and completed rows remain visible to their owner.

### Derive suitability from current explicit facts

The first qualification rule is deliberately narrow: the person must hold one
active assignment for the demand's exact Position throughout the Shift. A
current submitted Availability window must completely cover the work interval.
The demand must be open, unfinished, and below capacity, and it must not
overlap another active commitment or that commitment's required rest envelope.

**My shifts** shows only the current person's suitable open work and retained
commitments. It never releases another person's identity, organizer reasons,
or planning rationale. A claim is the person's request, not organizer
confirmation. The person may withdraw while planning is open through an
explicit confirmation checkbox. Maru does not ask for or retain a personal
free-text explanation; command evidence records only the fixed fact that the
person withdrew.

### Make organizer confirmation and locking explicit

The separate exact-edition `workforce.view_shifts` capability protects the
complete organizer projection and `workforce.manage_shifts` protects commands.
The bounded read includes demand, operational instructions, coverage counts,
display labels, current qualification and Availability consequences, and
directly inspectable current confirmation, removal, and completion rationale.
It executes in one repeatable read-only snapshot, repeats authorization at
response time, and persists a minimized sensitive-read audit before release.

An organizer cannot confirm their own claim. Confirmation freshly rechecks the
matching Position, current submitted Availability version and covering window,
overlap, and rest. Locking requires every active claim to be confirmed and
current. Coverage below requested headcount may lock only after the organizer
explicitly accepts underfill and records a reason; capacity itself is never
overridden. Completion is permitted only for ended locked work and completes
all confirmed commitments atomically.

### Enforce concurrency and evidence below the adapters

Browser and API adapters call the same strict, optimistic, idempotent commands.
Applicable locks follow edition, Department, Position or demand, then
commitment order. Claim capacity and person overlap/rest are checked under
those locks and backed by PostgreSQL unique and exclusion constraints. Position
closure fails while draft, open, or locked demand depends on it; complementary
Position and demand triggers serialize raw concurrent closure and creation.

Each successful mutation advances exactly one aggregate version and writes an
immutable command receipt, minimized audit record, registered domain event,
and outbox message in the same transaction. PostgreSQL rejects scope drift,
published-work rewrites, invalid transitions, incomplete actor/time/reason
evidence, unsupported subject kinds, missing exact-version receipts, ordinary
deletion, and destructive truncate. Once durable Shift evidence exists,
recovery fixes forward or restores the complete database to a mutually
consistent earlier point.

### Stop at planned commitments

This decision implements demand through planned completion evidence. It does
not claim general qualifications, ranked recommendations, maximum hours,
lone-working policy, sensitive accommodation handling, attendance/check-in,
actual time, benefits, notifications, calendars, schedule publication, or live
coverage escalation. Those remain separate requirements even when the Shift
page has a truthful place for them.

## Consequences

- A person can understand available work, claim it, keep their instructions,
  distinguish awaiting review from confirmed work, and leave planning without
  disclosing why.
- Organizers can create demand, inspect current coverage and rationale, confirm
  independently, resolve claims, accept explicit underfill, lock, recover,
  complete, or cancel from one purpose-based workflow.
- Availability remains person-owned planning input. A changed plan does not
  silently rewrite a commitment; it marks active coverage for review and blocks
  locking until an organizer reconfirms current evidence.
- Exact Position assignment is only the initial qualification vocabulary.
  Broader certification and interest matching can extend suitability later
  without changing the demand/commitment distinction.
- Database constraints and command receipts increase migration and recovery
  ceremony, but they keep API, browser, fixture, and concurrent-client writes
  on the same integrity boundary.
- The first journey can be useful before check-in and timekeeping exist, while
  its UI and documentation must continue to name those omissions.

## Alternatives considered

### Treat an active Position assignment as a scheduled Shift

Rejected because responsibility and authority do not identify a time, place,
briefing, capacity need, or personal decision.

### Let a claim immediately become confirmed coverage

Rejected because current qualification, Availability, overlap, rest, and
headcount need an independently accountable organizer decision.

### Store a volunteer's withdrawal explanation

Rejected because an ordinary cancellation reason can invite medical, family,
travel, accessibility, or conduct disclosure with no operational need. The
withdrawal fact is sufficient; organizer removal still requires rationale.

### Edit published demand in place

Rejected because changing time, place, Position, care instruction, or workload
would silently change what people claimed. Cancel and recreate, or use a later
explicit revision protocol.

### Implement a complete scheduling engine first

Rejected because it would delay the coherent high-value demand-to-coverage
journey and mix current facts with unaccepted publication, attendance,
notification, policy, and live-operations decisions.
