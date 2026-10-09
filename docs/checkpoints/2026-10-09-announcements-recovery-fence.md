# Announcements retained-recovery repair

Date: 2026-10-09
Status: Focused repair verified; full acceptance remains open

## Failure and preserved evidence

The first required certification of Announcements candidate
`633fab42736d8d34d3112bac23947d19d449b27a` against protected main
`e77fae5b94dbee3e7f2e9d64b2f768be95888738` selected all historical owners:
374 groups, 106 historical groups, 74 planned PostgreSQL shards and eight local
workers. The plan fingerprint was
`11529b04cf1dbc9dede8e39fae255fe9a34a75b31f39b3b0d2a2ba15c82d83e0`.

Repository quality gates, 13,806 units and 108 frontend cases passed. Nine native
shards completed successfully. Shard 12 failed
`test_native_used_downgrade_refuses_before_removing_guards_or_recorder`; its
other 47 cases passed. The pool cancelled seven in-flight shards and removed all
recorded task-owned containers. Partial passing tests in cancelled shards do not
certify those shards. There was no successful receipt or aggregate coverage
result. All three hosted CodeQL analyses passed for this source; that does not
replace full native acceptance.

The complete local artifact tree, full log and exact source bundle were copied
to preserved local evidence before repair. SHA256 verification covered 4,257
files. No earlier successful or failed evidence, unrelated fixture or user
worktree was overwritten.

## Repair

The failing rollback targeted Programme archive migration 0020. Django first
reversed the newer Announcements 0001–0003 and Events 0019–0021 successors, then
Events 0018 correctly refused retained Programme evidence. The refusal arrived
after newer guards and migration-recorder entries had already disappeared.
The assertion exposed a real ordering regression and remains unchanged.

The Announcements leaf now checks its retained owner evidence and calls the
frozen Events 0021 setup preflight. That setup preflight also runs the complete
frozen Events 0018 joined recovery preflight. Original owner locks, refusal
messages and checks remain intact and execute before successor reversal.
Readiness pins the reviewed updated Python migration sources. No forward SQL
schema, runtime authority, quality threshold or timeout is widened.

Empty joined installations retain reversal/reapply support. Retained owner or
joined evidence requires fix-forward or a mutually consistent restore. This
repair preserves Programme recovery; it does not complete or activate #48.

## Verification and next action

The two readiness files pass Ruff and formatting. The existing focused recovery
and health unit set passes 65 cases. Native verification passed 20 cases in 384.47 seconds against a fresh
disposable PostgreSQL 17.11 database: the original failure, all retained
authority-family fences, and unused/used Announcements reversal. The task-owned
container was removed after the successful run.

With that focused evidence, commit the coherent repair and run a new complete
required certification of its exact source. Do not reuse the failed candidate's
partial results as acceptance. Draft PR #210 remains blocked until full local
and independent hosted acceptance succeed. Independent human, specialist
accessibility, native-print and production acceptance remain separate.
