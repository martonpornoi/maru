# Programme host protected delivery

Date: 2026-09-07
Issue: [#79](https://github.com/martonpornoi/maru/issues/79), child of
[#48](https://github.com/martonpornoi/maru/issues/48)

## Delivered boundary

[PR #80](https://github.com/martonpornoi/maru/pull/80) squash-merged at
2026-09-07T01:05:34Z as `7ef234b20867c13674999f5cfc0e47fd65039716`.
It delivers ADR 0087's explicit Programme host/co-host relationships,
person-owned confirmation and deliberately shared per-item availability.
The [implementation checkpoint](2026-09-06-programme-host-confirmation-and-availability.md)
retains the detailed contract, focused checks and initial recovery repair.

## Exact evidence

The clean candidate was `92dd4bb25c429736c7594d32d9bd5c2db29245b7`.
Complete local certification succeeded at 2026-09-06T22:59:04Z with 6,041 Python
tests, 33 frontend tests, eight isolated PostgreSQL shards and all unchanged
quality, security, schema, documentation and branch-aware coverage gates.

[Hosted full acceptance](https://github.com/martonpornoi/maru/actions/runs/34065746000)
passed all eight PostgreSQL shards, combined coverage, quality checks and the
aggregate `PR gate` at 2026-09-07T01:04:41Z.
[CodeQL](https://github.com/martonpornoi/maru/actions/runs/34061604993) passed
on the same exact head. Hosted PostgreSQL elapsed times were 87m54s, 73m54s,
79m14s, 117m00s, 89m30s, 95m55s, 119m19s and 112m28s for shards 1 through 8.
No hosted rerun or timeout/coverage-policy change was required. The first local
attempt's historical-downgrade expectation repair was included and verified
in the final certified commit; production guards were not weakened.

GitHub reported a ready, mergeable, clean PR with no unresolved review threads.
Protected squash merge used `--match-head-commit` for that candidate. The
fetched squash tree and certified candidate tree both equal
`5efefe7da7c243e4ae250819f2ddc8432ab74a68`. The clean separate main worktree was
fast-forwarded, and local main, origin/main and the protected result matched.
Existing feature branches, both worktrees and unrelated stashes were preserved.

## Continuation and limits

Issue #79 closed automatically. Umbrella #48 remains open, with its integrated
acceptance boxes unchecked. The next native child is
[#81](https://github.com/martonpornoi/maru/issues/81), Scheduling candidates,
conflicts and governed Venue binding. The user's authorization covers all
remaining children sequentially, single-agent, through protected delivery.

Hosting does not infer proposal consent, create attendee or Workforce records,
mount a route, activate a profile, publish timing or approve production use.
Hosted PostgreSQL remains slow and the final shard was close to its unchanged
120-minute limit. This evidence is not a whole-suite speedup claim or authority
for an unrelated optimization project.
