# Pinned populated Programme logical recovery

Date: 2026-09-20. Requirements: EVT-007, INT-007, NFR-013 and the #97 recovery
contract within #48/#108/#109. This is local exact-source journey evidence, not
whole-repository certification, protected delivery or production recovery approval.

## Source and isolation

The maintained journey ran at exact commit
`dea7674068d6322bfae74b6f4e45b6e56d695c37` in the separate managed
`programme-recovery-dea7674` worktree. Explicit Python paths resolved both Maru
and rehearsal helpers from that checkout; only installed dependencies came from
the original environment. The pinned tracked worktree was clean afterward.
Concurrent Stop Programme preparation in the primary worktree did not alter the
source under test.

The first pinned attempt failed before provisioning because its ignored `.tools`
directory did not exist (3.15s, run18). Creating that directory fixed the setup
failure; its failed report remains. No database guard or timeout was changed.

## Result

Run19 passed: **one complete populated journey in 939.44s (15m39s)**. It retained
the maintained 15-second HTTP budget and one-hour owned rehearsal lease.

- Genuine complete logical restoration: **38.172s**, including restored worker
  and application readiness, current authorized read, unadmitted-reader denial,
  native withdrawal/retry, unchanged historical artifact, current-authority
  revocation and reversible clone-only unsafe privilege/function refusal.
- Incomplete-backup rejection: **5.484s**. A second actual custom-format dump
  deliberately omitted only nonempty release-journal data. The restored copy
  failed the exact public-table snapshot comparison before restored worker
  admission. The original remained unchanged and the new database was disposed.
- Populated archive phase: **79.907s**. Generation took **15.250s**, producing
  **157,233 bytes**, with **3,060,458 bytes tracked Python peak**, not RSS or a
  maximum-capacity claim.
- All maintained excluded-owner comparisons remained unchanged. After test
  disposal, Docker's exact `io.maru.programme-rehearsal-run` ownership-label
  inventory was empty. No unrelated container was removed.

Evidence: `.tools/programme-populated-runtime-native-19.xml`; failed initial
attempt `.tools/programme-populated-runtime-native-18.xml`. Earlier schema/native
fault tests and diagnostic failures are preserved in the
[native catalog recovery checkpoint](2026-09-20-programme-logical-native-catalog-recovery.md).

## Remaining boundary

This establishes the maintained synthetic same-image logical recovery outcome,
including the previously unexecuted partial-backup case. It does not establish
cluster-role backup, PITR, provider disaster recovery, complete P11 stop-use,
P12 denial coverage, browser/human acceptance, final profile promotion or full
exact-head local/hosted certification. #97 remains open pending protected delivery;
#48/#108/#109 remain open for their distinct outstanding criteria.
