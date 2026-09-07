# Risk-based PostgreSQL acceptance

Date: 2026-09-07
Requirements: NFR-001, NFR-002, NFR-003, NFR-008
Decision: ADR 0090
Issue: [#83](https://github.com/martonpornoi/maru/issues/83)

## Outcome and boundary

The owner approved separating current-schema PostgreSQL behavior from exhaustive
historical migration compatibility testing after PR #82 timed out three jobs.
This independent branch starts from protected main
`7ef234b20867c13674999f5cfc0e47fd65039716`; PR #82 and its Scheduling work remain
preserved separately. No application behavior, migration, guard, assertion,
coverage exclusion, runtime profile or production deployment changes.

The initial inventory contains 265 work groups: 179 current-file groups and 86
historical groups. Actual full collection has 3,126 cases; the current-only
collection retains 3,002 and defers 124 historical cases. Current authorization,
raw SQL, concurrency and readiness cases in mixed files remain on every code PR.
Parameterized variants stay together; four shared historical baselines remain
indivisible. Independently repeatable invitation RSA-key generation is explicitly
reviewed separately from shared database setup.

Global safety/harness changes, including this change and PR #82, still require
exhaustive acceptance. Domain schema changes add owner/dependent history and
committed full-graph recovery. The actual Django graph resolves the scope before
hosted fan-out; unknown nodes fail conservatively to all history. Eight database
jobs run concurrently at most; sixteen exhaustive hosted groups provide per-job
headroom without increasing the 120-minute timeout. Routine and local runs use
eight groups. No cases run concurrently in one database.

## Estimate provenance, not new acceptance

Initial weights use matching test observations from PR #82's successful local
receipt for `4e6eb1bde8a681b6d5cebb0cdbeaac2bbbc77f68`, completed at
`2026-09-07T14:18:08.0122193+00:00`. This is explicitly a cross-revision planning
input, not proof that this main-based candidate has passed. Original receipt,
reports and old timing map were copied into an independent uniquely named
temporary evidence directory before any new certification could replace them.

Matching groups total 40,585.032 recorded seconds: 6,100.365 current and
34,484.667 historical (about 85 percent historical). Eight current groups project
762.445–762.696 seconds each. Sixteen exhaustive groups project
2,536.418–2,536.796 seconds each, in at least two hosted waves. These sums include
the setup/teardown attributed by the original JUnit reports, but new processes
and regrouping change setup cost. Neither wall time nor runner billing is obtained
by simply dividing case durations. Shared-baseline groups retain their entire
recorded setup/teardown cost.

The preliminary routine feedback estimate is 20–35 minutes rather than a
two-hour timeout: roughly 70–85 percent less waiting versus the old exhaustive
path. It does not promise that formerly database-free frontend checks speed up,
that high-risk/release acceptance becomes cheap, or that the remaining complete
suite has no performance work left. Verify coverage and measure actual execution
before treating the estimate as an achieved improvement.

## Initial verification and remaining work

All 2,974 unit tests passed in 14.97 seconds after the first policy tests were
added. Complete and current-only real pytest collection agree with the explicit
inventory. Ruff, strict NumPy docstrings, semantic docstrings and maintained
Markdown validation passed at that stage. These are development checks, not
final exact-head local or hosted certification.

Current-only execution/coverage measurement and exhaustive exact-head acceptance
remain to be performed. The local diagnostic mode reports `diagnostic_success`
and only the gates actually run; it cannot certify a higher-risk diff. Nightly
run-history selection keeps failures actionable without starting blind retries.
Releases always recertify their exact current-main source. No GitHub settings,
ruleset bypasses, publishing authority, app heartbeat or unrelated Docker cleanup
are introduced by this task.
