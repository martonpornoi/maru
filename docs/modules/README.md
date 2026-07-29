# Implemented modules

Only modules with executable behavior appear here.

- [`core`](core.md) - platform-neutral runtime primitives
- [`identity`](identity.md) - platform account boundary
- [`organizations`](organizations.md) - tenant, series, and membership
- [`events`](events.md) - event edition and authorized lifecycle
- [`participation`](participation.md) - self-scoped relationship and history
- [`authorization`](authorization.md) - scoped capabilities, grants, and policy
- [`audit`](audit.md) - append-only control evidence and integrity batches
- [`effects`](effects.md) - domain events, transactional outbox, and delivery
- [`registration`](registration.md) - configurable forms, products, attendee
  lifecycle, entitlements, and check-in
- [`workforce`](workforce.md) - departments, positions, volunteer openings,
  reviewed agreements, assignments, and scoped access activation
- [`communications`](communications.md) - canonical service inbox and email
  delivery evidence
- [`accreditation`](accreditation.md) - credentials and bounded offline
  check-in
- [`privacy operations`](privacyops.md) - subject rights, historical
  corrections, retention, and disposal evidence
- [`Staff Console`](staff-console.md) - separate React/TypeScript staff workspace
- [`demo data`](demo-data.md) - local-only synthetic cross-module fixture

Target modules that have not been implemented remain in the architecture and
delivery plan, not as empty Django applications.
