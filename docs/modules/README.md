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
- [`Convention work`](staff-console.md) - React/TypeScript workflows embedded
  in the original administration shell
- [`demo data`](demo-data.md) - local-only synthetic cross-module fixture
- [`Marucon admin-first rehearsal`](../operations/marucon-admin-rehearsal.md) -
  clean-database educational scenario with bounded public-roster import

Target modules that have not been implemented remain in the architecture and
delivery plan, not as empty Django applications.
