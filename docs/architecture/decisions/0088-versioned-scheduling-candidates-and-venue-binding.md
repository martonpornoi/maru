# ADR 0088: Separate Scheduling candidates from physical reservations

- Status: Accepted
- Date: 2026-09-07
- Extends: ADRs 0053, 0081 and 0087
- Requirements: SCH-001, SCH-003, SCH-004, SCH-007 through SCH-010,
  PRG-008, VEN-001, VEN-002, VEN-008, AUD-001, AUD-003 and NFR-013
- Issue: [#81](https://github.com/martonpornoi/maru/issues/81), child of
  [#48](https://github.com/martonpornoi/maru/issues/48)

## Context

Programme owns accepted content and explicit hosts. Venues already reserves
physical rooms and requires an independent physical decision. Neither owns
service days, stable Programme occurrences or comparable timetable drafts.
Creating an ordinary live VenueBooking for every draft alternative would make
alternatives conflict with one another and confuse a proposal with a reservation.
Keeping only a mutable grid would lose the exact timing, dependency and reason
behind a later decision. Scheduling therefore needs its own bounded candidate
model before the editor and release children can use it.

## Decision

### Own service days, occurrences and immutable candidate revisions

Scheduling owns exact-organization/edition planning control, service days,
stable occurrences and versioned candidates. Service-day revisions contain an
explicit label, ordered window and grid precision inside the current Events
date envelope. Windows may cross local midnight but may not overlap. Adjacent
windows remain distinct service days. Persist instants in UTC; Events remains
the owner of the IANA zone and current edition bounds. Browser-local input must
reject ambiguous or nonexistent minutes, while offset-bearing input identifies
an exact instant. Grid precision is a positive whole-minute divisor of one hour
and is anchored to the service-day start.

Explicit retirement retains a mistaken service day's revisions and makes its
existing placements stale rather than deleting them. Limit one edition to 32
active and 128 retained service-day identities, 2000 retained occurrences and
100 retained candidates. Metadata supports 1000 ordinary revisions and a final
retirement; candidates support 10000 ordinary revisions and a final archive.
The separate candidate bound accommodates building a full timetable one
placement at a time. Bounds fail explicitly, never truncate a passing result.

Each occurrence binds one exact Programme item without copying its private
content or creating a Venue booking. Related or repeated occurrences have
explicit stable group/sequence identity; recurrence creates ordinary explicit
occurrences, not an unbounded rule that changes history when interpreted later.
An occurrence survives placement, movement, resizing and candidate copying.

A candidate revision is an immutable, complete bounded manifest of immutable
placement revisions. A placement names one occurrence, service-day revision,
selected space, capacity request and ordered preparation/effective/teardown
envelope. Copying a candidate preserves occurrence identity and the selected
source revision. Editing one candidate creates new evidence without changing
another candidate or an old revision. Unplacement removes an occurrence only
from the new manifest; it does not delete history or the occurrence.

Use explicit current versions and one actor/edition retry namespace. Every
meaningful command retains actor, reason, old/new state, resulting candidate
version and minimized receipt/audit/event/outbox evidence. A reasoned historical
restore creates a new candidate revision rather than rewriting a previous one.
No command in this child approves or publishes a Programme timetable.
Routine draft placement edits may use an inspectable code-owned action reason;
warning acknowledgement, historical restore, archival and physical reservation
require explicit human rationale. Pointer editing must not invent a person's
explanation or silently bypass a required reason.

### Make draft conflicts truthful and explainable

Structural authorization, ownership, boundedness and interval shape always
fail closed. A draft may retain an incomplete or conflicting proposed placement
so a planner can compare alternatives. Such a placement is explicitly blocked
or unchecked; storing it is neither consent, room reservation nor approval.

An evaluation declares exact owner/version conflict-source descriptors,
current dependency versions, the candidate revision and completeness. It
distinguishes hard blockers, reason-overridable warnings and an unavailable
check. Missing availability never means free. A failure or bounded overflow
never becomes a partial passing result. An acknowledgement binds the exact
warning and dependency fingerprint; changed sources require fresh evaluation.
Acknowledging a warning cannot remove a hard blocker or unavailable check.

The first sources cover edition/service-day bounds, Programme item and explicit
host consequences, and Venue availability, configured/fire capacity and physical
member occupancy. Apply ADR 0053's two-clique rule to both candidate placements
and current physical reservations. Only the permitted preceding teardown and
following preparation overlap is a turnover window; room combinations still
conflict on every physical member. Do not claim to check future Workforce
coverage/rest, equipment, travel or accessibility-fit adapters before their
declared evidence exists. Programme accessibility-readiness evidence is not an
automatic physical accessibility-fit decision based on free text.

Occurrence-specific host presence is distinct from room occupancy. The planner
explicitly selects current item relationships and required presence intervals
within the work envelope; the ordinary presence interval is effective delivery.
Room preparation or teardown does not silently require every host's attendance.
A planner's selection cannot confirm a person, share availability or override
withdrawal. Empty host selection is not proof that hosting is unnecessary:
Programme must explicitly identify the concern as not applicable. Same-person
overlap is checked across occurrences through an independently authorized,
edition-bounded Programme conflict key, not a private Identity model import.

Programme and Venues provide minimized current queries with independent field
ceilings. Evaluate current shared host periods only in memory; historical
candidate/conflict evidence retains versions, digests and outcomes, not copied
availability windows, private drafts, contact, proposal answers or review text.
Released-copy, private planning, physical operations and host-dependency reads
remain separate purposes. A generic candidate read is not authority for any
restricted owner layer.

Physical members can be shared with another edition of the same organization.
The exact physical-dependency purpose may reveal only their current busy
intervals clipped to the requesting edition's time envelope, with an
edition-bounded pseudonymous conflict key and source version. It must not
release the other edition or booking identifiers, titles, contacts or review
actors. This checks genuine physical contention without opening another
edition's administrative schedule. No cross-organization source is admitted.
The physical source key is the first 128 bits of SHA-256 over the canonical
ASCII domain/edition/booking tuple `venue-physical-conflict@1:<edition>:<booking>`,
formatted as a UUID. This is a scoped opaque correlation key, not authority or
a generated object identity. Both the owner query and PostgreSQL source-freshness
guard verify this same extension-free derivation.

### Deliberately reserve an occurrence through Venues

Only an explicit governed reservation operation can turn an exact placement
revision into physical occupancy. It requires both Scheduling authority and
the exact Venue-space authority, then calls Venue-owned commands inside one
transaction. A retained typed binding joins the occurrence, source placement
revision and Venue booking with reciprocal evidence. Free-text external
references are never canonical identity. Alternative candidates do not all
reserve rooms.

A reservation is still not Venue approval or Programme publication. Physical
availability, capacity and occupancy are rechecked by the Venue owner and its
database guards. Host/content/staffing readiness remains an independent
Programme approval consequence; a room hold does not establish it. Venue
approval is independent of the people responsible for the physical placement,
including its Scheduling source. A bound booking cannot independently publish
Programme timing or be generically rescheduled around its source contract.
Unrelated bookings retain ADR 0053's existing lifecycle.

The source placement author's retained identity is attribution and an approval
exclusion, not continuing authority over the draft. Another currently authorized,
active verified planner can reserve that unchanged placement after its author
becomes inactive or unverified. Recovery of the author's account does not erase
their exclusion from independent approval. Current reservation and approval
actors still require current verified-person eligibility.

Replacing a reservation is explicit and retains the former booking/binding.
The old cancellation and replacement occupancy/binding/evidence commit
together; failure leaves the old reservation intact. An occurrence retains its
stable identity across replacement. Cancelling physical use retains history
and makes current candidate evaluations report the missing or invalid binding.
At most one live physical reservation may be bound to one occurrence.

Future release work must join this boundary atomically with release activation
or invalidation as required by ADR 0081. This child has no active release to
invalidate and must not introduce an independent public schedule as a shortcut.

### Serialize owners and keep adoption dormant

Use the exact edition mutex before deterministic current-person, Programme,
Scheduling and physical-space locks. Ordinary Venue writers participating in
the binding boundary must use the same order; a read-before-write conflict
preview is not the concurrency guarantee. Current identity, profile, scope and
source state are rechecked under that transaction. Late audit, effect, binding
or deferred-integrity failure changes no success state.

Events owns a separate scheduling-write consequence admitting Draft,
Preparing, Ready and Live editions, while Closing, Archived, Cancelled and
unknown lifecycle states deny new planning writes. This supports later on-site
successor candidates without reopening Programme's private content or host
invitation commands. Those owners retain their existing lifecycle rules.

Declare exact Scheduling and owner-adapter capabilities and descriptors, but
do not widen either existing literal adoption manifest. New Scheduling runtime
relations remain SELECT-only. There is no new route, UI, API, worker, delivery
handler, root role or profile activation. Private candidate planning is not a
public, host or volunteer timetable. Existing purpose relationships create no
Registration, Participation, payment, attendance or unrelated-module state.

Additive owner migrations enforce scope, versions, immutable manifests,
binding identity, complete evidence and protected history. Readiness and runtime
provisioning cover the exact new schema. Unused reversal is supported; durable
Scheduling or binding evidence fences contraction. Django may reverse unused
successors before an older populated fence refuses, so recovery verifies the
protected owner evidence and explicitly reapplies the complete current graph.
Never fabricate migration, approval, consent or source receipts to recover.

## Consequences

Planners can explore alternatives without monopolizing rooms or hiding missing
dependencies. Explicit reservation and independent physical approval add a
deliberate step, but preserve honest authority and a single future release.
Versioned manifests retain recoverable draft history while making later editor,
comparison and approval behavior depend on the same commands. The workflow
remains dormant until its visible continuations, release, staffing, continuity,
guided setup and integrated acceptance are delivered under #48.

## Verification

Test real service-day/DST and three-phase boundaries, candidate independence,
same-person overlap, hidden/empty/withdrawn availability, stale dependencies,
capacity and combinations, warning fingerprints, scoped field denials,
idempotency, actual concurrent writes and late rollback. Verify raw database
integrity, SELECT-only runtime readiness, safe unused reversal, populated
fences and forward recovery, including affected historical conversion/host
tests. Full exact-head local certification and green protected hosted delivery
remain required; this decision alone is not implementation or adoption proof.
