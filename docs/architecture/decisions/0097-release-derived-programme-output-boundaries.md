# ADR 0097: Release-derived Programme output boundaries

- Status: Accepted
- Date: 2026-09-12
- Issue: [#99](https://github.com/martonpornoi/maru/issues/99)

## Context

ADR 0096 supplies checked immutable release references and governing native
invalidation. Its audited planner/history query is neither public admission nor
an enduring permission token. Latest Programme copy, private day labels, host
relationships and independently published Venue bookings cannot become public
content just because they are available to a planner.

## Decision

Add a distinct, exact-profile `scheduling.public-release-output@1` adapter. No
existing profile pins it and no production route is mounted by this work.
Public admission needs no account, planner grant or attendee Participation. It
does need the exact edition's adapter and current, complete checked active
release. Anonymous reads collect no visitor activity or synthetic audit actor.

Scheduling supplies a bounded, content-free owner reference query for that
active release only. Programme and Venues independently resolve this reference
when supplying public fields; caller-provided object identifiers, a manifest,
an audience string or an earlier projection do not grant disclosure authority.
The composite query checks the same complete reference before and after owner
reads. Canonical shared parent ordering protects publication/profile changes;
native release dependency checks still govern disclosure and physical safety.
Missing, incomplete, oversized or moving evidence fails closed, never as a
partial or cached last-good timetable. Absent, withdrawn and invalidated states
contain no schedule rows.

Programme supplies only the **exact selected immutable rendition's** reviewed
title, summary and content note, provided that rendition is not withdrawn.
A newer rendition does not silently replace the released choice. Host names,
invitations, contacts, working copy, review rationale and delivery notes are not
public fields. Withdrawal never falls back to an older rendition; this also
applies to the existing host-self latest-reviewed-copy view.

Scheduling supplies stable occurrence and service-day identities, exact approved
effective intervals and the immutable service-day window. Public day headings
use dates in the Events-owned IANA zone, not private planning labels. Venues
supplies only the selected room's current wayfinding names with explicit owner
versions. These names are current labels, not a claim that an old release
snapshotted them. Venue contacts, restrictions, staffing and layout documents
are not part of this public contract. Venue publication is never consulted as
an alternative Programme release.

Personal hosting and accepted Workforce work remain independent purpose-bound
layers, without Participation. Operator delivery layers require their owner's
field authority and explicit source/version meaning; they do not become public
by augmenting a public dictionary. No personal or operational layer may edit,
cancel or silently relocate accepted work. Detailed layer contracts and their
tests are required before those adapters are exposed.

Personal hosting uses a separate non-persistable, exact-self
`scheduling.view_host_self` capability with only `own_host_schedule` fields;
no existing profile pins it. Scheduling additionally asks Programme to prove
the person's own retained purpose and exact invitation. Only confirmed purposes
can select presence from the active checked release. No confirmed purpose
means no release lookup or release-existence disclosure, not an assertion that
the edition has no published timetable. Pending and ended purposes remain
explicit own history. Approved host presence and the surrounding three-phase
placement envelope are distinct; a host is not silently assigned every phase.
This does not require anonymous public admission or a planner grant. Owner
reauthorization, source rechecks and sensitive-read audit remain mandatory.

The private compositor independently identifies adopted hosting and Workforce
layers, then requires each owner's fresh authority. An unadopted layer is `None`;
an empty adopted layer is an empty collection. An adopted but denied, incomplete
or moving layer fails closed rather than silently disappearing. Workforce-only
performs no Programme/release lookup. Shared parents and the exact person fence
the owner reads; final owner and adoption rechecks precede materialization.

Private JSON keeps all retained host/work states and explicit source versions.
The shared My Maru rendered/print surface consumes that same private projection.
An Events-owned minimized current edition label/version is read only after real
own hosting/work records justify the context, under canonical parents and final
owner rechecks. Empty scopes do not discover edition names; no foreign private
model is imported into the timetable transport. Scope labels grant no authority.
Personal calendar events use approved own host presence, not every surrounding
placement phase. Shift claims are tentative, confirmed work confirmed, removals
cancelled and completed work explicitly historical; only operative claims and
confirmations block calendar time. These states describe retained scheduled
work, not attendance. A current Shift demand location stays labelled in its
description, not in a `LOCATION` property that might imply immutable accepted
location or silently relocate work. Withdrawn/invalidated hosting withholds the
combined calendar import; JSON and rendered output can still show the known
host state and unchanged retained Shifts. Stable IDs and cancellation status
cannot guarantee that a calendar client updates or erases an earlier import.

Transport adapters consume the same freshly authorized audience projection.
Typed/JSON, calendar and printable views must retain release identity, truthful
source age, complete-state meaning, deterministic ordering, bounded output and
format-specific escaping. A pure serializer is not an access boundary or a
cache permission. Ordinary downloads/print cannot promise remote erasure or
offline freshness. Continuity packs, change delivery/acknowledgement, logical
recovery (#97) and human acceptance (#92) remain separate gates under #48.

## Consequences

- Repeated checked-reference reads cost more than serializing retained bytes,
  but keep owner boundaries explicit and prevent stale-reference disclosure.
- Existing public Venue output and attendee-specific discovery are not reused
  for Programme, preserving progressive modular adoption.
- No schema or release-history rewrite is required for the public reference
  boundary. Later output layers cannot silently reinterpret existing evidence.
- Dormant synthetic fixtures may exercise the contract without activating it.
  Automated browser evidence does not satisfy representative-human acceptance.

## Alternatives considered

- Inject an unrestricted planner authorizer: rejected; anonymous publication is
  a different purpose, not an organizer permission bypass.
- Render the newest copy or a retained artifact directly: rejected; neither
  preserves exact released selection plus current withdrawal consequences.
- Publish private day labels and all host details: rejected; no such public
  review or identity-publication consent is present in the owning contracts.
- Treat exported files as revocable offline packs: rejected; freshness,
  acknowledgement and stop-use need their own governed contracts.

## Requirements affected

SCH-004, SCH-005, SCH-006, SCH-008, SCH-009, SCH-010, SCH-012, PRG-008,
HR-014, HR-015, AUD-001, NFR-001, NFR-002, NFR-005, NFR-008, NFR-009,
NFR-013. ADRs 0081, 0087, 0088, 0093 and 0096 remain accepted.
