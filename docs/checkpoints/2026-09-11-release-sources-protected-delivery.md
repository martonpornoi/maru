# Trusted Programme release sources: protected delivery

- Date: 2026-09-11
- Requirement: SCH-012, PRG-008, HR-015 and ADR 0095
- Issue: [#94](https://github.com/martonpornoi/maru/issues/94), child of #48
- Pull request: [#95](https://github.com/martonpornoi/maru/pull/95)

## Protected result

Exact candidate `8cae3d5ea9d3faffaf29403f681e4053c2f3bef2`, based on
`60dc9aeb15e306e3d64abd0e76c5a455540402f7`, was squash-merged at
2026-09-11T08:57:18Z as `413997c938de86daa88dc626f70389c5b84af36a`.
Both trees are `d34dbce5afd853456a3f7023a10b9a4f4eb7f366`. The separate clean
main worktree was fast-forwarded to that identical protected result; local main
and origin/main matched. No force, bypass, settings change or unrelated worktree,
stash, data or container cleanup was used. #94 closed and #48 was reconciled.

## Exact evidence

Complete local certification passed in 8,273.235 seconds (2h17m53s): 8,291
Python tests (4,503 unit and 3,788 PostgreSQL), 64 frontend tests, all ten gates,
eight isolated databases and 90.62% combined branch-aware coverage. Its nine
Python reports have zero failures, errors or skips. The receipt, reports,
selection manifests, logs and coverage were preserved outside the disposable
certification directory, and its eight databases were removed.

[Hosted exhaustive acceptance](https://github.com/martonpornoi/maru/actions/runs/34567816857)
passed on that exact head, including all sixteen PostgreSQL jobs, all quality
gates, combined coverage, Full CI gate and the required PR gate.
[CodeQL](https://github.com/martonpornoi/maru/actions/runs/34567817545) also
passed. The fresh pre-merge state was clean/mergeable with no unresolved review
conversations and unchanged main. Merge used the exact expected head.

Independently downloaded hosted artifacts contain seventeen Python reports,
8,291 tests and zero failures, errors or skips. The sixteen selection manifests
contain all 3,788 integration cases exactly once. Four parameterized case names
include collection-time generated UUIDs in the existing admin edition-context
and invitation-header tests; their definitions were inspected rather than
misrepresenting their raw node IDs as identical across machines. No test was
excluded. Local and hosted XML coverage agree on 64,206/68,844 covered lines and
13,114/16,476 covered branches, yielding the same combined 90.62% measure.

Hosted workflow latency was 2h58m16s. Database jobs ranged from 31m04s to
111m47s, all within the unchanged per-job limit and eight-job concurrency cap.
This safety/runtime/history change used exhaustive acceptance, not a routine
path benchmark. No hosted rerun, timeout increase, split-run exception or
threshold reduction was used.

The earlier candidate's failed unit/provisioning inventories and stopped
unfinished database work remain documented in the
[certification corrections](2026-09-11-release-source-certification-corrections.md).
That attempt never received a success receipt. Corrected focused recovery runs
and the later complete exact-head acceptance are separate evidence.

## Resulting boundary and next action

Programme now owns accountable exact fit/no-staffing evidence; Scheduling
collects every release category through independent current owner boundaries.
This remains dormant preflight, not persisted approval or a released timetable.
Native child [#96](https://github.com/martonpornoi/maru/issues/96) owns independent
approval, exact release warnings, mandatory artifact validation and atomic
publication/safety/privacy invalidation. Outputs, continuity, guided setup and
integrated acceptance follow. Genuine human acceptance remains open in #92.
No profile, route, runtime writer, production use or excluded-module side effect
is activated by this delivery.
