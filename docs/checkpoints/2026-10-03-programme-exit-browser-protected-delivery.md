# Programme continuity and exit-browser repair: protected delivery

Date: 2026-10-03. Scope: #205, supporting #92/#109/#108/#48.

## Delivered state

[PR #206](https://github.com/martonpornoi/maru/pull/206) squash-merged at
06:10:04 UTC as `1fa3bb8359fde77e5eebdfd70fde379c4f2d1ae3`, closing #205.
Its tree equals certified head `722462ec12e520d79f66d4eb093b4935a3313a76`:
`aec03cb9d68137ce869216cc51449008e1ea9d5f`. The clean main worktree was
fast-forwarded to that exact protected result; unrelated worktrees, branches,
stashes and resources were preserved.

The delivered changes provide an encrypted, exact-scope public continuity-policy
handoff and same-origin referrer policy on stop/archive HTML, with genuine Django
CSRF regression coverage. Private archive downloads retain no-referrer. The
scoped migration-test cleanup repair retains native refusal checks and unchanged
history selection, timing budgets and production migrations. No production profile,
route, authority grant or security policy was changed. See the
[browser checkpoint](2026-10-02-programme-exit-form-browser-repair.md) and
[timing checkpoint](2026-10-02-programme-exit-certification-headroom.md).

## Exact local acceptance

Ordinary `scripts/certify.ps1` passed all ten gates at clean `722462e`, with
`CI=true`, pinned pnpm 11.9.0, all PostgreSQL history and the unchanged 90% combined
coverage minimum. Its schema-3 success receipt records **15,215.764 seconds
(4h13m36s)**, completing on October 3 at 00:52:34 UTC. The one-shot worker exited
zero; no interrupted or previous-commit result was reused.

- **18,570 Python cases:** 13,489 units and 5,081 native cases across 71 shards,
  with zero failures, errors or skips; **103 frontend cases** also passed.
- Combined line/branch-aware coverage was **91.73%**.
- All 71 native records passed headroom and owned-container cleanup, at most
  eight databases concurrently. Slowest local shard 61 took **49m03s**, with a
  conservative projection of **83m34s** below the unchanged 90-minute ceiling.
  Repaired shard 34 passed all 78 cases in **37m50s** in the real pool.
- All 5,043 local-ci artifacts and three worker files were preserved and
  individually SHA-256 compared. Independent readback found no owned certification
  container or browser fixture remaining. The failed `eb620d4` artifacts remain
  separately preserved, never promoted to a success receipt.

## Independent hosted acceptance and merge

[Hosted run 37084838258](https://github.com/martonpornoi/maru/actions/runs/37084838258)
passed from 01:06:56 to 05:34:44 UTC, **4h27m48s**, at exact head `722462e`.
All 71 PostgreSQL jobs passed. All 73 full-run artifacts were retained; all 72
Python XML reports independently total **18,570 cases**, with zero failures,
errors or skips. Coverage XML records 84,907/90,258 lines and 18,268/22,218
branches, **91.73%** combined, with no lowered threshold.

Native jobs ranged **6m21s–58m52s**, median **18m45s**. Slowest shard 69 retained
**61m08s** before the unchanged two-hour timeout. Repaired shard 34 took
**41m34s**, leaving **78m26s**. These are actual measurements, not future guarantees.

Exact-head PR gate check 111138250587 and CodeQL protection check 111092915909
passed. [CodeQL run 37084836468](https://github.com/martonpornoi/maru/actions/runs/37084836468)
passed all three language analyses. Current protection remained active, with no
bypass actors. Up-to-date CLEAN/MERGEABLE state and zero review threads were
verified before `--match-head-commit` squash. No administrative bypass, security
waiver, alert dismissal or check-policy change was used for delivery.

## Reconciliation and remaining gates

#205's final acceptance checkbox and its supporting #48 item were reconciled;
delivery evidence was added to the PR and #205/#48/#92/#109. The approved
`finish-maru-205` temporary check-in was deleted after verified merge and main sync.
No replacement schedule was created.

#48/#92/#109/#108 remain open. Native print, timely actual-browser offline use
and archive/custody browser interactions remain distinct from the successful
assistant-operated stop rehearsal. Expired download evidence is not a live
offline pass. No new archive authority was granted. Independent-person,
specialist screen-reader and operational-owner acceptance, trusted HTTPS for a
future cross-computer pilot and separately verified final profile promotion
cannot be inferred from green CI or assistant-controlled separate accounts.

This post-merge checkpoint is follow-up documentation, not part of the certified
tree or an inherited certification receipt for a future change. Continue from
protected `1fa3bb8` and carry the record in the next coherent acceptance bundle.
