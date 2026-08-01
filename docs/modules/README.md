# Implemented modules

Only modules with executable behavior appear here.

ADR 0030 retained these backend modules while the controlled interface mounted
Sign in and Pages 1–7. ADR 0039 now integrates that spine, Convention work,
and specialist records into one `/admin/` shell, while ADR 0040 implements Page
8 Executive Board activation. Their backend route, authorization, migration-
drift, frontend build, populated/fresh migration, local restore, sensitive-read
audit, and responsive browser gates pass. The final consolidated full-suite/
coverage rerun, accessibility, complete visual states, and owner rehearsal
remain. ADR 0037 and
`docs/project/PRODUCTION_CONSOLIDATION.md` distinguish mounted,
API-only, preserved/unmounted, partial, absent, and deployment-gated
capabilities. ADR 0041 defines the still-unimplemented department/resource
scope prerequisite. References in module documents to Convention work, Specialist
records, registration pages, or other HTML surfaces describe the preserved
pre-reset implementation unless the paragraph explicitly identifies the ADR
0039 migration and its current evidence.

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
- [`workforce`](workforce.md) - departments, positions, volunteer openings,
  reviewed agreements, assignments, and scoped access activation
- [`communications`](communications.md) - canonical service inbox and email
  delivery evidence
- [`accreditation`](accreditation.md) - credentials and bounded offline check-in
- [`privacy operations`](privacyops.md) - subject rights, historical
  corrections, retention, and disposal evidence
- [`Convention work`](staff-console.md) - React/TypeScript workflows mounted in
  the unified shell; current browser and release verification pending
- [`demo data`](demo-data.md) - local-only synthetic cross-module fixture
- [`Marucon admin-first rehearsal`](../operations/marucon-admin-rehearsal.md) -
  retired public-roster path and the supported synthetic replacement journey

Target modules that have not been implemented remain in the architecture and
delivery plan, not as empty Django applications.
