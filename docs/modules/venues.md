# Venues module

Status: venue catalog, edition selection, operational space booking, and
independent public schedule projection implemented; Programme-linked
publication reconciliation is contract-only
Last updated: 2026-08-31

## Purpose and boundary

`maru.venues` owns organizer-reusable hotel and venue facts and the explicit
decision to use them in an event edition. A property is not a Maru tenant. It
belongs to the organizing `Organization`; edition selections additionally
belong to one exact edition and responsible Department.

This is the bounded VEN-001, VEN-002, VEN-003, VEN-008, SCH-004, SCH-006,
SCH-009, SCH-010, and SAF-008 slice. It is not a programme-authoring system,
guest-room assignment service, hospitality CRM, logistics ledger, or statutory
property/contract system. Programme records can later reference venue booking
IDs through a documented adapter without importing venue-private writers.

ADR 0081 partially supersedes ADR 0053 only for a future Programme-linked
booking. Venue approval remains the authoritative prerequisite for safe use of
physical space, capacity, availability, and occupancy, but such a booking must
not independently publish a second public Programme schedule. Scheduling will
own the one approved Programme release and its public, personal, department,
venue, calendar, signage, and print projections. Unrelated operational Venue
bookings retain the existing independent approval/publication lifecycle. This
reconciliation is accepted architecture, not current runtime behavior.

## Reusable catalog and edition selection

- `VenueProperty` represents a hotel, venue, or mixed property with legal and
  provider facts, restricted contacts, public copy, location, and lifecycle.
- `VenueSite`, `VenueBuilding`, and `VenueSpace` form the physical hierarchy.
  Spaces record public/accessibility facts separately from internal,
  equipment, and known-barrier facts.
- `VenueSpaceConfiguration` versions seated, standing, table, and fire
  capacities plus access and equipment facts.
- `VenueSpaceCombination` and immutable member rows describe mergeable rooms.
  Edition selection expands a combination into its physical members so
  conflicts are enforced against every source room.
- `VenuePropertyMedia` and `VenueLayoutVersion` retain owner/license/source and
  checksum provenance. Public, internal, and security layouts are distinct.
  A submitter cannot approve their own media or layout. A public layout needs
  an explicitly approved public-safe rendition reference.
- `EditionVenueSelection` selects a reusable property for one edition and owns
  local public copy, contact, opening restrictions, and responsible Department.
- `EditionSpaceSelection` selects a physical room or combination and snapshots
  its local name and capacity. Append-only availability versions are hard
  constraints; placement outside the current window fails.

Accommodation is deliberately a separate bounded catalog.
`AccommodationRoomType` records room-type occupancy/accessibility/provider
facts, and `AccommodationNightInventory` records only a night, room count,
release time, and provider reference. It stores no guest, account,
registration, contact, or room-assignment data. Fair allocation, room groups,
and guest assignments remain future VEN-004 and VEN-005 work.

## Operational bookings and conflict rule

`VenueBooking` supports programme, panel, event, department, storage, catering,
rehearsal, and private uses. Every booking has ordered setup start, effective
start, effective end, and teardown end. Capacity is checked against both the
selected configuration mode and fire ceiling. The full setup-to-teardown
envelope must fit one current hard-availability window.

Physical occupancy is enforced in PostgreSQL, not by a race-prone read before
write. Each physical member receives two exclusion-backed ranges:

- setup through effective end in the `setup_effective` conflict group; and
- effective start through teardown end in the `effective_teardown` group.

Ranges in the same group cannot overlap. This forms the SCH-009 two-clique
rule: effective delivery conflicts with every occupying phase, setup conflicts
with setup, and teardown conflicts with teardown, while only a preceding
teardown and following setup may overlap as a visible turnover window. Moving
or cancelling a booking only deactivates old occupancy rows; it never rewrites
them.

Booking history is append-only and records actor, reason, old/new envelope,
review/publication/lifecycle transitions, and booking version. Rescheduling
invalidates prior approval and publication. The creator or last scheduler
cannot approve the booking, and the approver cannot publish it. Private-use
bookings cannot be published.

## Public and staff projections

The public and authenticated My Maru projections read only active, approved,
published bookings in active edition spaces and properties. Their schema
contains the effective interval, public title/description, public venue and
space names, attendee access information, and an optional currently approved
public layout rendition. Setup/teardown times, internal titles, provider
references, expected attendance, contacts, availability restrictions,
internal layouts, security floor plans, and review actors are structurally
absent. Both projections require the exact edition manifest to adopt Venues and
pin `venues.attendee-schedule@1`; My Maru also requires an attendee relation
admitted through `participation.attendee@1`. Retained booking or Participation
rows under another exact profile disclose neither the schedule nor its edition
label.

