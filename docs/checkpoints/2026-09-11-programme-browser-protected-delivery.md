# Programme browser checks: protected delivery

Issue [#87](https://github.com/martonpornoi/maru/issues/87) closed through
[PR #90](https://github.com/martonpornoi/maru/pull/90). The protected squash is
`d9dcd5074af494689912dc1524095b85343f5f2c`, merged on 2026-09-10 at
22:46:01 UTC (2026-09-11 locally). Its tree equals the accepted candidate
`cb131c8c10ee46f12702dada1248204676b3670d`; the exact base was
`dca412e97dfa40371e01db3222105f87cf9d4562`. Clean local main was fast-forwarded
to the protected merge and verified equal to origin/main.

## Bounded browser evidence

The [assisted observations](2026-09-10-programme-browser-assisted-observations.md)
record the maintainer's Chrome 152.0.7977.83 (Official Build), 64-bit checks:
native Cancel retained entered values, deliberate OK reset the pending form,
the populated inventory/board remained readable and usable at genuine 200%
browser zoom, Tab visibly highlighted fields and kept them in view at 200%,
and board/item interaction remained usable with Windows Animation effects off.
The maintainer chose to retain that setting; do not restore it automatically.

Browser-control timeouts prevented fresh automated preference/viewport readback.
The [earlier attempt](2026-09-10-programme-browser-acceptance-attempt.md) separately
records exact field/retry retention after Cancel and an unverified discard
attempt. Neither account is rewritten to claim stronger evidence. The finite
assisted fixture closed normally; its 33m25s duration measures the interactive
lease and cleanup, not automatic UX acceptance or test-suite performance.

## Exact-candidate verification and approved exception

The required local certification command ran on the clean candidate with
current history selection. All 7,810 Python tests passed: 4,254 unit and 3,556
current PostgreSQL tests across eight isolated databases, with zero failures,
errors or skips. The slowest group passed 1,073 tests in 30m03s.

The command nevertheless failed because pnpm refused an interactive
modules-directory question without a TTY. No Python test failed. The maintainer
explicitly approved a one-off split-run acceptance rather than repeating the
passing database work. This was not a repository-policy change or a waiver of
GitHub protection, and no successful certification receipt was fabricated.

On the unchanged candidate, `scripts/check.ps1 -SkipPythonTests` with `CI=true`
passed the non-database gates: locked dependencies and audits, package/legal
contracts, formatting/lint/type analysis, documentation validators and fresh
warning-fatal Sphinx, Django/API checks, generated-artifact parity, all 64
frontend tests (9.18s), and the frontend build. Ordinary unconfigured-local
environment and schema-enum warnings remained visible. Combining all nine
preserved coverage parts passed the unchanged 90% branch-aware gate at 90.38%.
The tracked tree stayed clean throughout recovery.

Original test reports, logs, coverage parts, recovery logs and an explicit
non-receipt result record are retained locally in the ignored evidence archive.
The PR description records the failed initial command, recovery and maintainer
exception rather than calling the original invocation successful.

Independent [hosted acceptance](https://github.com/martonpornoi/maru/actions/runs/34537090280)
passed classification, repository safety, documentation/quality and `PR gate`.
The quality job took 22m37s. Hosted PostgreSQL jobs were not selected for the
documentation-only diff. All three languages in
[CodeQL](https://github.com/martonpornoi/maru/actions/runs/34533248001) passed.
Before merge the exact head/base were current, merge state was CLEAN/MERGEABLE,
and there were no review threads. Squash merge used an exact-head guard.

## Cleanup and continuation

The assisted fixture and certification processes ended. Their exact disposable
containers were removed and verified absent; only synthetic unrecoverable test
data was removed. No unrelated worktree, stash, persistent database, container
or production data was touched. No automation was created or re-enabled.

#48 now marks #87 complete and retains every integrated acceptance checkbox as
open. Next is independent approval/atomic release and combined release-derived
personal/public/room outputs, followed by on-site continuity and guided
activation/integrated acceptance. No profile, route, runtime grant, screen-reader
acceptance or supported Programme-only deployment follows from this child.

The next clean branch starts from the protected merge. This post-delivery
checkpoint travels with the next bounded change; it is not presented as part of
the already merged candidate or its exact-head certification.
