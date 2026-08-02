# Exact authority-lineage activation

Date: 2026-08-02

## Outcome

The repository implementation of ADR 0044's exact authority-lineage activation
slice is complete and locally verified with synthetic data. This milestone
installs and exercises the irreversible boundary; it is not a record of a
production cutover.

Authorization `0006` provides the append-only issuance/control ledger and
compatible source-aware writers. Authorization `0007`/`0008`, audit
`0005`/`0006`, organizations `0013`, workforce `0005`, and authorization
`0009` add the
dormant generation latch, immutable one-row activation marker and evidence,
writer barrier, deferred exact-completeness constraints, destructive-operation
fences, a narrow definer latch-lock helper, a reserved-activation-audit guard,
module-local plus converged downgrade protection, 57 exact security-critical
function fingerprints, and 12 exact caller-trigger contracts.

The `activate_authority_provenance` command and service require the external
exact-required fence, an explicit stopped-process acknowledgement, a zero-
blocker readiness graph, the configured PostgreSQL runtime-role proof, and a
top-level READ COMMITTED transaction. Marker and minimized audit evidence commit
together. Repeated activation is idempotent; local synthetic failure paths roll
both records back.

Exact policy selection is marker-backed and fail closed. Public readiness proves
the complete fingerprint contract and ADR 0046's genuine authenticated runtime
login; migration/cutover-owner provenance readiness proves the configured
target role instead. The application login reads but cannot mutate migration
history or marker/latch, delegate database authority, disable triggers, or
forge the reserved activation audit.

## Query-amplification boundary

The name-free scope projection resolves organization, edition, department,
typed-resource, and related target chains in five fixed queries independent of
candidate count. Exact issuance validation is bounded separately: one database
call is made for each chunk of at most 256 checks. The resulting database query
geometry is five fixed target-resolution queries plus `ceil(N / 256)` issuance
queries for `N` checks, not a wholly constant total.

This closes per-candidate target and issuance query fan-out. It does not bound
candidate-set construction, total rows, latency, or memory. Representative
unbounded candidate-cardinality load remains an explicit production gate.

## Focused verification

- combined runtime-role unit and real PostgreSQL matrix: 50 passed, including
  genuine-login readiness, three SELECT-only control relations, function
  nondelegation, and atomic provisioning-artifact success/failure;
- organizations `0013`, workforce `0005`, and authorization `0009` harden four
  direct helpers plus 12 persistent callers. Fresh hardening passes 9 tests;
  the corrected fence/hardening rerun passes 10; and populated organization/
  workforce migration history passes 31;
- readiness proves 57 of 57 exact function definitions and 12 exact trigger
  attachments. Hostile path/shadow objects, body/config and trigger tamper,
  ACL/OID symmetry, missing-recorder, and activated downgrade paths are tested;
- production settings in both exact modes, OpenAPI/client determinism, 19
  frontend tests, frontend build, Python/Node dependency audits, Ruff, mypy,
  Django checks, migration drift, whitespace, and documentation validation
  pass.

The focused invocations above may overlap and must not be summed into a
repository-wide test count.

The definitive fresh current-graph repository invocation applies all 117
migration-plan entries and passes 1,199 tests in 930.63 seconds with 90.33
percent branch coverage and no warnings.

## Recovery boundary

Local synthetic activation, transactional failure rollback, idempotent repeat,
pre-activation migration reversal where allowed, and post-activation
fix-forward protections are verified by focused tests and rehearsals. Once the
marker commits, exact lineage is one way: do not reverse authorization `0007`,
truncate/delete the marker, disable guards, or run an old writer. Recover with
compatible fix-forward code or restore the whole database and application to
one mutually consistent pre-activation point after an explicit data-loss
decision.

This local evidence is not representative deployment backup or PITR
certification.

## Explicitly not completed

- no real production or partner personal data was used;
- no effective ordinary legacy authority was reconciled or recreated in a real
  deployment;
- no production database was marked active and no production cutover occurred;
- no real production runtime role or credentials were provisioned;
- no representative deployment restore, backup/PITR, or operator cutover drill
  was performed;
- no representative unbounded candidate-cardinality load bound was established;
- no external security, privacy, recovery-owner, or go/no-go approval was
  granted.

## Smallest next actions

1. Reconcile every effective ordinary legacy authority row without inference on
   a representative restored deployment and prove the count-only zero-blocker
   preflight.
2. Measure latency, memory, and database behavior for representative large
   candidate sets while preserving the five-query target resolver and 256-check
   issuance chunks.
3. Rehearse the runtime-role transition, activation failure/fix-forward paths,
   and whole-database backup/PITR recovery with named operators.
4. Perform a production activation only after those gates and explicit go/no-go
   approval pass.
