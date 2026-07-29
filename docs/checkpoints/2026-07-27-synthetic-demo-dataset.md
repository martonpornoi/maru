# Synthetic two-convention demonstration dataset

Date: 2026-07-27  
Phase: Platform foundation V02  
Requirements: MARU-FND-005, MARU-FND-007, IDN-001 through IDN-004, EVT-001
through EVT-005, ARC-001, ARC-002, UX-004

## Outcome

Maru now has a reusable, deterministic, local-only demonstration dataset and
the current development database has been populated from it. The fixture
contains two independent furry-convention organizer tenants with realistic
overlapping personas while preserving the platform's account, tenant, edition,
archive, capability, audit, and outbox boundaries.

The loaded dataset contains:

| Record | Count |
| --- | ---: |
| Accounts | 80 |
| Organizations | 2 |
| Convention series | 2 |
| Event editions | 6 |
| Organization memberships | 58 |
| Participations | 220 |
| Participation capacities | 734 |
| Role bundles | 8 |
| Role assignments | 146 |
| Lifecycle transitions | 12 |
| Audit events | 12 |
| Domain events | 12 |
| Outbox messages | 12 |

## Conventions and annual history

- Pannon Paws Foundation (Demo) operates Danube Furry Convention.
- Northern Tails Association (Demo) operates Aurora Tails.
- Each series has an archived 2025 edition, a preparing 2026 edition, and a
  draft 2027 edition.
- Three synthetic accounts participate across both organizers to demonstrate
  one platform identity without tenant visibility collapse.

The fixture represents board chair, vice chair, treasurer, secretary,
convention chair and deputy, operations, registration, volunteer coordination,
programme, guest relations, dealer relations, IT, stage and AV, safety,
security, first aid, accessibility, hotel, communications, art show, charity,
fursuit operations, logistics, front desk, volunteers, hosts, dealers and
assistants, guest of honour, performer, photographer, sponsor, ordinary and
first-time attendees, an invited volunteer, a cancellation, and former board
history.

## Implementation

- Added `maru.demo`, installed only by local and test settings.
- Added `seed_demo_data --password ...` with JSON created/total reporting and
  explicit `--reset-passwords`.
- Stable UUIDv5 identities and natural-key collision checks make repeat loads
  deterministic and fail closed around non-demo records.
- The complete seed is atomic and does not delete data.
- All addresses use `.invalid`; no production personal data or provider
  credential is present.
- Lifecycle progression uses `transition_edition`, producing canonical
  lifecycle versions, transition history, audit events, domain events, and
  transactional outbox messages.
- Added root quick-start, development setup, implemented-module, progress, and
  current-state documentation.

No ADR was needed. The fixture implements the accepted multi-tenant,
event-history, and capability-scope decisions without changing them.

## Verification

- Fixture command loaded the current local database successfully.
- Second local load created zero records and returned identical totals.
- Demo administrator and convention-chair passwords authenticate.
- The Danube convention chair receives `events.transition` through the expected
  edition-scoped role assignment.
- Focused command tests pass, including comprehensive structure, shared
  identity, capacities, policy, idempotency, and production refusal.
- Ruff format and lint pass.
- Strict mypy passes 79 source files.
- 167 PostgreSQL tests pass.
- Branch-aware coverage is 92.40%, above the 90% gate.
- Django local and production deployment checks pass.
- Migration drift check reports no changes.
- OpenAPI 3.1 generation and validation pass.
- Audit integrity verification passes with 12 expected unsealed demo events.
- Documentation validation passes 54 Markdown files and 164 unique requirement
  identifiers.

## Known limits and next actions

The current schema does not yet have dedicated department, position,
application, onboarding, shift, programme-item, dealer-table, registration,
order, accommodation, case, asset, or message records. The fixture uses
participation capacities to represent those personas honestly rather than
claiming later vertical slices exist.

The 12 lifecycle outbox messages are pending because the supervised effects
worker remains future work. The fixture should become the representative local
and performance dataset as V03 and later modules add their owned records.
