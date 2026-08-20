# Logistics module

Status: bounded storage, offers, manifests, and custody slice accepted in the
canonical current tree; full LOG portfolio remains partial and production is
gated
Last updated: 2026-08-11

## Purpose and boundary

`maru.logistics` owns organizer equipment, bulk stock, physical storage,
equipment offers, operational custody, manifests, and return obligations. A
reusable provider or owner is an organizer-owned beneficiary/business profile,
not a Maru tenant. A person, postal address, or software principal is never a
container. The module records declared equipment movements and custody; it
does not collect GPS data or continuously track a person's location.

This slice materially implements LOG-005 and LOG-008 and bounded parts of
LOG-001, LOG-002, LOG-004, LOG-006, and LOG-007. It does not yet complete:

- LOG-001 maintenance scheduling, maintenance history, or governed value-class
  workflow beyond the stored identity/value-class facts;
- LOG-002 loss and asset/stock/key disposal lifecycle commands;
- LOG-003 department demand, priority, and reservation planning;
- LOG-004 driver, route, and delivery planning;
- LOG-006 supplier acceptance criteria and invoice linkage; or
- LOG-007 low-stock signals and governed wastage semantics.

Those omissions are explicit future work, not alternate uses of editable
current-state fields.

## Parties, contacts, and authenticated offers

`LogisticsParty` contains only reusable legal/public identity, role, provider
reference, and public website. It has closed owner, provider, rental-business,
borrower, and mixed roles; commands reject using a declared borrower as an
owner or provider. Private recipient names, email addresses, phone numbers,
postal addresses, and access instructions live only in
`RestrictedLogisticsAddress`, with an explicit purpose, optional exact edition,
retention horizon, and active/disposed lifecycle.

An authenticated person may submit an `EquipmentOffer` only while an edition
is Preparing, Ready, or Live. The offer stays self-owned and Pending until
Logistics accepts or rejects it; submitting an offer grants no workforce or
software authority. The pickup contact retention horizon must cover both
availability and any requested return. Offer items and ownership statements
are retained as immutable operational/contract evidence until the organizer's
equipment-offer retention policy closes the relationship; contact values are
disposed independently as soon as their lawful operational horizon ends.

External provider/business identity is retained while the organizer has an
active supplier, owner, rental, audit, or legal-evidence relationship. It does
not duplicate private contacts. The organizer is the retention owner and must
close that relationship under its documented supplier/evidence policy. A
governed Party-retirement command is not implemented in this slice, so Party
retirement and later relationship-retention closure remain explicit future
work. Custody history remains minimized and append-only after contact disposal.

## Physical graph, assets, keys, and agreements

`LogisticsNode` has closed types for storage sites, areas, racks, containers,
boxes, vehicles, loading zones, staging areas, and selected venue rooms. Typed
containment edges are organization-scoped, edition-compatible, and acyclic.
Boxes may nest; box counts and contents are derived from the graph and current
manifest data. A global node may reference only a global storage address. A
venue-room node must reference an active `EditionSpaceSelection` from the same
organization and exact edition.

Serialized `Asset` records and bulk `StockLot` records keep identity,
ownership, edition allocation, and catalog facts. `PhysicalKey` is a separate
tracked subject. Time-bounded `KeyholderResponsibility` records are physical
facts only and never grant application access. PostgreSQL exclusion
constraints prevent overlapping responsibility for one physical key; multiple
copies are separate key rows.

`AssetAgreement` records loan/rental provider, borrower, interval, return due,
and an optional return address. One serialized asset, physical key, node, or
whole unsplit stock lot cannot have overlapping agreements; adjacent half-open
intervals are valid. A return address must remain lawful through the return
horizon. Provider/borrower accounts must be exact eligible convention people,
while external parties must have a compatible declared role.

## Append-only custody and manifests

Current location, containment, custody, quantity, and condition are never
ordinary editable fields. Receive, pack, unpack, move, load, unload, handover,
count, condition, damage, and return commands append `LogisticsEvent` rows and
replace only the derived `LogisticsCurrentState`. Commands lock and revalidate
the exact tenant, edition allocation, subject sequence, current/source node,
destination, custodian, and manifest. Handover requires one person or party
recipient; return requires a destination or recipient. Count/state conflicts
create discrepancies rather than silent corrections.

