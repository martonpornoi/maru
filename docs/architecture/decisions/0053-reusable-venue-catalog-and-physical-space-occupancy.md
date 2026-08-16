# ADR 0053: Reusable venue catalog and physical-space occupancy

- Status: Accepted
- Date: 2026-08-09
- Clarifies: ADRs 0002, 0003, 0004, and 0005
- Requirements: VEN-001 through VEN-003, VEN-008, VEN-009, SAF-008, PRI-001,
  and AUD-001

## Context

Venue facts such as properties, buildings, rooms, combinations, capacities,
and layouts are reusable, but each edition needs local names, restrictions,
availability, and bookings. A displayed combined room can represent several
physical spaces. Checking only the display record permits overlapping real
occupancy, while treating the full setup-to-teardown envelope as one exclusion
range unnecessarily forbids a later setup during an earlier teardown.

## Decision

`venues` owns a reusable property, site, building, space, configuration,
combination, accommodation-inventory, photo, and layout catalog. Media and
public/internal/security layouts are versioned and independently reviewed. An
edition explicitly selects venues and spaces, snapshots the immutable physical
member expansion, and owns versioned hard availability and local restrictions.
The exact edition-space selection is the authorization resource.

A booking stores ordered setup, effective, and teardown intervals. Validation
locks the selected members, checks current hard availability and configured and
fire capacities, and creates occupancy rows for every physical member. Two
same-group exclusion cliques represent setup-through-effective and
effective-through-teardown. Consequently every setup/effective,
effective/effective, and effective/teardown collision is rejected at the
database boundary, while a teardown/setup handoff may overlap. Rescheduling
replaces current occupancy and clears prior approval/publication evidence.

Approval must be independent of the creator or last modifier. Publication must
be performed by another authorized actor, requires a non-private approved
booking and approved public layout, and is independently withdrawable. Public
and My Maru projections contain only approved effective schedule information;
setup/teardown windows, internal and security layouts, accommodation provider
details, and operational notes remain restricted.

## Consequences

- Stable property knowledge can be reused without an edition mutating another
  edition or the source catalog.
- Combined rooms cannot double-book a hidden physical member under concurrent
  commands.
- Operations can plan setup and teardown precisely without exposing those
  intervals to regular attendees.
- Immediate teardown-to-setup turnover remains possible, while every conflict
  involving an event's effective occupancy is rejected transactionally.
- Guest assignments, travel, programme ownership, and hospitality fulfilment
  remain separate bounded workflows.

## Alternatives considered

### Copy all venue facts into every edition

Rejected. It loses reusable provenance and makes corrections inconsistent.

### Check conflicts only in application code

Rejected. Concurrent transactions can both pass an application check and
commit an impossible physical-space schedule.

### Exclude the entire setup-to-teardown envelope

Rejected. It would forbid a safe and operationally common teardown/setup
turnover that does not overlap either event's effective occupancy.
