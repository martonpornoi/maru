# Implemented modules

Only modules with executable behavior appear here.

ADR 0030 retains these backend modules; the controlled interface currently
mounts Sign in and Pages 1–7 through the edition record/workspace spine. ADR
0037 and `docs/project/PRODUCTION_CONSOLIDATION.md` distinguish mounted,
API-only, preserved/unmounted, partial, absent, and deployment-gated
capabilities. References in module documents to Convention work, Specialist
records, registration pages, or other HTML surfaces describe the preserved
pre-reset implementation unless the paragraph explicitly identifies the
current baseline.

- [`core`](core.md) - platform-neutral runtime primitives
- [`identity`](identity.md) - platform account boundary
- [`organizations`](organizations.md) - tenant, series, and membership
- [`events`](events.md) - event edition, profile, and authorized lifecycle
- [`participation`](participation.md) - self-scoped relationship and history
- [`authorization`](authorization.md) - scoped capabilities, grants, and policy
- [`audit`](audit.md) - append-only control evidence and integrity batches
- [`effects`](effects.md) - domain events, transactional outbox, and delivery
- [`activity`](activity.md) - bounded value-minimized record history
- [`registration`](registration.md) - configurable forms, products, attendee
  lifecycle, entitlements, and check-in
- [`workforce`](workforce.md) - departments, positions, volunteer openings,
  reviewed agreements, assignments, and scoped access activation
- [`communications`](communications.md) - canonical service inbox and email
  delivery evidence
- [`accreditation`](accreditation.md) - credentials and bounded offline check-in
- [`privacy operations`](privacyops.md) - subject rights, historical
  corrections, retention, and disposal evidence
- [`Convention work`](staff-console.md) - preserved React/TypeScript workflows,
  currently unmounted
- [`demo data`](demo-data.md) - local-only synthetic cross-module fixture
- [`Marucon admin-first rehearsal`](../operations/marucon-admin-rehearsal.md) -
  clean-database educational scenario with bounded public-roster import

Target modules that have not been implemented remain in the architecture and
delivery plan, not as empty Django applications.
