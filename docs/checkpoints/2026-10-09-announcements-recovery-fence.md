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

## Follow-up: retain a Programme edition before successor DDL

The fresh full run for `94646aa5180e532d6854d1e16c447e12005cef76`
passed the previously failing archive case and twelve native shards, plus
13,806 units. Shard 13 exposed a second joined reversal boundary:
`test_any_retained_programme_edition_fences_assignment_downgrade` reached a new
Events constraint alteration before Workforce 0029 could refuse the retained
Programme edition. PostgreSQL correctly rejected DDL with pending trigger events.
This was a failure, not a successful rollback rehearsal or a timing shortage.
Seven running shards were cancelled. All twenty started shard containers were
removed; no aggregate coverage or successful receipt exists for that source.

The complete failed artifact tree, log and source bundle were preserved before
repair; SHA256 verification covered 4,280 files and 174,521,351 bytes. The new
preflight locks event editions and retains a bare Programme edition even before
assignment evidence exists. It copies only the older data-only refusal, never
calls the older mutating reverse operation, and keeps its original message.
The original native test now also requires the entire migration recorder to
remain unchanged. The Events source fingerprint was refreshed accordingly.

Focused readiness/recovery units pass 65 cases. An expanded native batch covering
both failures, assignment reversal, retained authority and Announcements recovery
is in progress. A new full exact-commit run and independent hosted acceptance are
still required after the final coherent repair is frozen.

The expanded PostgreSQL 17.11 batch passed 27 cases in 436.79 seconds. Reviewing
the complete new predecessor set then added the frozen Organizations 0015 and
Authorization 0041/0042 preflights, protecting representation and access evidence
that can exist before any Announcements edition. Two new native tests use no
outer rollback, so an earlier committed successor reversal cannot be hidden by
the test harness. They require the entire recorder and native readiness to remain
unchanged after refusal.

The final focused batch passed seven native cases in 278.43 seconds: both original
certification failures, unused assignment reversal, unused/used Announcements
reversal, and the two pre-edition foundation refusals. Final readiness/recovery
units pass 65 cases in 1.07 seconds. Both disposable databases were removed.
The final Events 0021 source pin is
`f0fb832ba3a4495dc4ca7bcfad3f15a66dc28fa02e94de546ad55097cef19ff0`.
No previous owner SQL, runtime privilege, quality threshold or timeout changed.
A new complete certification still has to certify the frozen repair; these
focused results do not certify the failed candidate or close Programme #48.
