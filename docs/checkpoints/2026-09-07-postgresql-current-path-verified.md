# Precise current-path PostgreSQL acceptance

Date: 2026-09-07
Scope: CI issue #83; ADR 0090; NFR-001/002/003/008.

The fresh `CurrentDiagnostic` run for
`80f36ad713a6c5d5e3589dee22d9b8fe344d2477`, based on protected main
`7ef234b20867c13674999f5cfc0e47fd65039716`, completed at
2026-09-07T19:19:37.3225212Z with a `diagnostic_success` receipt.

| Evidence | Observed result |
| --- | --- |
| Elapsed local time | 957.955 seconds, 15m58s |
| Unit tests | 3,224 passed |
| Current-schema PostgreSQL tests | 3,002 passed |
| Total Python tests | 6,226 passed |
| Failures / errors / skips | 0 / 0 / 0 |
| Isolated PostgreSQL instances | 8 |
| Combined branch-aware coverage | 90.02% at the unchanged 90.00% gate |
| Historical cases deferred by this diagnostic | 124 |

Coverage starts before the PostgreSQL runner initializes Django. The original
rounded-coverage shortfall is resolved by current-behavior tests, not a lower
threshold or changed exclusions. The real fresh result agrees with the earlier
development estimate; the latter is no longer the acceptance evidence. See the
[coverage follow-up](2026-09-07-postgresql-current-coverage-follow-up.md) for the
regression scope and reviewed cache/nightly safeguards.

The diagnostic retains 3,002 of 3,126 PostgreSQL cases, approximately 96%, and
does not execute the non-database quality gates. It is neither exhaustive local
certification nor hosted acceptance. The 20–35-minute hosted routine estimate
remains unmeasured; comparing this local diagnostic directly with older hosted
78–102-minute jobs would mix platforms, revisions and acceptance scopes.

All eight diagnostic-owned containers were removed normally. The reports,
selection evidence, receipt, combined coverage data and complete log were
archived outside the next certification artifact directory. Existing persistent
and unrelated resources, stashes, worktrees and PR #82 remain untouched.

Final exhaustive certification must cover all 6,350 Python cases, quality gates
and frontend checks, followed by exact-head hosted acceptance and protected
delivery. No pull request or merge is claimed by this checkpoint. The temporary
app reminder remains deleted.
