# Scheduling hosted timing repair

- Date: 2026-09-07
- Scope: Issue #81 / PR #82; NFR-001, NFR-002, NFR-003; ADR 0089
- Status: Bounded repair prepared; new-head full acceptance and merge pending

## Verified input evidence

Clean candidate `d22a267b8c5c7117208979e27fd02effd7190a57`, tree
`afb652cbb10a7108233bfb6526c7b547ebd7b20b`, passed default eight-shard
`scripts/certify.ps1` at `2026-09-07T09:53:25.0808363+00:00`. It passed
6,539 Python tests, 33 frontend tests, every non-database quality gate and the
unchanged combined 90% branch-aware coverage gate. All eight isolated local
integration suites were complete and passing without skips. The local receipt
is contributor evidence, not a hosted attestation.

The same head's
[hosted acceptance run](https://github.com/martonpornoi/maru/actions/runs/34108685975)
completed PostgreSQL shards 1, 2, 3, 5, 6, and 8. Shards 4 and 7 were cancelled
at the existing 120-minute limit, with cancellation rather than an assertion
failure in their logs. All non-database jobs and
[CodeQL](https://github.com/martonpornoi/maru/actions/runs/34108683584) passed.
The failed aggregate `PR gate` remains authoritative; this head was not merged.
The candidate's protected base was
`7ef234b20867c13674999f5cfc0e47fd65039716`.

## Repair and measurement contract

The complete local reports contain 208 integration files and 3,376 integration
cases; the separate unit suite contains 3,163 cases. The successful hosted
artifacts contain 152 complete files. A native-only refresh balanced estimated
local shards at approximately 5,161 seconds, but one proposed shard already
contained approximately 6,981 seconds of measured hosted work plus unobserved
files. Therefore the repair does not assume that native seconds equal hosted
seconds.

ADR 0089 permits conservative cost calibration. Each successful hosted file
must match its complete baseline testcase identities. The largest matched
job-group hosted/local ratio, approximately **1.460200**, scales unobserved
baseline files. Observed weights are at least both measured durations. Exact
inventory coverage, deterministic ordering and millisecond rounding are
enforced before writing the map.

Two hosted measurements were explicitly excluded because collection-generated
UUID values appear in their parametrized testcase names:

- `tests/integration/test_page10_account_invitation_api.py` (42 baseline and
  hosted cases, two unstable identities; successful hosted shard 6).
- `tests/integration/test_admin_edition_context.py` (22 baseline and hosted
  cases, two unstable identities; successful hosted shard 8).

No test or baseline file was excluded, changed, normalized or skipped. These
two files use conservative fallback weights. Whole report completion is
validated before measurement exclusions; default mismatched-identity rejection
remains strict. Reproduce with complete reports and both exact-head flags,
plus one `--exclude-hosted-file` flag for each path above. Original reports,
receipt and derived maps were preserved outside the next certification's
disposable `.local-ci` directory.

The resulting eight shards contain 20, 26, 26, 27, 28, 26, 27, and 28 files.
Their calibrated costs range from **6,703.344 to 6,703.508 seconds** (about
111.72 minutes). These are estimates, not an observed speedup or a guarantee
against runner variability. All 208 files remain whole and serial, each exactly
once. Eight jobs, the 120-minute fail-stop, database isolation, fail-fast
policy, full-acceptance routing and the 90% combined coverage requirement are
unchanged. No workflow, runner, repository setting or production data changed.

## Verification and remaining work

The focused timing-updater and shard-runner group passed **49 tests**. New
coverage rejects different heads, mismatched or partial cases, split files,
duplicates, failed/skipped/incomplete reports, invalid durations, unknown or
all-observation exclusions, orphaned CLI flags and incomplete inventory. It
also proves deterministic conservative weighting, whole-job group ratios,
unit-report separation and unchanged direct aggregation. NumPy docstring
validation passed for the updater.

The complete database-free suite passed **3,199 tests in 13.23 seconds**.
Ruff format/lint, NumPy and semantic docstrings, maintained documentation
validation and whitespace checks passed. These are focused pre-certification
results, not a substitute for the repaired clean head's full acceptance.

New-head complete local certification, independent hosted acceptance, protected
squash, issue reconciliation and local-main synchronization remain required.
Do not rerun the failed head without this repair or describe a projected
balance as accepted. After delivery, continue the accessible timetable editor
and the remaining #48 sequence. Both current adoption manifests remain
unchanged; no Programme profile, route, UI, API, worker or release is activated.