Staff property-directory reads expose restricted provider/contact facts only
after organization-scoped authorization and append a purpose-attributed audit.
Exact-space operational schedule reads include setup/effective/teardown layers
only after typed-resource authorization and are also audited.

## Authorization and evidence

The capability catalog provides organization-scoped property and accommodation
management, edition-scoped workspace/selection, and exact-resource
view/manage/publish capabilities. `EditionSpaceSelection` resolves through a
deterministic `venue.edition_space` binding to its responsible Department. A
platform administrator receives no automatic convention-subject authority;
an explicit exact grant is required.

Commands are closed, transactional, optimistic-versioned, and scope-bound
idempotent. Privileged mutations append minimized audit, domain-event, and
outbox evidence in the same transaction. Event payloads contain only action,
record type, and record UUID; they never contain provider contacts, layout
sources, operational times, or private copy.

## Interfaces

The shared authenticated shell exposes:

- the selected-edition venue workspace, including property and physical-space
  selection;
- a reusable-property detail journey for complete profile changes, physical
  paths, room combinations, governed media/layout review, accommodation room
  types, and room-night inventory;
- an exact-space operational journey for edition-local hard availability,
  bookings, rescheduling, independent approval, separate publication or
  withdrawal, cancellation, and immutable history; and
- an always-resolved `/my/schedule/` index plus exact-edition My Maru schedule
  pages using the same minimized projection as the public API.

Browser forms are closed to unknown and duplicate transport values. Command
UUIDs and control integers use canonical spellings. `datetime-local` values
are interpreted only in the persisted edition IANA time zone and reject both
nonexistent daylight-saving gaps and ambiguous folds. Every POST authorizes
the exact organization, edition, or typed space before form construction,
validation, or object-choice lookup; command services repeat the tenant and
object authorization at the write boundary. Every edition-keyed staff route
also requires the exact adoption-profile code and version to include Venues
before it reads reusable property labels, constructs forms, or invokes an
organization-scoped property mutation. A retained URL for an edition that no
longer adopts Venues therefore returns not found even when the actor still has
an organization-wide Venue grant.

The current My schedule index first derives the signed-in person's current
confirmed, active, or completed adapter-admitted Participation scopes. It
intersects only those
opaque edition IDs with published schedule scopes, bounds distinct eligible
editions in most-recent-edition order, and loads labels only afterward. A
foreign published convention cannot disclose its name or consume the bounded
result prefix. Withdrawal immediately removes a booking from the public and My
Maru projections. ADR 0081 requires a successor purpose-scoped host and
volunteer eligibility query so Programme Operations can project a personal
timetable without manufacturing Participation; that query is not implemented
here.

Navigation shows the venue workspace only after `venues.view_workspace` is
reauthorized for the selected edition. Strict versioned APIs cover public and
My Maru schedule reads, property list/create, venue and space selection, hard
availability replacement, exact-space operational reads, and booking
create/reschedule/approve/publish/withdraw/cancel commands. Staff APIs
authorize before parsing, reject unknown fields and query parameters, and
require a canonical `Idempotency-Key` UUID for mutations.

All authenticated staff and My Maru HTML and API responses use a private,
no-store boundary, including API error responses. The explicitly public,
minimized schedule API remains a separate cacheable surface.

## Data handling, recovery, and operations

Migrations `venues.0001` and `venues.0002` create the catalog/schedule schema,
`btree_gist` exclusion support, immutable-scope and append-only guards, and a
deferred exact-binding requirement. `authorization.0014` adds venue capability
minimum scopes, the resource kind, database binding validation, and a
downgrade fence. A destructive authorization downgrade is refused after venue
capabilities or bindings are in durable use.

Property retirement, edition-selection retirement, booking cancellation, and
publication withdrawal are the supported non-destructive controls. Operators
must monitor denied decisions, version/availability/capacity/overlap conflicts,
outbox delivery, and readiness fingerprints without logging restricted
fields. Backup/restore validation must include the `btree_gist` extension,
exclusion constraint, append-only triggers, and typed binding functions.

Remaining work includes programme ownership/adapters, schedule-version
comparison, person/equipment/qualification conflicts, service-day layers,
calendar/signage/print exports, accommodation blocks/assignment/allocation,
travel, and hospitality fulfilment. Until the ADR 0081 adapter and release
owner exist, Venue publication remains independent and must not be presented as
the accepted Programme timetable.
