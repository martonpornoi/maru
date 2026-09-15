# Guided Programme release workspace: protected delivery

Date: 2026-09-15
Parent: #108 under #48; both remain incomplete.

## Exact protected result

[PR #131](https://github.com/martonpornoi/maru/pull/131) squash-merged at
04:11:07 UTC as `6c1d437e7e9935f5716397aede13b59a2609f4c2`.
Certified head `bd247c8dc99978184e0c5ba16e87da24001812e1` and the protected
squash share tree `6b977a24b4d5cc09565271c69eb715ee23ad6d25`.
Clean local main and origin/main were fast-forwarded to that exact result;
the separate detached repair worktree was verified clean and left unchanged.

Fresh head/base, ready state, CLEAN mergeability, exact-head PR gate and all
CodeQL analyses passed before normal match-head squash. There were no review
threads and no additional page of conversations. No bypass, force update,
timeout change or hosted rerun was used.

## Actual verification

Clean exact-head local certification passed all eight retained development gates
in **1,082.490 seconds (18m02s)**. All **7,544 database-free units** passed in
**44.69s**, with the three existing URLField warnings and zero failures/errors/
skips. All **90 frontend tests** passed. Locked inputs, package inspection,
static/NumPy/semantic/Sphinx checks, Django/generated contracts, frontend build
and dependency security passed without tracked generated drift.

The schema-4 receipt explicitly reports `postgresql_deferred`, zero databases
and null combined coverage/headroom. Its SHA-256 is
`ed28f08039244774c1e3aca3c8fd20a6ee263a84e621c3f90bfeb8551dc55c82`.
Receipt, plan, JUnit, wheel and sdist are preserved under the ignored
`.tools/certification-evidence/issue108-bd247c8-deferred/`, with all five
source/copy hashes compared before the next certification resets its directory.

[Hosted workflow 34925891751](https://github.com/martonpornoi/maru/actions/runs/34925891751)
passed on the same head. Hosted units passed in **85.02s** (1m43s job), and all
90 frontend tests passed. Quality took **28m32s**, including **26m27s** for the
documentation step. Overall workflow latency was **29m36s**. The observed
**1m28s** quality margin is modest, not guaranteed; #113 retains this risk but
does not displace unblocked #48 implementation.
[CodeQL 34925889466](https://github.com/martonpornoi/maru/actions/runs/34925889466)
and the aggregate PR gate passed independently.

The earlier formatting-only canonical failure is retained in the
[repair checkpoint](2026-09-15-programme-release-workspace-certification-repair.md).
It produced no receipt. Fresh certification of the corrected head passed;
there was no split-run exception or reuse of the failed candidate as acceptance.

## Delivered boundary and continuation

The [release workspace](../product/page-contracts/programme-release-workspace.md)
provides labelled candidates, complete ten-category review, exact warning evidence,
independent approval/publication, source-independent withdrawal selection and
explicit retained history. Original pending intent reaches canonical receipt
recovery before private source refresh. No writer, schema, current profile,
production route, excluded-module side effect or CI policy was changed.

Four maintained native scenarios remain unexecuted #102 debt. Synthetic browser
observations remain component evidence only; #92 human and #109 integrated
acceptance remain open. #97 logical recovery and #102 exhaustive database/coverage/
timing restoration remain mandatory before activation or pilot use.

Only #108's nested release-workspace checkbox is delivered. Next, connect private
items, the canonical dormant timetable editor and release workspace through
independently admitted task navigation. Workforce, notice and continuity
connections, reference/file selection and viewing, accountable setup and final
gated promotion remain unfinished. No integrated #48 checkbox is completed here.
