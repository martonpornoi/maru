# Checkpoint: Venue catalog and operational space scheduling

- Date: 2026-08-09
- Phase: implemented and focused-verified
- Related requirements: VEN-001, VEN-002, VEN-003, VEN-008, SCH-004,
  SCH-006, SCH-009, SCH-010, SAF-008, AUD-001, NFR-001, NFR-002, NFR-009
- Related ADRs: 0001, 0002, 0003, 0005, 0008, 0031, 0039, 0041, 0044,
  0049

## Outcome

Maru now has an organizer-owned, reusable hotel and venue catalog with
governed media and layouts, accommodation room-type/night inventory without
guest data, explicit edition/property/space selections, hard availability,
capacity-aware operational bookings, and minimized public and My Maru schedule
projections. Properties are not Maru tenants; every write and restricted read
is scoped to its owning organization and, where applicable, one exact edition.

Staff can model sites, buildings, spaces, configurations, and mergeable room
combinations. Bookings distinguish setup, effective, and teardown intervals
and cover programme, panel, event, department, storage, catering, rehearsal,
and private uses. Approval and publication are independent, append-only,
actor/time/reason-attributed transitions.

## Decisions

- PostgreSQL exclusion constraints enforce the SCH-009 two-clique occupancy
  rule. Effective delivery conflicts with every occupying phase; setup/setup
  and teardown/teardown also conflict; only a preceding teardown and following
  setup may overlap as an explicit turnover window.
- Public and My Maru projections structurally contain only approved effective
  intervals, public copy/access facts, and an optional approved public-safe
  layout rendition. Setup/teardown, internal/provider/security data, review
  evidence, and non-public floor plans never enter those projections.
- Accommodation remains a bounded inventory catalog. Guest identity, room
  assignment, fair allocation, and hospitality fulfilment are outside this
  slice.
- Exact space access resolves through a typed `venue.edition_space` resource
  binding and responsible Department. Platform administrators receive no
  automatic convention authority.

## Changed areas

- Added the bounded `maru.venues` Django module, schema, commands, queries,
  strict APIs, same-shell pages, templates, and edition navigation entry.
- Added venue capability definitions, exact-resource binding resolution,
  policy bulk resolution, and authorization migration `0014`.
- Added `venues.0001` and `venues.0002`, including `btree_gist`, exclusion
  constraints, immutable-scope guards, append-only history, and binding checks.
- Added audit, domain-event, outbox, idempotency, version, and public-projection
  coverage plus the venue module documentation.

## Verification

- Focused PostgreSQL integration matrix: 8 passed.
- Ruff formatting and lint: passed for venue and touched shared boundaries.
- Focused mypy: 13 venue source files passed with no issues.
- Django setup/import, URL reversal/resolution, template loading, and Python
  compilation: passed.
- `makemigrations --check --dry-run`: no model drift for venues,
  authorization, or catalog.
- Documentation validation and `git diff --check`: passed.
- Final installed authorization readiness fingerprints were recomputed and
  pinned for minimum-scope and typed-binding functions.

## Data, migration, and deployment notes

Deployment requires PostgreSQL `btree_gist`; restore drills must verify the
extension, occupancy exclusion constraint, append-only triggers, and typed
binding functions. The authorization migration includes a downgrade fence and
refuses destructive reversal while venue capabilities or resource bindings
are durably used. Retirement, cancellation, and publication withdrawal are
the supported non-destructive recovery controls.

## Known risks and incomplete work

Programme ownership/adapters, schedule-version comparison, person/equipment
and qualification conflicts, service-day layers, calendar/signage/print
exports, guest accommodation allocation, travel, and hospitality fulfilment
remain intentionally out of scope. A coordinated cross-slice ADR still needs
to capture the occupancy and public-projection boundary without changing this
implemented contract.

## Recommended next actions

Exercise the mounted workspace with realistic explicit grants and concurrent
booking attempts, then design the programme adapter and export/versioning
contract before adding cross-module writes or guest accommodation data.