Reusable kits, labels/QR digests, packing lists, manifest lines, box counts,
Stage Tech receiving views, and return projections derive from current
catalog/custody facts. Non-inbound stock manifest lines represent a whole lot
because split-lot semantics are not implemented; sealing therefore requires
the line quantity to match current quantity on hand. Offline scan batches are
bounded, expiring, ordered, idempotent, and reconciled against server state.
`Completed` freezes a manifest's definition and route, but it does not assert
that every late physical reconciliation has already happened. A canonical
one-time manifested event may therefore be appended after completion; the
per-line/event-type uniqueness fence prevents repeating the same planned
traversal evidence.

## Authorization and interfaces

Capabilities are exact to organization, edition, or a typed
`logistics.manifest` resource binding. Self-offer authority is non-persistable
and relationship-derived. Organization-global and edition-allocated catalog
commands deliberately authorize at different exact targets. Platform
administrator identity alone is rejected at the Logistics boundary and is not
convention authority.

The shared shell provides:

- `/my/equipment-offers/`, which discovers only currently open authorized
  editions or editions in which the person already owns an offer;
- exact-edition self offer pages with safe empty states;
- an edition Logistics workspace whose currently accepted browser projection
  is read-only and exposes no mutation controls;
- exact manifest detail/state/line workflows;
- a Stage Tech receiving projection; and
- purpose-coded, audited restricted-contact reads through short-lived opaque
  results.

The stable HTTP command and query contracts are documented in the
[Logistics API](logistics-api.md).

Browser and API adapters reject unknown fields, duplicate single-value fields,
UUID aliases, alternate integer spellings, and ambiguous/nonexistent
edition-local times. Every authenticated Logistics API response and safe error
is private and no-store. Route-scope or exact-object authorization happens
before query/body/header parsing; services repeat authorization after parsing.
Malformed JSON receives one code-owned generic error rather than decoder
exception text. Successful offer submission reverses the exact named
same-origin route rather than redirecting to a request-derived path. The API
and browser call the same idempotent versioned commands.

## Verification and acceptance

The final canonical current-tree repository gate passed all 4,067 tests in
15,558.23 seconds (4:19:18) at 90.78 percent coverage. An authenticated
read-only browser rehearsal also passed for both the edition Logistics
workspace and Stage Tech receiving projection at 1920- and 390-pixel viewport
widths. Each page rendered exactly one `main` landmark and one H1, showed no
horizontal overflow, and exposed no mutation controls to the rehearsed role.

That browser result accepts the bounded read-only projection only. A
mutation-capable Logistics role, keyboard traversal, automated accessibility,
representative recovery, deployment rehearsal, and production approval remain
separate gates. The canonical repository result likewise does not complete the
partial LOG-001/002/003/004/006/007 portfolio.

## Retention, evidence, and recovery

Expired restricted contacts are disposed by a bounded idempotent worker. It
clears person/party links and every contact/address value, retains only minimal
scope/purpose/version evidence, appends a service audit, and publishes the
closed `logistics.record.changed.v1` event. It refuses early disposal while a
live offer or return agreement still depends on the contact horizon. Global
and exact-edition records require separate explicit scheduler invocations.

Privileged commands append audit, domain-event, outbox, and idempotency receipt
evidence in the same transaction. Event payloads contain only action, record
type, and UUID; free-text reasons, contacts, addresses, provider terms, and
manifest contents do not enter generic audit metadata or outbox payloads.

Deployments must preserve PostgreSQL exclusion constraints, append-only and
scope triggers, typed manifest bindings, and the `btree_gist` extension.
Venues migration `0001` owns that shared extension; Logistics migration `0001`
depends on it so clean reverse plans remove Logistics constraints before the
extension owner.
Deletion and direct current-state editing are unsupported recovery paths.
Correct errors through a new corrective event and, where investigation is
required, a new discrepancy. A governed discrepancy-resolution workflow is not
implemented. Use only implemented lifecycle commands or explicitly audited
contact disposal for their respective records.
