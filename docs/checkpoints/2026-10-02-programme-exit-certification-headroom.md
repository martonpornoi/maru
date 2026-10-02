# Programme exit certification timing repair

Date: 2026-10-02
Scope: #205's delivery blocker under #48; NFR-001, NFR-002, NFR-003 and NFR-008.
Decisions: ADRs 0090 and 0098 remain unchanged.

## Failed exact candidate and retained evidence

The clean `eb620d41cce26179801f124a68ad81c4793e998d` candidate, based on
`911002068dd5acb89ac4e4a8c46b60c1081c6097`, ran ordinary `scripts/certify.ps1`
with pinned pnpm 11.9.0 and `CI=true`. Its one-shot process began at 17:53:11 UTC
and finished with exit 1 at 19:29:26 UTC. There is no success receipt.

The units passed **13,489 / 203.81s**, with three existing Django warnings.
Thirty-eight PostgreSQL shards passed. Shard 34 exceeded the unchanged measured
headroom limit at **3,200.657s**; seven other active shards were cancelled by the
existing pool control, and the remaining 25 were never started. These partial
results are not certification. All 46 result records report owned-container
removal; a separate Docker readback found no remaining `maru-cert-*` containers.

All **4,419** files under `.local-ci` and the three one-shot worker files were
preserved and independently SHA-256 compared under
`.tools/certification-evidence/programme-local-eb620d4-headroom-failed`.
The original results remain in place until a fresh certification replaces them.

## Diagnosis and bounded optimization

Incremental timing shows the real activated helper-downgrade cases passing their
assertions before cancellation during cleanup. The old group estimate is
**1,573.166s**. The complete previous `df9e094` certification independently
measures both variants together at **2,100.880s**, including setup and teardown;
its whole shard took **3,009.609s**, already close to the local limit.
The maintained cost refresher reconciled all 371 groups from that successful
source-matched receipt into an ignored diagnostic file, not a new policy or
acceptance result. A timing-only refresh would expose an indivisible group above
the one-hour predicted budget. It is not permission to raise that budget.

Both cases use one connection and transactional migrations. The repaired test
commits activation first, executes each original Django migration plan inside
the existing `rollback_migration_case()` boundary, and checks the original
refusal, retained activation and hardened helper contracts **before** rollback.
It then verifies exact restoration of migration-recorder membership and complete
helper metadata, plus the retained activation. `migrate_test_targets()` rejects
any future non-atomic transition instead of silently wrapping it.

This removes redundant forward reconstruction after negative cases. It does not
fake migrations, skip a guard or parameter, split the group, cache model state,
change production code, or replace committed full-graph recovery. The ordinary
restoration fixture remains as a safety net. No schema migration, new authority,
production profile, timeout, coverage threshold or GitHub rule changes.

## Verification and continuation

Complete database-free units pass **13,489 / 91.21s**, with the same three
existing Django warnings. Changed-test Ruff/format and whitespace checks pass;
documentation validation passes 710 Markdown files, four skills and 215 unique
requirement identifiers. The real dependency graph contains no non-atomic
migration below either tested hardening boundary; runtime planning still enforces
that condition independently through the maintained helper.

The complete repaired shard 34 passed **78 cases**, with zero failures, errors
or skips, in **1,606.094s (26m46s)** wall time; pytest reports 1,596.55s. Its eight
groups and all 78 unique selected node IDs exactly match the failed run's
selection, including both original downgrade-refusal variants. Their call phases
passed in 480.457s and 468.137s; their teardown phases took 1.111s and 1.093s.
The existing pool runner reported measured headroom, exit zero and owned-container
removal. Separate Docker readback confirmed removal and no remaining native pool
or browser fixture. The diagnostic source fingerprint was unchanged throughout.
Evidence is retained under `.tools/programme-205-shard34-repair-r1`.

This was a **one-database diagnostic**, not an eight-worker timing comparison or
whole-commit acceptance. Complete fresh candidate certification remains required.
Do not push or open a PR based on the old receipt, passing subsets or the
diagnostic cost estimate. Certify the clean final commit with all required history
and unchanged headroom, then require its independent protected GitHub acceptance.

#48, #92, #109 and #108 remain open; no human or operational acceptance is claimed.
