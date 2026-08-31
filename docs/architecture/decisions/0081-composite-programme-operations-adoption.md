# ADR 0081: Make Programme operations a composite progressive-adoption profile

- Status: Accepted
- Date: 2026-08-31
- Extends: ADRs 0001, 0003 through 0005, 0041, 0051, 0078, and 0080
- Partially supersedes: ADR 0053 only where a Programme-kind VenueBooking may
  independently publish public schedule truth
- Requirements: IDN-014, EVT-006, EVT-007, HR-009, HR-013 through HR-015,
  PRG-001 through PRG-008, SCH-001 through SCH-012, OPS-001, OPS-002, OPS-005,
  OPS-009, INT-005, INT-007, INT-008, NFR-005, NFR-008, and NFR-013
- Issue: [#57](https://github.com/martonpornoi/maru/issues/57), child of
  [#48](https://github.com/martonpornoi/maru/issues/48)

## Context

Maru's first executable bounded profile proves that a convention can adopt the
complete Workforce journey without adopting attendee Registration, payments,
attendance, or Participation. Programme currently has useful but disconnected
foundations: Applications owns typed intake and review evidence, Venues owns
physical spaces and occupancy, and Workforce owns governed staffing. There is
no accepted Programme item, timetable candidate, release, or on-site
projection joining those boundaries.

A Programme department needs one understandable journey from setup through
calls, review, accepted-item readiness, conflict-aware timetable planning,
volunteer coverage, publication, and on-site use. Calling that outcome
`programme_only@1` would hide real dependencies. Applications, Venues, and the
complete current Workforce journey are deliberate parts of the requested
operation, not accidental implementation details.

The current adoption-policy helpers resolve only a profile code and then allow
every capability in an adopted module namespace. That is insufficient for a
second bounded profile. An immutable stored version would have little meaning
if a later capability, destination, effect, or conflict adapter silently
entered its behavior. The contract therefore precedes activation and requires
exact manifest resolution before runtime implementation.

ADR 0053 also gives an independently approved VenueBooking its own publication
lifecycle and public/My schedule projection. A shared Programme release cannot
coexist with a second independently publishable Programme timetable. The Venue
physical decision remains necessary, but public Programme occurrence identity
and timing need one owner.

## Decision

### Introduce one exact composite profile

The next bounded profile is `programme_operations@1`. Every enforcement and
disclosure decision resolves the exact `(profile code, profile version)`
manifest. Resolution includes policy, capabilities, destinations, effects,
catalog entries, background handlers, adapters, conflict sources, queries, and
navigation. An unknown or unsupported version fails closed. Adding a new
capability to an adopted module does not add it to an existing profile version;
expansion requires a new reviewed manifest and explicit adoption decision.

The version-one manifest declares the following product boundary:

| Manifest area | Declared boundary |
| --- | --- |
| Shared foundations | Identity, Organizations, Events, Authorization, Audit, Effects, and Privacy operations. |
| Adopted product modules | Applications, Programme, Scheduling, Venues, and the complete current Workforce journey. |
| Bounded supporting behavior | Programme on-site/run-sheet projections and purpose-specific service delivery through separately pinned effects and adapters. |
| Excluded product modules | Participation, Registration, payments, attendance, Accreditation, catalog and charity, broad Logistics, a general Communications workspace, and personalized attendee features. |
| Primary destination | Programme operations, continuing from calls and review through readiness, timetable, staffing coverage, release, and on-site use. |

The implementation manifest must pin exact capability, destination, effect,
catalog, and adapter codes rather than rely on the broad module list above.
The intended destination set is **Set up Programme operations**, **Programme
calls**, **Programme review**, **Programme readiness**, **Timetable planning**,
**Venue planning**, the complete current **Workforce** sequence, **Programme
Now**, **My applications**, **My host run sheet**, and **My shifts/timetable**.
Unimplemented destinations remain absent, and the profile cannot be offered as
supported until every mandatory continuation is ready.

Permitted effects are minimized audit, registered domain events,
transactional outbox work, explicitly declared Programme collaboration
invitation, application-decision, and schedule-change delivery, and versioned
export or print artifact generation. Those service effects do not create a
general Communications workspace, audience, campaign, social-posting
authority, or unrelated message history.

The enabled conflict adapters are edition/service-day bounds, Programme host
availability and overlap, Venue hard availability, configured/fire capacity
and physical occupancy, declared accessibility fit, and Workforce Shift
coverage and retained commitments. A conflict result records which exact
adapters and versions were checked. Registration, attendance, Participation,
Logistics, or any other unadopted source is neither queried nor described as
checked.

### Retain truthful accountable authority and purpose relationships

Setup reuses an existing truthful organization representation or provisions
two accountable Maru operators. It does not invent an Executive Board. A new
immutable, independently approved operator-role version or profile-specific
root bundle must declare the exact Programme Operations authority. Existing
Workforce-only operator authority is not widened in place, and organization-
scoped root authority applies to an edition only when its exact profile
manifest permits the requested capability.

Programme coordinator, call editor, reviewer, moderator, final decision maker,
readiness owner, timetable planner, venue operator, independent approver,
publisher, host, co-host, and volunteer are separate purpose relationships.
Account existence, invitation acceptance, hosting, review, planning, or
volunteer work creates no attendee Participation, Registration, payment,
attendance, membership, or unrelated public profile.

An exact host or co-host relationship and a retained Shift commitment are
valid personal-timetable relationships. The public programme and those
personal projections must work without a Participation row.

### Preserve module ownership

- **Events** owns edition identity, lifecycle, the immutable adoption profile,
  and guided profile setup orchestration.
- **Applications** owns calls, typed proposals, collaborative revisions,
  private answers, staged review evidence, conflicts, moderation, decisions,
  and the typed accepted-target receipt.
- **Programme** owns the accepted Programme item, host relationships,
  readiness, approved public renditions, and delivery history.
- **Scheduling** owns occurrence identity, public timing, service days,
  candidates, placements, conflict results, overrides, approval, immutable
  releases, supersession, and release-derived projections.
- **Venues** owns reusable spaces, edition selection, hard availability,
  configured/fire capacity, physical occupancy, and the independent physical
  approval required for a Programme placement.
- **Workforce** owns Departments, Positions, Assignments, Availability,
  ShiftDemand, claims, confirmations, locked coverage, and completed planned
  work.
- **Audit and Effects** own their existing evidence and delivery boundaries;
  they do not become sources of Programme or schedule state.
- **Bounded Programme operations projections** own now/next, run-sheet,
  change-impact, acknowledgement, and last-published continuity views. General
  incident command, dispatch, attendance, and Shift actual-time records remain
  outside this profile version.

Cross-module work uses closed, versioned commands, minimized queries, and
registered domain events. No new Programme or Scheduling code may import
another module's private models or write another module's tables directly.

### Advance accepted proposals without sharing private review data

An accepted exact proposal revision may create exactly one Programme item
through an idempotent typed Applications adapter. Rejected, wait-listed,
withdrawn, or undecided proposals create none. A reasoned organizer command may
create ceremonies, breaks, announcements, and other core Programme items
without fabricating a submitter or review.

Applications retains private proposal and review evidence. Programme stores
only the explicit accepted transition, stable source reference, necessary
approved facts, readiness evidence, and reviewed public renditions. Restricted
host contact, technical, accessibility, consent, and departmental discussion
layers keep separate field ceilings, authority, history, and retention.

### Give Programme one released timetable while Venues owns occupancy

Programme owns accepted item identity. Scheduling owns occurrence identity and
public timing. Venues remains the authority for physical space, availability,
capacity, occupancy, and physical approval.

This decision partially supersedes ADR 0053 only for Programme-linked
bookings. A Programme placement requires the exact current Venue decision, but
the VenueBooking cannot independently publish or withdraw a second Programme
timetable. Programme public, host, room, API, calendar, signage, and print
outputs derive from one active Scheduling release. Venue-owned bookings that
are unrelated to Programme retain ADR 0053's accepted approval and publication
lifecycle.

If Venue approval, hard availability, capacity, configuration, or physical
occupancy becomes invalid for a placement in the active release, the Venue-
changing application service must join Scheduling's exact-release invalidation
boundary in the same transaction. It either activates an already approved safe
successor or retains the immutable release while appending a reasoned
invalidation that immediately removes the unsafe room assignment from normal
public, host, volunteer, room, API, calendar, signage, and print projections.
A change-impact or relocation-pending rendition replaces the unsafe claim;
failure to persist both Venue and Scheduling evidence changes neither.

Known invalidation also revokes the ordinary last-published degraded snapshot.
An offline overlay or newly versioned fallback must show the occurrence as
withdrawn or relocation pending and must never continue to claim that the
space is approved.

An approved immutable candidate may be published only by a separately
authorized actor after required artifacts and adapter results are generated and
validated. One transaction changes the active-release pointer and retains the
source candidate, release digest, artifact manifest, actor, approval,
publication time, superseded release, audit, domain event, and outbox evidence.
Preparation failure leaves the previous release wholly active.

The timetable editor may support pointer placement, but every move, resize,
grouping, recurrence, and warning override has an equivalent keyboard and
explicit-form command. Hard authorization, consent, capacity, availability,
physical occupancy, and safety constraints cannot be overridden. Warnings
require an inspectable reason.

### Integrate Programme staffing through Workforce-owned Shift commands

The profile deliberately adopts the complete current Workforce journey; it is
not a hidden partial Workforce module. Programme staffing demand enters
Workforce through an explicit, idempotent adapter into documented ShiftDemand
commands. Scheduling may consume only a minimized, versioned coverage query.

Programme movement may update linked draft demand. It may never silently
rewrite or relock open or locked `ShiftDemand`, or reconfirm or remove a
claimed or confirmed `ShiftCommitment`. A later change must preview affected
commitments and use an explicit recovery, replacement, or successor workflow
while retaining the original evidence.

Position-assignment Participation evidence depends on the exact profile
manifest, not on a hard-coded assumption that `workforce_only@1` is the only
bounded profile. `full_convention@1` continues to require its configured
Participation evidence. Both `workforce_only@1` and
`programme_operations@1` exclude Participation, create or touch no
Participation evidence during assignment approval or ending, and require the
assignment Participation-capacity pointer to remain null. The opposite shape
is an integrity conflict requiring stopped writes and fix-forward or whole-
database recovery, never manufactured or discarded evidence.

### Bound the first on-site outcome and preserve issue 24

Version one covers approved Programme timing, confirmed or locked Shift
commitments, role-specific now/next and run sheets, release change impact,
acknowledgement, a version-stamped printable pack, and a last-published
read-only degraded view. Every projection identifies its release version,
source age, field ceiling, and unavailable dependency.

Issue [#24](https://github.com/martonpornoi/maru/issues/24) remains the owner of
check-in, lateness, absence, Shift actual time, correction and dispute, and Shift
handover. This decision does not add payroll, performance scoring,
geolocation, biometric attendance, surveillance, automatic discipline, or a
life-safety workflow.

### Make coexistence, exit, and recovery explicit

Incumbent Registration, payment, attendance, broad Communications, Logistics,
and attendee systems remain authoritative. Imports use mapping, validation,
duplicate policy, provenance, preview, and reversible staging before current
domain commands. They do not fabricate reviews, decisions, claims, or
confirmations.

Permission-controlled continuity export includes profile configuration,
proposals, review and decision evidence, Programme items, readiness,
candidates, releases, artifacts, Shift links, schemas, stable identifiers, and
an audit manifest subject to field-level retention. Public, host, volunteer,
room, daily, and department print outputs derive from one release.

There is no destructive self-service uninstall. Stop-use prevents new work and
access while retaining required evidence. Profile expansion requires a new
reviewed manifest and impact preview; it is never a mutable checkbox. Runtime
migrations must be additive, preserve existing profile meaning, prove exact
database/runtime-role readiness, and fence downgrade once durable Programme
Operations evidence exists. Recovery fixes forward or restores one mutually
consistent database and its release artifacts.

## Consequences

- Programme Operations is an honest composite departmental workflow rather
  than a supposedly narrow profile with hidden Workforce and Venue
  dependencies.
- Hosts and volunteers can receive purpose-specific timetables without becoming
  attendees.
- One released schedule replaces independent Programme publication from Venue
  bookings while preserving Venue physical authority.
- Programme changes cannot silently rewrite volunteer commitments.
- Exact profile-version manifests add catalog and migration discipline but
  prevent future capabilities from widening a bounded deployment accidentally.
- The contract is not runtime behavior. The profile remains unavailable until
  its implementation children, continuity package, integrated synthetic
  acceptance, and protected merge gates complete.

## Alternatives considered

### Retain `programme_only@1` and hide Workforce

Rejected because Department ownership, volunteer coverage, personal Shifts,
and the requested on-site journey would remain hidden dependencies or separate
manual systems.

### Extract Departments into a new neutral module first

Rejected for this profile because the complete current Workforce journey is a
deliberate dependency. A documented Department query boundary is still
required; new cross-module private-model imports are not accepted.

### Permit every capability in an adopted namespace

Rejected because a later catalog addition could silently widen an immutable
profile version and operator authority.

### Give Programme and VenueBooking independent publication

Rejected because public, host, room, calendar, signage, and print audiences
could receive contradictory timing.

### Edit claimed or locked Shifts when a Programme occurrence moves

Rejected because it would rewrite what a volunteer and organizer separately
accepted and destroy truthful coverage history.

### Require attendee Participation for personal schedules

Rejected because hosting and volunteering are independent purposes and the
profile explicitly excludes attendee Participation.

### Include check-in and Shift actual time in this contract

Rejected because issue #24 must first settle authority, privacy, offline,
correction, dispute, retention, and handover semantics.

## Requirements affected

- **EVT-006 and EVT-007:** Profile meaning is exact by code and version, and
  Programme Operations has a declared composite boundary.
- **PRG-001 through PRG-008:** Applications evidence advances through one typed
  transition into Programme-owned readiness and public renditions.
- **SCH-001 through SCH-012:** Scheduling owns accessible candidates, conflict
  evidence, atomic releases, and purpose-bounded projections.
- **HR-009 and HR-013 through HR-015:** Workforce remains authoritative for
  staffing and applies Participation evidence from the exact profile manifest.
- **OPS-001, OPS-002, OPS-005, and OPS-009:** Version one supplies a bounded
  Programme operating picture and continuity view. OPS-006 and issue #24's
  attendance, Shift actual-time, dispute, and handover behavior remain excluded
  dependencies rather than satisfied outcomes.
- **NFR-013:** Composite adoption is deliberate, pinned, recoverable, and free
  of unrelated records, authority, notifications, or hidden dependencies.
