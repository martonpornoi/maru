# Checkpoint: IDN-011 database subject boundary

- Date: 2026-08-01
- Phase: Production consolidation and release hardening
- Related requirements: IDN-011
- Related ADRs: 0031, 0040

## Outcome

PostgreSQL now enforces that a platform administrator cannot be a convention
person in the remaining organization, participation, registration, and
workforce subject tables. The invariant covers ORM writes, bulk operations,
direct SQL, concurrent writes, and later identity-account reclassification.

Platform accounts remain valid in actor and provenance fields. The migrations
do not infer a replacement person, reclassify an account, or delete a
relationship.

## Decisions

- Each owning module installs its own trigger functions and migration.
- Every subject insert or update locks the referenced `identity_account` row
  `FOR UPDATE` before checking `account_kind = 'person'`.
- Deferred identity triggers reject a person-to-platform reclassification at
  transaction commit while a protected subject relationship remains.
- Trigger DDL precedes the final count-only existing-data preflight within one
  transactional migration, closing the scan-to-protection deployment race.
- Representation appointments are protected in every lifecycle state, not only
  open appointments.

## Changed areas

- organizations `0012_idn011_convention_subject_guards`;
- participation `0004_idn011_convention_subject_guards`;
- registration `0031_idn011_convention_subject_guards`;
- workforce `0003_idn011_convention_subject_guards`;
- focused runtime, concurrency, and migration-preflight integration tests; and
- requirement, module, and deployment/recovery documentation.

## Verification

- Focused platform-boundary and migration tests passed on a fresh PostgreSQL
  test database.
- Seventy-one adjacent organization-representation, platform-boundary,
  participation, registration, and workforce tests passed.
- Ruff formatting and lint checks passed for the migrations and focused tests.
- Django system check and migration-drift check passed.
- Documentation validation passed for 162 Markdown files and 195 unique
  requirement identifiers.
- All four migrations applied successfully to the populated local development
  database.

## Data, migration, and deployment notes

Deployment requires stopped writers and a representative restored-database
rehearsal. A non-zero legacy count aborts the owning migration with bounded
counts and rolls back its triggers and preflight together. Operators must
reconcile which fact is wrong under an approved procedure; they must not fake
the migration, disable triggers, or print subject data. The detailed procedure
is in `docs/operations/idn011-convention-subject-migration-and-recovery.md`.

## Known risks and incomplete work

- A representative restored production-like database rehearsal, backup/PITR
  evidence, and named deployment approvals remain external release gates.
- This checkpoint records focused and adjacent suites, not a new complete
  repository test run or coverage measurement.
- Lock-wait and deadlock behavior still requires deployment observability and
  incident-owner review under real workload characteristics.

## Recommended next actions

1. Run the complete repository verification and coverage gate from the final
   consolidated tree.
2. Rehearse preflight, forward application, postflight, and fix-forward
   recovery against a representative restored database with all writers
   stopped.
3. Retain count-only evidence and reopen writers only after compatible code and
   every postflight check pass.
