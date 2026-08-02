# Checkpoint: Page 9a.1 structure write cutover

- Date: 2026-08-02
- Phase: Production consolidation M2.4 / Page 9a.1 command and database core
- Related requirements: IDN-002, IDN-004, IDN-011, IDN-012, HR-010,
  HR-011, UX-025, AUD-001, INT-001, NFR-001 through NFR-004, NFR-008,
  NFR-009
- Related ADRs: 0041, 0044, 0045, 0046

## Outcome

The edition-owned Organization structure is now a versioned aggregate with a
stopped-writer database boundary. Workforce migrations `0006` and `0007` add
the structure control and append-only command receipt, backfill compatible
legacy Department trees as `legacy_existing`, and install the complete
control/receipt/Department evidence handshake. Direct or partially ordered
writes cannot create an unexplained current tree.

The shared, currently unmounted command core can apply the immutable
`awoostria-reference@1` template and create, replace, reparent, reorder,
retire, or safely delete a Department. Commands use exact organization,
series, and edition scope; fresh view-and-manage authorization; strict input;
positive expected versions; deterministic template/create retry evidence;
bounded complete-hierarchy validation; minimized audit; and transactional
outbox events. The platform administrator remains an oversight actor and is
not made a convention subject.

Page 9 reads now publish the aggregate version, minimized source kind, and
explicit active/retired Department state. HTML and API reads retry once around
a version movement and return a name-free `503` instead of mixing versions.
The mutation adapters remain deliberately unmounted until the next slice.

## Database and writer boundary

- The stopped-writer preflight rejects malformed or over-limit legacy trees,
  broken scope/parent chains, cycles/depth overflow, unsupported Department
  foreign keys, and incompatible Position, assignment, binding, or authority
  scope before installing guards.
- One global activation barrier and one exact-edition mutex define the common
  structure/authority writer order. Supported Department, Position,
  assignment, resource-binding, capability, role, Board, bootstrap, and demo
  writers enter that order before narrower row locks.
- Fourteen pinned `SECURITY DEFINER` helpers and 28 exact trigger attachments
  enforce the write protocol, scope mutex, immutable receipts, control and
  Department evidence, no-truncate behavior, and retired-Department target
  rules. They are not directly executable by `PUBLIC` or the runtime login.
- Retirement is one way. Current children, open Positions, active unended
  assignments, and unclosed present or future authority block it. Closed
  authority and immutable Position bindings remain historical evidence; they
  block hard deletion but do not falsely keep a Department operational.
- A hard delete is limited to a current command-created leaf with exact name
  confirmation, no later Department history, and no known or unknown retained
  dependency. The migration verifies the complete Department foreign-key
  contract so a later cross-module reference fails closed.
- Control, receipt, and Department data form a one-way recovery fence. After
  the cutover or a governed write, old writers and partial migration reversal
  are unsupported; fix forward or restore the application and whole database
  to one mutually consistent pre-cutover point.

## Production writer reconciliation

The first-authority bootstrap, management command, and synthetic demo seeding
now create Departments through the command service and create Positions and
assignments under the canonical edition scope. Specialist Department records
are inspection-only. Test setup uses the same public boundaries except where a
test deliberately exercises a historical migration state or hostile raw DML.

An adversarial writer sweep found and fixed three older authority paths that
could otherwise take target rows before entering the shared boundary:
delegated capability creation, access-assignment replacement, and Executive
Board activation/emergency containment. A two-connection regression holds the
delegation target rows while a Department update starts and proves that the
structure writer waits at the canonical advisory boundary, after which both
transactions complete without deadlock.

A transaction that began before the one-way exact-authority activation is a
distinct restart-required writer failure with stable SQLSTATE `40001`. Other
boundary inconsistencies remain non-retryable. This preserves fail-fast
operator and client behavior without manufacturing a database-driver cause.

## Readiness and verification

- exact Page 9 catalog and tamper contract: 47 passed;
- existing readiness, runtime hardening, and readiness views: 107 passed;
- full runtime-role matrix: 81 passed;
- stopped-writer integrity, migration, and writer-boundary suite: 18 passed;
- combined structure snapshot/schema/commands/scope/integrity focus: 48
  passed;
- canonical Page 9 HTML and API projection: 36 passed;
- production delegation/structure concurrency regression: passed on two real
  PostgreSQL connections;
- repository unit suite: 243 passed;
- exact-lineage administration navigation: 8 passed;
- structure and retired-authority migration focus: 9 passed;
- historical/current scope-v2 integrity and concurrent reparenting: 16 passed;
- authorization `0010` exact downgrade-fence contract: 14 passed, with every
  trigger disable/function tamper, missing recorder, and clean reverse covered;
- onboarding journey: 3 passed;
- repository-wide Ruff and formatting, strict mypy, documentation validation,
  Django local/deploy checks in both exact-authority modes, migration drift,
  OpenAPI validation and deterministic TypeScript generation, 19 frontend
  tests, frontend typecheck/build, whitespace, dependency integrity, and
  Python/Node vulnerability audits: passed.

These focused invocations overlap and must not be summed. The definitive
current-graph gate then recreated a fresh isolated PostgreSQL test database and
passed all 1,471 repository tests in 1,538.40 seconds with 90.13 percent branch
coverage. This supersedes the historical 1,239-test Page 9a.0 baseline for the
implemented Page 9a.1 command/database core.

## Known risks and incomplete work

- Strict HTML/API mutation adapters and their complete denied, stale, retry,
  protected, persistence, audit, and outbox response matrix are not mounted.
- Page 9b Position/template/reporting/opportunity management is separate and
  still requires its accepted authority-bearing workflow.
- Reliable 390-pixel, keyboard, automated accessibility, complete visual-state,
  and owner tutorial evidence remain open.
- A representative deployment still needs ordinary legacy-authority
  reconciliation, stopped-writer rehearsal, runtime-role transition,
  backup/PITR restore, load, telemetry, and named operator approval. Local
  migration and test evidence is not a production activation.

## Smallest next actions

1. Mount strict shared HTML and API adapters for template application and
   Department create/update/retire/protected-delete, using the completed
   command core without duplicating policy or validation.
2. Complete the response/concurrency/audit/outbox matrix and run the definitive
   repository coverage gate plus responsive/accessibility smoke.
3. Keep Page 9b separate, then proceed to the people/registration and shared
   programme-to-timetable journeys in the consolidation checklist.
