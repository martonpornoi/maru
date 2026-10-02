# Programme local-assisted rehearsal: protected delivery

Date: 2026-10-02. Scope: #203, supporting #92/#109/#108/#48.

## Delivered state

[PR #204](https://github.com/martonpornoi/maru/pull/204) squash-merged at
07:59:36 UTC as `911002068dd5acb89ac4e4a8c46b60c1081c6097`, closing #203.
The certified head `df9e094fa7cef0e9e16cd4e5344a9a4cdad07811` and squash
have identical tree `8b6c3c4576e15aad106c1d086ffd52fc3f72bfe4`.
Clean local main was safely fast-forwarded to the protected squash; unrelated
worktrees, stashes and resources were preserved.

The local-only browser bridge and its repairs remain governed by ADR 0115.
Production routes, TLS policy, adoption profiles and permissions are unchanged.
The interrupted and superseded runs remain distinct preserved failure evidence;
none was used as certification of the final head.

## Exact local acceptance

Ordinary `scripts/certify.ps1` completed all ten gates at the clean final head,
with `CI=true`, pinned pnpm 11.9.0, all PostgreSQL history and unchanged coverage
thresholds. It ran from October 1 22:34:11 UTC to October 2 02:47:53 UTC,
exit zero, **4h13m41s**. The schema-3 success receipt's SHA-256 is
`b5818bb43e4566549d367dea26177807b01154f43e8ca3f1385b0a36528cc4ad`.

- **18,538 Python cases:** 13,457 units and 5,081 native cases across 71 shards.
  All 72 XML reports were parsed, with zero failures, errors or skips.
- **103 frontend cases**, both dependency audits and **91.74%** combined
  branch-aware coverage passed; the minimum remains 90%.
- Every native shard passed measured headroom and owned cleanup. Slowest local
  shard 34 took **50m10s**; its conservative projection was **85m14s**, below the
  unchanged 90-minute planning ceiling. At most eight databases ran concurrently.
- All 5,043 local-ci artifacts and three wrapper files were preserved and
  individually SHA-256 compared before delivery. All 71 owned containers were absent.

## Independent hosted acceptance and merge

[Hosted run 36958056721](https://github.com/martonpornoi/maru/actions/runs/36958056721)
completed at 07:41:05 UTC in **4h42m44s**: 82 successful jobs and three intentional
alternate-path skips. All 71 PostgreSQL shards passed. All 73 full-run artifacts
were downloaded; the 72 Python XML reports again contained exactly 18,538 cases
with zero failures, errors or skips. Combined coverage was **91.73%**.

Native job durations ranged from **7m15s to 57m29s**, median **19m09s**. The
slowest was shard 68, leaving **62m31s** before the unchanged two-hour timeout.
These are measured job durations, not a guarantee for future changes.

Exact-head `PR gate` check 110751665026 and CodeQL protection check 110685490417
passed. Fresh Python, JavaScript and Actions analyses had zero findings; alert 22
was fixed, not dismissed. The sole review conversation was resolved/outdated.
Fresh up-to-date CLEAN/MERGEABLE state was verified before squash with
`--match-head-commit`; no administrative bypass or security waiver was used.

## Remaining acceptance and handoff

The separate eighteen-phase joined native rehearsal remains attributed to
`0d2a3aa5c862e70f2741cceb6aedc0f03b2042af`, **1,265.44s**, not relabelled as a
browser run or certification of another commit. See the
[verification recovery checkpoint](2026-10-01-programme-rehearsal-verification-recovery.md).

#203's acceptance list and its supporting #48 item were reconciled. #92, #109,
#108 and #48 remain open: remaining assistant browser interaction evidence,
representative independent-person/specialist accessibility/owner acceptance and
separately verified final profile promotion must not be inferred from green CI.
The temporary `finish-maru-203` check-in was deleted after verified delivery.
No replacement schedule or production activation was created.

Continue the remaining continuity/print/offline and archive/stop browser checks
with explicitly admitted synthetic roles. Record their actual outcomes separately;
this delivery checkpoint is not their acceptance.
