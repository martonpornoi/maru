# Programme conversion runtime provisioning correction

Date: 2026-09-06

## Finding and correction

The first complete-certification attempt for issue #77 / PR #78, candidate
`7709fa5c63dde14cfebf844e7a73ac1a678d45e1`, reported a failure in the real
operator-artifact provisioning test. The new accepted-transition relation was
declared SELECT-only in the readiness probe but omitted from the SQL artifact's
explicit privilege exceptions. Earlier focused probe tests did not exercise
that artifact. The certification was stopped after the failure; it did not
produce a successful full-suite receipt.

The provisioning SQL now revokes all privileges on the new relation from
PUBLIC and the runtime role, then grants only runtime SELECT. No capability,
profile, function execution, route, writer or delivery handler is activated.
The migration graph and domain implementation are unchanged by this correction.

## Verification

- A new database-free inventory test failed on precisely the missing relation
  before the correction, then passed. It checks every dormant Programme-owned
  and Applications Programme relation against explicit SELECT grants and write
  revocations, catching omissions before long certification runs.
- All 2,851 unit tests passed in 11.63 seconds.
- A fresh PostgreSQL database passed three real tests in 114.55 seconds:
  complete provisioning and late-failure rollback, prerequisite refusal, and
  the independently checked runtime relation/function allowlist.
- The fast inventory test supplements rather than replaces real SQL execution.
  Existing assertions, migration tests, timeouts and coverage gates remain.
- A new exact clean-commit certification and independent hosted acceptance are
  required before merge. PR #78 retains those candidate-specific results.

Failed-run logs were retained in ignored local artifacts. Only that run's
disposable PostgreSQL resources were stopped or removed; unrelated Docker
resources, worktrees and both retained user stashes were preserved.

See the [conversion recovery contract](../operations/programme-conversion-migration-and-recovery.md),
[current handoff](../project/CURRENT.md), and
[implementation checkpoint](2026-09-06-programme-accepted-conversion.md).
