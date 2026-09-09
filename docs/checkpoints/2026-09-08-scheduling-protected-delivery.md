# Scheduling protected delivery

- Date: 2026-09-08
- Issue: [#81](https://github.com/martonpornoi/maru/issues/81)
- Pull request: [#82](https://github.com/martonpornoi/maru/pull/82)
- Exact tested head: `85db2e16a453355b534dfb2e37e6695bb858e635`
- Reviewed base: `c0cf5a24d7593744bbb52ad0f9293deaf21e393a`
- Protected squash: `ec0d2474810e27b72c9dbabcc1d210222e4989af`
- Merged: 2026-09-08 11:49:27 UTC

## Delivered boundary

Scheduling owns versioned service days, stable occurrences, immutable draft
alternatives, explainable current conflict evidence and explicit reciprocal
Venue reservations under ADR 0088. A draft is not host consent, room
reservation, independent physical approval or a published Programme timetable.
All fifteen Scheduling relations and the Venue source-binding relation remain
runtime SELECT-only. No existing manifest, profile, navigation, route or release
was activated. ADR 0091 reconciles the integrated CI policy with ADR 0090.

## Verification

Exact-head exhaustive local certification passed 6,887 Python tests (3,511
database-free and 3,376 PostgreSQL), 33 frontend tests, all ten quality gates,
eight isolated databases and 90.34% combined branch-aware coverage. Elapsed
time was 108m19s; the version-two receipt completed at 09:15:01 UTC.

The earlier interrupted local attempt produced no complete receipt. Its
partial evidence was archived rather than treated as passing. A separate
one-shot recovery completed the unchanged certifier and exact-head push;
complete reports, logs and raw coverage were preserved outside `.local-ci/`.
The eight task-owned certification containers were removed after completion.
Unrelated persistent containers, worktrees and stashes were preserved.

[Fresh hosted acceptance](https://github.com/martonpornoi/maru/actions/runs/34208969678)
passed all sixteen PostgreSQL jobs, with at most eight concurrent jobs and
unchanged 120-minute per-job limits. Individual jobs ran 42m02s–72m44s; total
PostgreSQL job time was 964m32s and workflow creation through green `PR gate`
was 142m14s. Hosted combined coverage was also 90.34%.
[CodeQL](https://github.com/martonpornoi/maru/actions/runs/34208966095)
passed all three configured languages and its native gate. These are
exhaustive-acceptance costs, not a measured routine-path speedup.

Merge verified the exact head, clean/up-to-date mergeability, all required
checks and no unresolved conversations. The protected squash tree equals the
certified head. The separate clean main worktree was fast-forwarded and local
`main`, `origin/main` and the protected result matched exactly. Issue #81's
acceptance checklist and #48's native child/checklist were reconciled; #48 and
all thirteen integrated acceptance items remain open. The temporary #82
check-in was paused after delivery, and no other reminder was recreated.

## Next boundary

The next mandatory child is the accessible timetable editor, followed by
Workforce staffing, independent approval/atomic release, on-site continuity,
guided surfaces/runtime activation and the complete synthetic journey.
Protected delivery of this kernel is neither adoption nor production approval.
