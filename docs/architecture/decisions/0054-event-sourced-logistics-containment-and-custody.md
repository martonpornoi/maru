# ADR 0054: Event-sourced logistics containment and custody

- Status: Accepted
- Date: 2026-08-09
- Clarifies: ADRs 0003, 0004, and 0005
- Requirements: LOG-001 through LOG-008, ACC-003, VEN-002, PRI-001,
  AUD-001, AUD-003, and NFR-002

## Context

Logistics teams need to know what is in a storage container or box, what a
truck should receive, who currently holds an item or physical key, and when a
rented asset must return. Individuals and external businesses may offer
equipment without becoming convention staff or Maru tenants. Freely editable
"current location" fields would erase custody history, while treating people,
postal addresses, or vehicles as interchangeable containers would invite
unsafe personal-location tracking and invalid physical graphs.

## Decision

`logistics` is an organization-owned bounded context with optional exact
edition allocation. External owners, providers, rental businesses, restricted
purpose/retention addresses, and authenticated person-owned equipment offers
are distinct records. An offer remains pending and person-owned until an
authorized Logistics review accepts or rejects it. Acceptance may create
serialized assets or bulk lots and loan/rental/return obligations, but it does
not grant the offerer convention or software authority.

Physical whereabouts use typed nodes: site, area, rack, container, box,
vehicle, loading zone, staging area, or selected venue room. Containment is
organization-scoped, type-checked, and acyclic. A person is a custodian, never
a container; a restricted address describes an authorized place rather than
the person's live location. Physical keys and their time-bounded keyholder
responsibilities are tracked separately from authorization roles, so holding a
key never grants access in Maru.

Assets, stock lots, kits, manifest lines, ownership/provider agreements,
return deadlines, condition, and custody use closed typed records. Current
location, containment, quantity, condition, and custody are projections of an
append-only event ledger containing receive, pack, unpack, move, load, unload,
handover, count, condition, damage, and return actions. Commands lock and
revalidate the exact organization, subjects, source, destination, manifest,
sequence, and current projection before appending an event and replacing only
the derived current state. Count, condition, damage, source, or manifest
mismatches create owned discrepancies rather than silent corrections.

Reusable kits, packing lists, box counts, truck manifests, receiving views,
labels/QR references, and return checklists derive from current asset data.
Offline scanning uses bounded, expiring batches and idempotent ordered
operations. Reconciliation rejects or queues stale, foreign, over-limit, or
ambiguous operations for review; an offline client is never permitted to
rewrite history. Maru records declared operational movements and handovers,
not continuous GPS or volunteer location telemetry.

Private provider, pickup, return, and site-contact details live only in a
purpose- and retention-bound restricted-address record, never on the reusable
party or ordinary asset projection. Exact authorized reads are separately
audited. A bounded disposal command redacts expired contact/address values only
after the currently modeled active offer, agreement, and return horizons clear,
while preserving the minimized event sequence needed to explain physical state.
Incident, discrepancy, and legal-hold retention extensions remain a required
production follow-up; until those sources exist, operators must use a retention
horizon that already covers them.

This decision supplies the architecture for LOG-001 through LOG-008; it does
not declare every workflow in those broad requirements complete. The bounded
first slice directly covers asset identity, custody/return/damage evidence,
kits/manifests, containment, movement projection, person-owned offers, and
offline reconciliation. Department demand/reservation planning, optimized
drivers/routes, supplier invoice linkage, low-stock/wastage policy, and the
complete loss/disposal workflow remain later explicit commands and adapters.

## Consequences

- Stage Tech and Logistics can reconcile expected boxes and contents against
  what is actually received on site.
- Nested boxes, containers, vehicles, staging areas, and venue rooms remain
  expressive without cycles or cross-organization containment.
- Owner, provider, renter, custodian, driver, keyholder, and software actor
  remain separate responsibilities.
- Every movement and discrepancy retains actor/time evidence, while ordinary
  people can offer equipment through a bounded personal workflow.
- Route optimization, live fleet telemetry, procurement invoices, and
  continuous person tracking are outside this boundary.
- Physical keys, keyholder responsibility, and software authority remain
  distinct: possession of a key never grants a Maru capability or role.

## Alternatives considered

### Store only an editable current location and owner

Rejected. It cannot explain loss, damage, handover, late return, quantity
variance, or which manifest was followed.

### Model people, addresses, vehicles, and boxes as one generic location

Rejected. It confuses custody with containment and makes personal-location
tracking an accidental platform feature.

### Accept offline scans as authoritative final state

Rejected. A stale or duplicated device can create cycles, negative stock, or
false custody unless operations are bounded and reconciled against current
server state.
