# Named reviewer management protected delivery

Date: 2026-09-14. Issue #108 within #48; PR #123.

Protected squash `d8fc19bae95ba683f90ed0d9422791400ac186e6` merged at
16:21:52 UTC. Its tree `89b8f1cbd0ee55dd843d950420dc38c59813c50f` equals
certified head `f0a0838bb511ba2005c767b382c47c455765d359`. Clean local main
and origin/main were fast-forward synchronized to that squash. The detached
issue96 worktree and both unrelated stashes remained unchanged. The new reviewer
workspace branch starts from this verified protected result.

## Exact evidence

- Fresh canonical local certification: eight retained gates, **1008.436 seconds
  (16m48s)**, completed 15:50:11.7617670 UTC. **6,887 units in 41.72s**, three
  existing URLField warnings; JUnit reports zero errors, failures or skips.
- Schema-4 receipt: `postgresql_deferred`, development checks passed, zero
  database instances and null combined coverage/timing headroom. Receipt SHA-256
  `ba2c253a6d5986a6f95be23f6d5b446741f4b6a142e6968edf673dc9ccc22d52`.
  Policy SHA-256
  `36354f14eabc58fa31ae7b2d7ec0e9a5e7afb8ab2c4b48bfa02a1edeff5f528d`.
  Receipt, plan, complete unit report and both packages were hash-verified into
  the ignored `issue108-f0a0838-deferred` evidence archive before reuse of local CI.
- [Hosted PR run 34864982078](https://github.com/martonpornoi/maru/actions/runs/34864982078)
  passed at the exact head. Hosted units: **62.29s** (1m28s job); frontend:
  **85 tests in six files**. Quality: **27m52s** (15:52:33–16:20:25 UTC).
  Documentation: **25m45s** (15:53:38–16:19:23). Workflow: **28m21s**.
  Exact-head PR gate passed 16:20:34 UTC; all
  [CodeQL analyses](https://github.com/martonpornoi/maru/actions/runs/34864979384)
  passed. No hosted repair, rerun, policy exception or timeout increase.
- Before squash, refreshed checks confirmed PR gate success, ready/CLEAN state,
  exact head/base and no review threads. An initial local merge guard rejected
  an older pending watcher snapshot; fresh direct checks and watcher completion
  proved success before the authorized merge was retried. No guard was bypassed.

The first implementation head `00aef0708ba3c087727b00ba1ace4fc4ffd49a10`
failed local documentation reachability before Sphinx because its page contract
lacked a hidden toctree entry. The corrected clean head above passed a complete
fresh certification; no failed or split-run receipt is claimed. Observed hosted
quality margin was **2m08s**, not guaranteed future headroom; #113 remains open.

## Scope and remaining gates

The [candidate checkpoint](2026-09-14-programme-reviewer-management.md) records
the dormant exact-Department roster, signed known-person selection, explicit
assignment/removal, safe original-intent recovery and bounded synthetic browser
evidence. No schema/profile/production route/runtime privilege changed.

One maintained native scenario remains unexecuted
[#102 debt](https://github.com/martonpornoi/maru/issues/102#issuecomment-5666425405);
full human acceptance remains
[#92 debt](https://github.com/martonpornoi/maru/issues/92#issuecomment-5666425101).
Only named management is checked complete in #108. Reviewer/moderator/decision/
conversion, reference/file choices, connections and setup remain. A separate
database-forbidden HTTP adapter diagnosis reproduced mutable-email host invitation
retry rebasing/blockage; it is explicitly unchecked in #108, with no native
wrong-person mutation claim. See issue comment 5666828850.

#108 and #48 stay open. #102 restoration, #97 logical recovery, #109 integrated
and #92 genuine human acceptance still precede final Programme promotion.
