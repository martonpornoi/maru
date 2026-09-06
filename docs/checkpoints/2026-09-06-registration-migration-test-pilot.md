# Registration historical-migration test pilot

Date: 2026-09-06
Issue: [#75](https://github.com/martonpornoi/maru/issues/75)
Requirements: NFR-001, NFR-002, NFR-003
Related decisions: ADRs 0061, 0063, and 0066; no new architecture decision

## Outcome and scope

The pilot evaluates shared committed setup for the twelve serial Registration
0035-to-0036 ACL-retirement, backfill, and invalid-history cases. The two schema
round trips and populated durable-receipt downgrade fence remain committed
tests in the original file. Every original input, assertion, and actual
migration is preserved; tests are reorganized, not dropped.

Synthetic Account, EventEdition, and Participation parents are created through
current factories before downgrading. Each case receives only their identifiers
and uses freshly rendered historical models. The existing rollback helper
isolates case data, DDL, migration records, and callbacks, checks deferred
constraints, and rejects non-atomic transitions. No Django model-state cache,
fake migration, disabled SQL guard, or global fixture change is introduced.

Two additional PostgreSQL regressions execute real forward DDL and backfill,
then verify rollback after success and a synthetic exception. A second isolated
case checks absent rows, schema, and recorder changes, discarded callbacks, and
preserved baseline parents. Final module teardown restores current leaves once
and independently inspects all managed model tables/columns and the migration
plan, without executing another repair migration.

The first changed run exposed pending deferred foreign-key trigger events when
uncommitted legacy inserts preceded table alteration. The pilot-local migration
helper now uses Django's constraint check before real DDL inside case isolation:
it validates the input that the original tests had already committed, without
committing the isolated case or disabling constraints. A third new regression
requires invalid deferred data to fail at that boundary, not only at eventual
case cleanup. Production migrations and the shared isolation helper are unchanged.

No application source, production migration, authorization, runtime-role,
coverage, selection, timeout, worker-count, or hosted-policy change is in scope.
Existing Docker resources, other worktrees, and stashes are not cleanup targets.

## Verification and measurement boundary

The unchanged fifteen-case benchmark starts from protected main
`08ae02ef12e21e2bf91990c9527ebd840d624c54`. A dedicated PostgreSQL 17.11 Alpine
container holds only synthetic data. Before and after use the same locked
Python environment, one serial worker, fresh pytest database, branch-aware
coverage instrumentation, and whole-group setup/restoration timing. A focused
group's partial coverage is not the full repository coverage gate.

| Complete group | Cases | JUnit elapsed time |
| --- | --- | --- |
| Unchanged baseline | 15 passed | 2,643.355 seconds (44m03s) |
| Pilot, including new regressions | 18 passed | 847.331 seconds (14m07s) |

This comparable one-worker group measurement reduces elapsed time by about
68 percent, including fresh setup and final restoration. Outer process times
are 2,647.144 and 849.525 seconds respectively. It is not an eight-shard
whole-suite speedup claim. No competing database test workloads ran during
either measurement.

- The first changed run stopped on the deferred-input fixture defect after
  four passing cases; its timing is not speedup evidence.
- After the fix, all twelve moved cases, three new boundary/leakage cases, and
  four generic PostgreSQL isolation cases passed: 19 tests in 216.80 seconds.
  This focused run reused the retained current database and is not the fresh
  complete-group comparison above.
- All 110 focused migration-support, CI selection, shard, timing-map, and workflow
  unit checks passed, along with Ruff/formatting and documentation validation.
  Source-level comparison retained
  all eleven original test-function bodies and parameter inputs, accounting for
  the fifteen original collected cases; only the explicit parent-fixture
  argument changed within the moved test bodies.
- Independent processes inspected current migration leaves, all 243 managed
  models' tables/columns, and representative profile-value guards after both
  focused and final benchmark teardown, without running repair migrations.
- Only the two affected timing weights change: 208.747 seconds for historical
  cases and 637.979 seconds for committed recovery cases, from the passing
  eighteen-case JUnit report. These one-worker measurements include their
  attributed setup/restoration and are scheduling inputs, not hosted forecasts.
- The exact run-owned disposable benchmark container and synthetic database
  were removed. Every pre-existing container was preserved; no existing volume
  cleanup was performed. Timing logs, XML, and previous certification evidence
  remain in the ignored local benchmark directory.

The pilot meets its measured group-improvement threshold. Exact-commit local
certification and independent protected hosted acceptance are separate required
delivery gates. The linked issue and PR own those later acceptance and merge
results; this candidate checkpoint does not predict them.

## Continuation boundary

This is a test-maintenance prerequisite, not a capability child of Programme
umbrella #48. One group cannot establish a whole-suite speedup. Do not extend
the fixture to other migration boundaries without reviewing their exclusions
and measuring them separately. Complete this bounded delivery, then stop;
accepted-item conversion remains the next Programme product boundary.
