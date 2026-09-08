# Scheduling module

Status: dormant candidate/conflict and reciprocal physical-reservation kernel;
no Programme timetable editor, approval, release or current-profile activation.
Last updated: 2026-09-07. See [CURRENT](../project/CURRENT.md) for verification
and protected-delivery status; this guide is the owner contract, not a merge claim.

## Ownership and adoption

`maru.scheduling` owns service days, stable occurrences, comparable timetable
candidates, explicit required host presence, conflict evidence and deliberate
reservation intent. [ADR 0088](../architecture/decisions/0088-versioned-scheduling-candidates-and-venue-binding.md)
maps this boundary to SCH-001, SCH-003, SCH-004, SCH-007 through SCH-010,
PRG-008, VEN-001, VEN-002, VEN-008, AUD-001/AUD-003 and NFR-013.

Programme owns item content, readiness, hosting confirmation and deliberately
shared availability. Events owns edition lifecycle, dates and IANA zone.
Venues owns actual physical occupancy and independent physical approval.
Workforce remains the future owner of Shift demand and volunteer commitments.
Scheduling must use those owners' documented services, not their private models.
Cross-owner database integrity deliberately verifies the exact foreign graph;
it is not a user-facing data-access path.

Neither `full_convention@1` nor `workforce_only@1` admits the new capabilities,
adapters or conflict sources. All fifteen Scheduling tables and the new Venue
binding table remain runtime SELECT-only. A schema migration, retained UUID,
platform role or successful isolated test does not activate this workflow.
There is no new HTTP route, API, UI, worker or effect-delivery handler. No
Registration, Participation, payment or attendance record is created.

## Owned state and commands

Every command uses `SchedulingCommandRequest`: exact person, organization,
edition, UUID retry key, correlation, normalized reason and bounded channel.
Current versions are explicit optimistic preconditions. One edition control
serializes commands and receipts; an exact retry returns the retained result,
while reusing its key with different intent fails. Authorization and source
eligibility are checked before work and under the final transaction. Current
verified people are required; an ORM writer context is not database authority.

- `day_commands`: create, revise and retire a service day. Its immutable revision
  retains label, UTC window, minute precision and Events version. Days fit the
  current edition, may cross local midnight, and cannot overlap. Adjacent days
  remain distinct. Precision divides an hour and anchors to the day's start.
- `occurrence_commands`: create, revise and retire a stable exact Programme-item
  occurrence, with explicit group key and sequence. Retirement first requires
  cancellation of its active physical hold; it never deletes retained plans.
- `candidate_commands`: create, copy, restore, archive or remove a placement.
  Each revision is a complete immutable manifest with count and digest. Copy
  preserves the exact source revision; restore creates a successor. Archive is
  terminal. Other alternatives and historical manifests never change.
- `placement_commands.set_scheduling_placement`: place, move or resize by adding
  an immutable placement and successor manifest. It identifies exact day and
  occurrence revisions, selected room, requested capacity, four ordered room
  times and explicitly selected host presence intervals. Invalid structure or
  foreign scope fails; a structurally valid draft may still have conflicts.
- `evaluation_commands`: persist a current candidate evaluation or explicitly
  acknowledge one exact current warning. Neither operation approves a timetable.
- `reservation_commands.change_scheduling_reservation`: replace or cancel one
  physical reservation, through the independent Venue owner in the same
  transaction. Draft placement edits never implicitly reserve rooms.

The existing four writable edition states are Draft, Preparing, Ready and Live;
Closing, Archived, Cancelled and unknown states deny planning changes. This is
an Events-owned Scheduling-write consequence, not permission to reopen
Programme private content or invitations on-site.

Bounds are explicit: 32 active/128 retained days, 2,000 occurrences, 100
candidates, 1,000 ordinary metadata revisions plus final retirement, 10,000
candidate revisions plus final archive, 100 required-host selections per
placement, 10,000 findings and one million conflict comparisons. Bounded
overflow is unavailable or a refused command, never a truncated passing report.

## Current dependencies and explainable conflicts

The exact source descriptors are:

- `scheduling.service-day-and-placement@1`: current edition, day and occurrence
  versions, grid and time bounds;
- `programme.item-and-host-availability@1`: current item lifecycle and hosting
  applicability, selected confirmed current people, and only their currently
  deliberately shared per-item availability or preferences;
- `venues.physical-scheduling-dependencies@1`: active selected rooms and physical
  members, configured/fire capacity, current hard windows and live occupancy.

