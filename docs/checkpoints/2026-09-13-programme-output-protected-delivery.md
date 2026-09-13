# Public/personal Programme outputs and budgeted CI: protected delivery

Date: 2026-09-13
Scope: #99 / PR #101, with the explicitly authorized PostgreSQL timeout repair.

## Protected result

- PR: https://github.com/martonpornoi/maru/pull/101
- Exact certified head: `ed654e27ff1328fde01171e93d74ceb16c5676c6`.
- Base: `0bea1b46f8611f3da8a3d3664f258505a8deb7e4`.
- Protected squash: `f999fb510b69901798959e16c120bf0fd15b839d`.
- Merged: 2026-09-13 01:10:30 UTC; #99 closed one second later.
- Both trees: `0ba97cc3af8d962ae6587eaf5d8bd5ab6749f6db`.
- Clean existing local main was fast-forwarded to the protected result and
  independently verified equal to origin/main. Other worktrees/stashes remained
  untouched. No policy bypass, deployment or general container cleanup occurred.

## Outcome

ADR 0097 delivers dormant release-derived public and exact-person host/volunteer
outputs. Each owner independently authorizes current source and audience;
immutable approved release facts remain distinct from current instructions and
retained Workforce work. JSON, calendar and rendered/print representations have
closed field ceilings and explicit unavailable/withdrawn/invalidated behavior.
Saved copies cannot be remotely erased or treated as signed offline continuity.
No profile, production route or runtime writer is activated.

ADR 0098 adds budgeted complete-group PostgreSQL planning, source-bound shared
local/hosted manifests, a bounded eight-worker fresh-database pool, incremental
timings and a measured local headroom guard. Scope, coverage, isolation and the
120-minute hosted limit remain unchanged. The planner expands with measured
cost and fails before execution for an indivisible over-budget group; it does
not silently omit tests or promise constant total suite duration.

## Exact local certification

The schema-3 receipt completed 2026-09-12 21:44:38 UTC in 12,778.125 seconds
(3h32m58s), selecting all history. All ten gates passed: 4,838 unit plus 4,251
PostgreSQL tests (9,089 Python tests), 64 frontend tests and 90.67% combined
branch-aware coverage. There were no failures, errors or skips. Locked inputs,
audits, static/NumPy documentation checks, fresh warning-fatal Sphinx, Django,
OpenAPI and generated frontend contracts passed.

All 39 exact planned jobs ran with at most eight concurrent databases; all
39 disposable containers were removed. Local elapsed times, including startup,
collection, shutdown and cleanup, were minimum 30m22s, median 43m01s, maximum
51m54s. Adding 50% slowdown and ten minutes overhead to the worst observation
gave 87m51s, leaving 32m09s before two hours. All jobs passed the 90-minute
projection ceiling. This is a conservative estimate, not a runner guarantee.

The shared plan fingerprint was
`9cbc93aa5da7f2d101e463c4e49cacb8423010bc22d3b5adf2dd0370dc658a63`.

## Independent hosted acceptance

[Run 34721009712](https://github.com/martonpornoi/maru/actions/runs/34721009712)
completed successfully at 2026-09-13 01:08:18 UTC. All 39 PostgreSQL jobs,
combined coverage, Full CI gate and protected PR gate passed. The archived
preflight log independently records the same plan fingerprint. Workflow
creation-to-completion elapsed time was 3h19m26s.

Actual hosted PostgreSQL job times, excluding queue wait, were minimum 27m22s,
median 39m58s and maximum 49m58s. The slowest job retained 70m02s before the
unchanged two-hour limit. No shard failed, skipped or timed out.

Downloaded JUnit/selection artifacts independently reconcile all 334 complete
groups and 4,251 unique PostgreSQL cases, plus 4,838 database-free units, with
zero failures, errors, skips, duplicate cases or duplicate groups. Hosted
combined coverage matches 90.67%. [CodeQL run 34721007850](https://github.com/martonpornoi/maru/actions/runs/34721007850)
passed all three analyses on the same head. Mergeability was clean with no
unresolved review conversations, and main had not advanced from the measured
base before merge.

## Failed evidence and tradeoffs

Original feature head `35bc135` passed local certification in 2h42m35s, but old
hosted shard 15 and its unchanged retry exceeded two hours. Neither is current
hosted acceptance. The first repair head `858a7f2` failed before any database
test because Windows selected Docker's extensionless wrapper. The native
Windows executable fix has regression tests and was included in the complete
replacement certification; no failed candidate received a success receipt.

The replacement exhaustive local run took 50m23s longer (31.0%). Smaller jobs
bound timeout and retry exposure but add fresh database setup; they do not
remove total migration-test work. The new shard 15's hosted 33m39s is not a
like-for-like comparison with the old partition's shard 15. Further actual
migration-work optimization remains separate from this timeout-resilience repair.

Original failed/passing evidence and full replacement local/hosted artifacts
are preserved separately in ignored task-local evidence archives. The first
post-download read-only Python reconciliation was blocked by the process sandbox;
the same check passed using the installed runtime with scoped tool approval.
That tooling restriction was not a test failure or a new certification run.

## Remaining boundaries and next action

#48's checklist now marks only #99 delivered and selects #100 next. That child
owns room/department operator run sheets and protected layers. Detailed change
impact/delivery/acknowledgement, on-site continuity, #97 logical restore, guided
setup and #92 human/screen-reader integrated acceptance remain open. Existing
valid #87 evidence is preserved, not reused to certify the new surfaces.

Continue single-agent on #100 from the protected result. Do not repeat the
completed #101 certification, reactivate a scheduled watcher, or infer supported
Programme Operations or production readiness from this merge.
