# Implemented modules

Implemented bounded modules appear here. Each guide states whether its behavior
is mounted, API-only, deployment-gated, or deliberately dormant.

Use [CURRENT](../project/CURRENT.md) for verified delivery and next actions,
the [production ledger](../project/PRODUCTION_CONSOLIDATION.md) for release
readiness, and [checkpoints](../checkpoints/index.md) for historical evidence.
This index is an ownership map, not a claim that every workflow is available.

The current interface uses one `/admin/` shell under
[ADR 0039](../architecture/decisions/0039-unified-admin-shell-and-platform-route-space.md).
Some older module guides also describe preserved interfaces from before that
transition. Follow the owning [page contract](../product/page-contracts/index.md)
and CURRENT for supported entry points and their actual verification scope.

- [`core`](core.md) - platform-neutral runtime primitives
- [`identity`](identity.md) - platform account boundary
- [`organizations`](organizations.md) - tenant, series, membership, and
  accountable representation lifecycle
- [`events`](events.md) - event edition, profile, and authorized lifecycle
- [`participation`](participation.md) - self-scoped relationship and history
- [`authorization`](authorization.md) - scoped capabilities, grants, and policy
- [`audit`](audit.md) - append-only control evidence and integrity batches
- [`effects`](effects.md) - domain events, transactional outbox, and delivery
- [`activity`](activity.md) - bounded value-minimized record history
- [`registration`](registration.md) - configurable forms, products, attendee
  lifecycle, entitlements, and check-in
- [`catalog`](catalog.md) - edition merchandise, charity-support products,
  attendee orders, governed stock, and payment reconciliation
- [`applications`](applications.md) - versioned typed form definitions,
  append-only applications, assigned review queues, target adapters, and dormant
  [exact-seal Programme review and decisions](programme-review.md)
- [`programme`](programme.md) - dormant private items, structurally separated
  information layers, evidence-backed readiness, and reviewed public copy
- [`scheduling`](scheduling.md) - dormant service days, occurrences, immutable
  candidate alternatives, conflict evidence and reciprocal Venue reservations
- [`charities`](charities.md) - reusable partners, governed edition selection,
  independent review, approved media, and minimized public snapshots
- [`venues`](venues.md) - reusable hotels and venues, exact edition space
  selection, hard availability, operational bookings, and public schedules
- [`logistics`](logistics.md) - equipment offers, storage and containment,
  manifests, restricted operational contacts, and append-only custody
- [`workforce`](workforce.md) - departments, positions, volunteer openings,
  reviewed agreements, assignments, and scoped access activation
- [`announcements`](announcements.md) - standalone reviewed manual publishing
  under implementation; exact profile and verification tracked in CURRENT
- [`knowledge`](knowledge.md) - internal Guides and FAQs with reviewed current
  copy and separately accepted event access; implementation in progress
- [`communications`](communications.md) - canonical service inbox and email
  delivery evidence
- [`accreditation`](accreditation.md) - credentials and bounded offline check-in
- [`privacy operations`](privacyops.md) - subject rights, historical
  corrections, retention, and disposal evidence
- [`Convention work`](staff-console.md) - React/TypeScript workflows mounted in
  the unified shell; canonical repository acceptance and bounded read-only
  responsive verification recorded, with broader browser acceptance pending
- [`demo data`](demo-data.md) - local-only synthetic cross-module fixture
- [`Marucon admin-first rehearsal`](../operations/marucon-admin-rehearsal.md) -
  retired public-roster path and the supported synthetic replacement journey

Target modules that have not been implemented remain in the architecture and
delivery plan, not as empty Django applications.
