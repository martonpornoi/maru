# Checkpoint: Historical PostgreSQL work density

- Date: 2026-10-09
- Requirements: NFR-001, NFR-002, NFR-003, NFR-008
- Decision: [ADR 0098](../architecture/decisions/0098-budgeted-postgresql-shard-planning.md)
- State: Scheduling repair; fresh full and hosted acceptance pending

Announcements commit `0eabf43b421804aed1ef7db7bec0c5603f7c299c`, against base
`e77fae5b94dbee3e7f2e9d64b2f768be95888738`, passed 63 of its 74 planned native
shards before shard 64 exceeded its measured limit at 3,200.687 seconds. All three
test bodies passed; the last restoration was interrupted. Eight started shards
failed or were interrupted and three never started. Static/frontend gates and
13,806 units passed, but no certification success receipt exists.

The entire failed evidence tree (4,694 files, 402,524,440 bytes) was copied and
verified by SHA-256 under the original checkout's ignored certification-evidence
directory. The console and exact-commit source ZIP were independently preserved.
No partial test or timing report was promoted to acceptance or new timing costs.

An unchanged isolated diagnostic of shard 64 passed all three cases and cleanup
in 2,279.203 seconds. Its owned container was removed. The first test's complete
current-graph restoration passed, as did additive Registration schema reversal
and the populated unproven-template refusal. This establishes that diagnostic
only; it does not prove the reason for concurrent slowdown or future headroom.

The repair caps historical group density at two per job while preserving complete
shared baselines, parameter variants, costs and all selected work. On this source
inventory it assigns the same 374 groups, including 106 historical groups, to
77 jobs instead of 74. Eight concurrent databases, the 128-job ceiling, all
runtime budgets, coverage, isolation and protected delivery rules remain.
The density cap participates in the independently reproduced frozen manifest.

Verification passes 121 focused policy cases and all 13,816 database-free cases
in 73.91 seconds. Lint, formatting, Python documentation contracts and Markdown
validation pass. Focused tests cover invalid/capacity limits, complete unique membership,
indivisible groups, deterministic ordering, unchanged current-only assignments
and manifest policy binding. A clean full run
and independent hosted acceptance remain necessary before any delivery claim. The unchanged diagnostic
and estimates alone do not make PR #210 ready or close Programme acceptance.
