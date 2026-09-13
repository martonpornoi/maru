# Programme continuity protected delivery

Date: 2026-09-13
Issue: [#107](https://github.com/martonpornoi/maru/issues/107), under #48
Pull request: [#111](https://github.com/martonpornoi/maru/pull/111)

## Exact protected outcome

- Certified head: `4e22719b43800528354893b109de4a6105f7a639`.
- Base: `05a53ffbab6d9c233dfdf293172457ee2edfe536` (PR #110).
- Protected squash: `fa155a143945b4d7533d0b4f8fa6f9cbd826bfcf`.
- Merge: 2026-09-13 21:34:46 UTC; #107 closed one second later.
- Head and squash tree: `902d4c00a27a90a50c8e9951904014be8e92ab0e`.
- Pre-merge state: exact head/base, clean local tree, CLEAN/MERGEABLE, no review
  threads and no further review-thread page, green PR gate and CodeQL.
- Merge used `--squash --match-head-commit` with the certified full head.

The clean main worktree at `C:/Users/TheMw/Documents/Maru-umbrella-issue-form`
was fast-forwarded only. Local main and origin/main both equal the protected
squash. The unrelated detached issue96 worktree, other stashes and Docker
resources were not changed. Next branch `codex/programme-guided-journey` starts
from that exact origin/main for #108; no direct main push or bypass was used.

## Local evidence

The first exact candidate `23a5ec2` stopped after package/dependency checks on
one native-test formatting difference. It produced no certification receipt and
ran no PostgreSQL. The formatter-only repair and its checkpoint were committed
before one complete rerun. No failure was relabelled as passing evidence.

`scripts/certify.ps1 -Base 05a53ffbab6d9c233dfdf293172457ee2edfe536` then passed
all eight retained development gates on the final clean head in **922.107 seconds
(15m22s)**, completing at 21:04:30.0202873 UTC. Pinned pnpm 11.9.0 and CI=true
were selected before invocation; the ambient runtime's pnpm 11.19.0 was not used.

- Python units: **5,788 passed in 36.12s**, two pre-existing URLField warnings.
- Frontend: all **64 tests** passed, with type/build/generated-asset checks.
- Strict mypy: all **587 source files** passed.
- Packaging: wheel/sdist and 178 package assets passed integrity checks.
- Ruff, NumPy/semantic docs, 486 Markdown files/four skills/215 requirement IDs,
  warning-fatal Sphinx, static Django/generated contracts and dependency audits
  passed. OpenAPI enum-naming warnings remain, with zero generation errors.

The schema-4 receipt is explicitly `postgresql_deferred`, not full certification:
zero databases, `postgresql_executed=false`, null combined coverage and timing
headroom. Receipt SHA-256:
`d341a2ece9dc50df13cfeb636e6e5703a9585cf7bc11bdb385ce004e2d617d6d`.
Receipt, plan, complete unit report and package artifacts were preserved under
`.tools/certification-evidence/issue107-4e22719-deferred/`; the archived receipt
hash was verified equal before push. PR #110's separate archived receipt hash
was also verified before its disposable `.local-ci` workspace was replaced.

## Hosted evidence

[Pull request workflow 34782753886](https://github.com/martonpornoi/maru/actions/runs/34782753886)
ran 21:05:28 through 21:33:49 UTC: **28m21s** workflow latency.

- Unit job `103792664115`: **1m24s**; completed log independently confirms
  **5,788 passed, two warnings, 64.71s** test duration.
- Quality job `103792664098`: **27m54s**; strict mypy 587 files, 30 auxiliary
  checks, successful Sphinx output and all 64 frontend tests were observed in
  the completed job log. Documentation was the long stage, not PostgreSQL.
- PR gate `103796568557`: green in **3s** on the exact head.
- [CodeQL workflow 34782751669](https://github.com/martonpornoi/maru/actions/runs/34782751669):
  Actions, JavaScript/TypeScript and Python analyses passed; aggregate passed.
- Native risk-selected/targeted jobs were explicitly skipped under ADR 0100.
  No hosted repair, rerun, changed timeout or weakened check was used.

The unsupported local watch flag was removed before using the installed CLI's
ordinary watch. Completed unit-job timing came from the jobs/logs endpoint because
the whole-run log command was unavailable while another job still ran. Neither
CLI limitation was a test failure or a reason to restart acceptance.

## Reconciliation and limits

#48's exact #107 delivery-decomposition box is checked and this delivery is
recorded; no integrated acceptance box changed. #107 has an evidence comment.
#108 explicitly owns ordinary authorized connections into notice and continuity
surfaces, without UUID discovery or key provisioning in routine department forms.
#92 contains unchecked remaining continuity viewport, keyboard, real zoom,
screen-reader/accessibility, native print and operator-comprehension tasks. #102
records the three maintained, unexecuted owner-authorized native cases.

The bounded synthetic preview and its one browser tab were stopped/closed after
rehearsal; no other browser tab, application or database container was stopped.
No real key was provisioned. ADR 0103's dated signed fallback does not activate
Programme, create a write relay, provide a full-profile archive, erase copies or
prove current authority/unseen-change absence. #104 remains the governed notice
workflow. #108's dormant connected journey is next; final promotion and #48
closure still require #102/#97/#92/#109 evidence. Existing production gates remain.
