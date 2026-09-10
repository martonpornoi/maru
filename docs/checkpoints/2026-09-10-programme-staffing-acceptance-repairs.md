# Programme staffing certification repairs and fast containment feedback

- Date: 2026-09-10 (Europe/Budapest).
- Child: [#88](https://github.com/martonpornoi/maru/issues/88), parent #48.
- Failed exhaustive candidate: `9a48829f43d40c72e5241e81c45b675ff20c1328`.
- Base: `cdb06d41a6d5795078a8ae19ee5e4a0ebbabd466`.
- Contracts: HR-015, INT-002/003, NFR-013 and ADR 0093; no activation.

## Complete failure inventory

All eight PostgreSQL shards completed: 3,683 tests passed and four failed,
without skips or teardown errors. The slowest shard took 7,007.353s. All 4,252
unit tests, 64 frontend tests and non-database quality gates passed. Combining
the nine preserved coverage parts separately gives 90.56% branch-aware coverage.
This is diagnostic evidence from a failed run, not a successful certification.

The failures exposed three bounded compatibility gaps:

1. `workforce.programme_staffing.changed.v1` was registered but missing from the
   explicit dormant-event set. Its sole addition to that set preserves the
   absence of internal/notification handlers and current-profile/non-edition
   routes. A database-free test now verifies exact registry coverage, disjoint
   classifications and handler presence/absence. A separate staffing test checks
   the exact event's route exclusions. The original integration check remains.
2. Both retained Scheduling/Venues downgrade variants assumed that the entire
   migration recorder remained unchanged. Only the six empty Programme 0010-0012
   and Workforce 0019-0021 successors had legitimately reversed before the
   populated owner fence. Tests now require that exact difference, unchanged
   retained candidate/revision values and intact owner readiness. Full reapply
   must restore the exact original migration set, evidence and readiness.
3. The Shift no-truncate test was intercepted by new binding foreign keys before
   reaching its existing guard. The synthetic attempt now explicitly includes
   both referencing binding tables; it still requires the original no-truncate
   error, with production guards enabled and the test-reset escape off. Demand,
   commitment and receipt survival are checked after rollback. It neither uses
   a broad cascade nor accepts a looser error as a substitute for the guard.

No production migration, database guard, recovery fence, timeout, history
selection, coverage threshold or executable profile is changed. The Effects
module and staffing recovery guide now describe the actual dormant classification
and partially reversed unused-successor recovery boundary.

## Verification and delivery boundary

- Focused database-free registry, adoption and staffing contracts: 68 passed in
  0.39s. This moves registry omissions into immediate feedback without dropping
  the original integration assertion.
- Complete fast suite: 4,254 passed in 21.89s, with two existing URLField warnings.
  An initial run encountered only Windows shared pytest-temp access errors;
  a dedicated workspace temp directory resolved them without code changes.
- Five isolated PostgreSQL cases: 5 passed in 227.32s. These cover empty
  Scheduling joint-graph reversal/reapply, both populated owner fences, the
  actual Shift truncate guard and the original closed-registry assertion.
  Pytest reported one optional cache-write warning; every test passed.
- Focused formatting/lint and documentation validation passed while preparing
  this repair; the new clean commit still requires complete certification and
  its own protected GitHub acceptance.

The failed run's complete reports and coverage are preserved. Its eight
disposable databases were removed by the certifier; the separate disposable
quality database was removed after use. Only a task-owned synthetic recovery
fixture was created for focused checks. No unrelated Docker resources, worktrees
or stashes were altered. There is no staffing PR or merge at this checkpoint;
#88 and #48 remain open, with #87 mandatory before activation.