Programme's `load_programme_scheduling_dependencies` independently authorizes
the exact edition and restricted fields. Venue's
`load_venue_scheduling_dependencies` independently authorizes every exact space
for `physical_dependencies`. Both are audited and bounded. Current host periods
are consumed in memory, not copied into Scheduling history. Draft, withdrawn,
unconfirmed or unavailable host information does not mean that someone is free.
Empty host selection does not establish that hosting is unnecessary: Programme
must explicitly identify that concern as not applicable.

Required person presence is distinct from preparation/effective/teardown room
occupancy. The ordinary presence is effective delivery; preparation and
teardown do not silently require every host. Same-person contention uses a
Programme-provided edition-bounded conflict key. Room contention uses ADR 0053's
two-clique rule across every physical member, including room combinations.
Only the permitted preceding teardown/following preparation overlap becomes
an inspectable turnover warning.

Same-organization busy occupancy from another edition is clipped to this
edition's envelope. No foreign edition UUID, booking UUID, title or private
content is disclosed. The opaque physical source key is the first 128 bits of
SHA-256 over ASCII `venue-physical-conflict@1:<edition_uuid>:<booking_uuid>`,
formatted as a UUID. It is a scoped correlation key, not a generated identity,
capability or consent token. PostgreSQL verifies the same derivation without
an extension. Independent Venue approval advances the Booking version but
does not rewrite its still-valid version-one occupancy.

Persisted evaluation evidence has a closed three-source JSON schema: versions,
current membership/status, manifest digest, opaque busy sources and exact
binding status. It contains no calendars, person keys, host contact, private
Programme copy or proposal/review material. `is_complete` means those declared
sources completed, not that the candidate is approved or conflict-free.
`not_evaluated` explicitly lists staffing, rest, accessibility-fit and release
readiness; equipment/travel checks also remain future declared adapters.

Findings distinguish blockers, warnings and unavailable checks. Warning
acknowledgement requires explicit rationale and the current complete source
digest and finding fingerprint. Any relevant dependency change requires a
fresh evaluation; the old acknowledgement stays historical. PostgreSQL rejects
stale acknowledgement even if application freshness validation regresses.

## Reciprocal Venue reservation

Scheduling reserves a command receipt and immutable intent identity before
calling `venues.scheduling_reservations.apply_scheduling_reservation`. Venue
reloads live exact proof through
`scheduling.reservation_sources.resolve_scheduling_reservation_source`; the
receipt must be active in its original owner transaction. Reusing a retained
intent outside that command is not authority.

Both `scheduling.venue-reservation@1` and `venues.scheduling-reservation@1` must
be admitted, as must Scheduling reservation authority and independent exact
Venue-space management. New reservations require current draft candidate,
occurrence/day revisions, grid, capacity, physical lifecycle and hard availability.
Cancellation can reference the retained historical placement even after the
candidate or day has changed; it still requires the exact current Booking version.

Venue creates an unpublished draft `programme` Booking named only
`Programme reservation`, physical occupancy, immutable source binding and its
own history/receipt/audit/event/outbox. Only the new explicitly Venue-visible
reservation reason crosses the boundary; original private placement rationale
and item text do not. A replacement cancels the previous hold and creates the
new hold atomically. At most one active hold exists per occurrence. Any late
failure restores the prior occupancy and both owners' evidence.

The original placement author, reservation creator and last physical editor
cannot independently approve the hold. Approval requires another current
verified person and does not publish Programme timing. Generic Venue reschedule
and publication are denied for linked bookings. Generic cancellation remains
available and retains the binding; subsequent evaluations expose the missing
active reservation. Public/My Maru Venue schedule queries exclude linked rows.
Historical placement authorship survives account inactivity or loss of
verification: another current authorized planner can reserve the retained
placement. The original identity remains excluded from approval after account
recovery; the current reserver and approver must still be verified active people.
The future release child must coordinate activation or invalidation atomically;
this kernel has no released timetable to invalidate.

## Integrity, observation and remaining work

Commands lock the exact edition, canonical people, owner records and complete
sorted physical-member union before selected rooms. Ordinary Venue writers
share the physical lock order, including replacement across rooms. PostgreSQL
independently enforces closed evidence, scope, contiguous versions, immutable
manifests, same-command child evidence, reciprocal holds and exact effects.

`scheduling.planning.changed.v1` retains only the closed operation code in its
payload, scoped to the edition/control version with actor and correlation.
Operational diagnosis uses denied/unavailable/version-conflict categories,
receipt/correlation identities and readiness status. Do not log source JSON,
private rationale, host periods or private owner records as debugging payloads.

The [migration/recovery runbook](../operations/scheduling-migration-and-recovery.md)
describes exact schema/readiness, runtime ACLs and populated contraction fences.
An accessible editor, staffing adapter, independent Programme approval, atomic
release, role-specific outputs, on-site continuity, guided activation and
integrated acceptance remain separate mandatory children of #48.
