# PostgreSQL current-path benchmark and coverage review

Date: 2026-09-07
Requirements: NFR-001, NFR-002, NFR-003, NFR-008
Decision: ADR 0090
Issue: [#83](https://github.com/martonpornoi/maru/issues/83)

## Measured diagnostic, not merge acceptance

The clean main-based candidate `2a0dda7f7307925135b7c2bfe401feb3f24829bb`
ran `scripts/certify.ps1 -Mode CurrentDiagnostic` against exact base
`7ef234b20867c13674999f5cfc0e47fd65039716`. Its receipt recorded
`diagnostic_success` at `2026-09-07T17:41:32.9661881+00:00`, with 899.281
seconds total elapsed time (14m59s), including database startup and reporting.

All 2,981 unit tests and 3,002 current-schema integration tests passed, with no
failures, errors or skips. Eight pinned PostgreSQL containers supplied isolated
databases; the certifier removed only those owned containers afterwards. The
complete integration inventory contains 3,126 cases on this baseline, so 124
historical cases were intentionally outside the diagnostic scope. Non-database
quality gates were also outside it.

| Isolated shard | Passing cases | JUnit elapsed seconds |
| --- | ---: | ---: |
| 1 | 827 | 866.76 |
| 2 | 340 | 768.34 |
| 3 | 284 | 787.90 |
| 4 | 494 | 791.07 |
| 5 | 294 | 772.06 |
| 6 | 265 | 765.66 |
| 7 | 307 | 762.60 |
| 8 | 191 | 509.80 |

These are actual local observations, not hosted runner billing or proof that
the complete historical suite is fast. The initial 20–35-minute routine hosted
feedback estimate remains provisional. Comparing that estimate with the prior
two-hour limit suggests approximately 70–85 percent less ordinary PR waiting;
no comparable exact-revision hosted speedup has yet been measured. High-risk
changes and releases still pay for exhaustive history. The new Scheduling work
in PR #82 is not part of this main-based benchmark.

## Coverage correction discovered in final review

The original XML reports 57,936/62,659 lines and 11,524/14,898 branches covered:
89.56 percent combined. The existing zero-decimal coverage setting rounded that
value to 90 and returned success. The runner also initialized Django before
pytest-cov started, producing a `module-not-measured` warning. Thus the original
receipt is truthful about the command result but does not establish an
unrounded 90-percent result or final acceptance of the redesigned harness.

Local and hosted PostgreSQL execution now start through
`coverage run -m scripts.run_postgres_acceptance`, without a nested pytest-cov
recorder. The shared report precision is two decimals; the 90-percent threshold,
branch recording and exclusions are unchanged. A fresh-process regression
checks actual Programme application startup recording without a database, and
another rejects the original rounded shortfall. This improves measurement, not
the application's behavior or the selected test assertions.

The 144 focused policy, workflow and classifier cases pass after the correction,
including the fresh-process startup regression. Ruff and maintained Markdown
validation pass. These focused checks do not replace PostgreSQL execution.

Original receipt, reports, logs, coverage XML and raw combined data were copied
to a uniquely named temporary archive before any replacement run. Generated
evidence remains ignored; only this reviewed summary belongs in Git. Corrected
current-path verification, exhaustive final-commit local certification, hosted
acceptance and protected merge remain pending. Neither #83 nor PR #82 is
delivered by this checkpoint. The user-requested temporary #83 reminder was
deleted and must not be recreated without authorization.
