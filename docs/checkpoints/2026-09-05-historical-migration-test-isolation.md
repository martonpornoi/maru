# Historical migration-test isolation and feedback time

Date: 2026-09-05
Requirements: NFR-001, NFR-002, NFR-003
Related decisions: ADR 0061 and ADR 0063, as refined by ADR 0066

## Outcome and boundaries

The #64 candidate passed exact-commit local certification, but three hosted
integration shards exceeded the existing two-hour limit on two attempts. The
maintainer requested faster, meaningful tests rather than weaker acceptance.

A profile of the clean organization-governance reverse/forward case recorded
301,848 historical model renders and about 487 of 520 profiled seconds inside
model rendering. An unprofiled diagnostic took 324.51 seconds, about 90 of them
in cyclic garbage collection. A threshold experiment reduced this to 261.83
seconds but increased observed peak memory. Garbage-collection settings remain
unchanged; the implementation removes repeated setup instead.

Three opt-in historical groups share a committed baseline: Workforce structure
write integrity, organization governance, and authorization scope-v2 activation.
The real Django executor still traverses the full graph at group setup and
restores current leaves at teardown. Every historical case executes its own
real forward/reverse migrations, data preflights, and assertions in an isolated
rollback boundary. All 32 original cases across the affected files remain,
including current-state cases which keep ordinary committed fixtures.

The helper checks deferred constraints before successful cleanup, discards data,
DDL, recorder state, and commit callbacks on either outcome, rejects non-test or
non-PostgreSQL databases and nested baselines, and rejects non-atomic migration
plans inside case isolation. Concurrent, cross-connection, commit-sensitive,
non-atomic, and full-history recovery evidence is not moved into this fixture.
No runtime source, production migration, authorization assertion, global Django
executor, test selection, coverage floor, or CI timeout is changed.

Two current-state scope-v2 downgrade cases previously expected an unrelated
Workforce Page 9 guard, reached before the intended authorization reverse guard.
They now execute the actual wired authorization reverse operation, include a
clean control, and assert its own ADR 0041 refusal after scoped authority rows
have been removed but the permanent write fence remains. The real full-graph
round-trip and populated Workforce downgrade tests remain. This improves the
meaning of the assertions as well as eliminating an irrelevant traversal.

## Verification

- Initial pilot: all six original Workforce cases plus four new PostgreSQL
  isolation cases passed in 238.92 seconds. Shared historical setup took 153.21
  seconds and final current-graph restoration 78.91 seconds.
- The original Workforce file took approximately 50.6 minutes in the prior
  eight-worker, coverage-enabled certification. That is not a like-for-like
  comparison with the focused, uncovered pilot and is not an overall speedup
  claim.
- The eight organization historical cases passed with 273.181 seconds of JUnit
  time including shared setup/restoration; its seven unchanged current cases
  passed with 14.193 seconds. A separate authorization group in that run exposed
  obsolete manual trigger-disabling cleanup, not failed domain assertions. That
  cleanup was removed because case rollback now discards the synthetic rows.
- The repaired authorization run passes all 11 cases in 262.26 seconds; its
  current-state file accounts for 10.521 seconds and historical file 251.511
  seconds of JUnit time. The two downgrade assertions now reach their own guard.
- All 2,770 unit tests pass, including non-atomic forward/reverse rejection,
  preservation of the native plan outside isolation, and complete timing-map
  inventory. Ruff, formatting, and maintained-documentation validation pass.
- An independent read after teardown, without executing repair migrations,
  verifies current tables and columns for all 239 managed models, every current
  migration leaf, and absence of isolation-test sentinel tables.
- Scheduling weights cover all 185 current files. Unchanged files use the
  successful `9d408fb` eight-shard receipt; the six changed/new files use the
  passing focused file measurements above. These mixed-topology weights are
  scheduling evidence, not a claim of whole-suite elapsed time. Full acceptance
  still selects every test; the new exact-commit run will measure actual speed.
- Fresh exact-commit certification and the protected hosted gate must complete
  before this candidate is merged. Local receipts do not replace hosted
  acceptance.

## Next action

Finish verification and the protected #64 delivery, then stop. Do not extend
the fixture to unrelated migrations without checking its explicit exclusions
and measuring whole-group setup, case execution, and final restoration.
