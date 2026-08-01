# Authority-provenance writer and provable-backfill checkpoint

Date: 2026-08-01
Branch: `codex/full-platform-consolidation`
Requirements: IDN-002, IDN-004, IDN-005, IDN-009, IDN-011, IDN-012,
AUD-001, AUD-005, NFR-001 through NFR-004, NFR-008
Decision: ADR 0044

## Outcome

Maru now has the additive, exact-source stage of ADR 0044. Authorization
`0006` owns append-only `AuthorityIssuance` and `AuthorityControl` evidence for
capability grants, immutable role-bundle versions, and role assignments. New
Executive Board, ordinary authority, and delegated-grant writers create that
evidence in the target/audit/event/outbox transaction.

The internal evaluator selects the narrowest eligible source deterministically,
pins its exact issuance, validates current and historical lineage recursively,
fails closed on missing/malformed/cyclic/deep evidence, excludes generic
platform administration from organizer authority, and never silently rebinds
to another equivalent source. Role definitions retain historical proof while
new assignments require current dual control.

The initial Executive Board remains non-cyclic. Its bundle and initial
assignments retain the exact platform activation and independent accepted
appointment. The live writer requires an active platform operator; historical
validation/backfill deliberately does not depend on that operator remaining
active later. Exact activation attribution, platform account kind, activation
timestamp, initial appointment cohort, cross-approvals, assignment terms, and
end/revocation timestamps remain mandatory.

Two privacy-minimized operator tools are present:

- `check_authority_provenance_readiness` reports stable aggregate blocker and
  review counts without people, capabilities, tenants, target identifiers, or
  entered values. Its data status may be ready, but production status remains
  blocked until exact policy, completeness guards, and the downgrade fence are
  active.
- `backfill_provable_authority_provenance` is a dry run unless both `--apply`
  and `--acknowledge-writers-stopped` are supplied. It appends only exact
  initial Board evidence and parent-first delegated chains, verifies in the
  same transaction, is idempotent, suppresses private failure context, and
  leaves ordinary legacy authority untouched.

The fresh-install migration graph now explicitly orders identity `0010` before
organizations `0009`, whose SQL reads the newer identity columns.

## Verification

- 168 combined PostgreSQL provenance and regression tests passed in 227.48
  seconds, covering schema/reverse boundaries, live writers, recursive runtime,
  commands, delegation, policy compatibility, readiness, backfill, access
  management, workforce, and representation migrations.
- The focused backfill suite passed 24 tests on a fresh PostgreSQL database,
  including dry-run, acknowledgement, exact three-controller Board evidence,
  parent-first delegation, ordinary non-inference, partial-ledger refusal,
  bundle-before-assignment ordering, suspended/ended historical Board evidence,
  inactive historical activator, cyclic and malformed snapshot classification,
  whole-transaction rollback, idempotency, and count-only privacy. Its command
  and reconciler reach 100 and 95 percent branch-aware coverage respectively.
- The focused readiness suite passed eight tests, including future versus closed
  debt, delegated gaps, broad-bootstrap review, incomplete/identity mismatch,
  non-earlier delegated parent, metadata mismatch, deterministic JSON,
  non-waiving failure behavior, corruption classification, and bounded graph
  traversal. The readiness module reaches 91 percent branch-aware coverage.
- The issuance writer suite passed eight tests and reaches 100 percent statement
  and branch coverage. A two-connection PostgreSQL regression proves the
  database-level `(issuance, principal)` constraint permits exactly one of two
  concurrent same-principal actor/approver inserts to commit.
- The definitive repository-wide run passed all 964 tests in 590.97 seconds at
  90.41 percent branch coverage with no warnings.
- Ruff formatting/lint, strict mypy across 205 source files, Django local and
  deploy-shaped checks, migration drift, OpenAPI validation and generated-client
  stability, Staff Console typecheck/19 tests/production build, `pip-audit`,
  production `pnpm audit`, and `git diff --check` passed.
- Documentation validation passed for 171 Markdown files and 195 unique
  requirement identifiers.

## Recovery boundary

Authorization `0006` is additive before the first issuance. Once an issuance or
control exists, downgrade is refused. Keep compatible code and fix forward, or
restore the complete target/ledger/representation/audit/event/outbox database
state to one consistent pre-write point. Never reverse or delete only evidence.
Backfill apply requires a stopped-writer window and one transaction; a failure
must leave no appended row.

## Open production gates

- Effective/future ordinary legacy roots and assignments must be deliberately
  revoked and recreated under current independent control. Referenced or latest
  unproven role definitions must be replaced. No migration may infer sources.
- The dormant deferred completeness guards, audited irreversible activation
  marker, point-in-time exact policy switch, readiness gate resolution, and
  provenance-write downgrade fence are not implemented in this checkpoint.
- Representative restore/PITR and live desktop/narrow-browser evidence have not
  yet been rerun for this tranche. The repository-wide backend, migration,
  static, OpenAPI, frontend, dependency, and documentation gates are current.
- Contextual effective-access explanations and the hierarchy editor remain
  unmounted; production personal data remains prohibited.

## Smallest next action

Implement the dormant-guard/activation-marker stage from ADR 0044: land guards
without activating them, reconcile zero reachable blockers, lock the authority
graph, record an audited platform activation, switch policy to exact point-in-
time lineage, reject stale writers at commit, and prove both concurrency
orderings plus irreversible recovery before moving to the synthetic department
hierarchy.
