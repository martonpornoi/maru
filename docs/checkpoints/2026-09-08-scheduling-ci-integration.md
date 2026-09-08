# Scheduling integration after protected risk-based CI delivery

- Date: 2026-09-08
- Scope: Issue #81 / PR #82; CI prerequisite #83 / PR #84; NFR-001/002/003/008
- Decisions: ADRs 0088, 0089, 0090 and 0091
- Status: CI prerequisite delivered; integration focused checks pass, full acceptance pending

## Delivered prerequisite

PR #84 merged through the protected squash flow as
`c0cf5a24d7593744bbb52ad0f9293deaf21e393a`. Exact candidate
`dfc775445d146ab86423544860e9a1726f0131f2` passed full local certification:
6,350 Python tests (3,224 unit and 3,126 PostgreSQL), 33 frontend tests, all
quality gates, zero Python failures/errors/skips and 90.20% combined coverage.
Its version-2 receipt records all history, eight isolated databases, base
`7ef234b20867c13674999f5cfc0e47fd65039716` and 5,722.153 seconds (95m22s).
The receipt, reports, logs and coverage were archived before another run.

[Hosted run 34161506336](https://github.com/martonpornoi/maru/actions/runs/34161506336)
passed all sixteen PostgreSQL groups, combined coverage at 90.20%, every quality
gate and the protected PR gate. Exact-head CodeQL passed. Individual database
jobs took 35m23s–63m08s, total database job time was 846m30s, and workflow
creation to PR-gate completion was 122m20s. At most eight database groups ran
at once. This proves job-limit headroom for that candidate, not a fast exhaustive
suite or a guarantee for the growing Scheduling graph.

Issue #83 is closed with its checklist reconciled. The clean existing main
worktree was fast-forwarded; local main, origin/main and the protected result
matched, and the squash tree matched the certified head. Other stashes,
worktrees and containers were preserved. No app reminder was recreated.

## Feature integration and timing provenance

The preserved Programme head was
`4e6eb1bde8a681b6d5cebb0cdbeaac2bbbc77f68`. It passed full local certification
but timed out three hosted jobs. It is not reused as new-head acceptance.
The delivered main is integrated without rewriting existing feature commits.
Scheduling commands, migrations and existing assertions are unchanged by this
integration. The four documentation conflicts are explicitly reconciled.

ADR 0091 reconciles the earlier whole-file calibration with the active risk
policy. The new Scheduling migration file has two independent historical
functions: empty normal reversal/recovery and a two-variant populated fence.
Its owners are Scheduling and Venues. All current Scheduling and owner-adapter
behavior remains in routine PostgreSQL acceptance. Real graph tests require
selection from either owner and from Programme prerequisites, with committed
whole-graph recovery retained.

Thirteen new group weights derive from complete local JUnit reports belonging
to successful exact head `d22a267b8c5c7117208979e27fd02effd7190a57`; its receipt
completed at `2026-09-07T09:53:25.0808363+00:00`. The retained eight reports
contain 3,376 passing integration cases with no failures/errors/skips. The
twelve new Scheduling/owner-adapter files contain 173 cases: 170 current cases
in eleven groups and three historical cases in two groups. Sum all JUnit case
durations, including setup and teardown; both fence variants contribute to one
weight. Verify relevant source is unchanged between that evidence revision and
the preserved feature head. Existing group weights remain unchanged.

These are cross-revision local cost estimates. The older whole-file runner did
not emit group selection JSON, so this is not presented as a group-native
refresh, authenticated attestation or measured new-head/hosted runtime. Normal
future refreshes require the complete selection/JUnit equality contract. New
unmeasured groups keep the conservative largest-known-cost fallback.

## Verification and remaining delivery

The database-free suite passed **3,511 tests in 28.15 seconds**, including the
new joint-owner graph selection and current-safety regressions. Two existing
Django URLField deprecation warnings remain visible. Actual collection against
an unreachable database URL selected all **3,376 PostgreSQL cases in 278
groups** for full scope and **3,249 cases in 190 groups** for current scope.
The difference is 127 historical cases in 88 groups, including Scheduling's
three committed cases. These are collection checks, not executed database tests.

All 173 new-group testcase identities matched the retained complete baseline
exactly; the thirteen weights equal their summed, millisecond-rounded durations.
Relevant source is unchanged and every existing group estimate is preserved.
The sixteen-group plan is complete/disjoint and estimates 2,562.928–2,563.168
seconds per group. These are local-derived costs, not hosted completion claims.

Repository Ruff lint and formatting passed (882 files). Maintained documentation
validation passed (420 Markdown files, four skills, 215 requirement identifiers),
as did semantic NumPy validation across 482 source/script files and strict
PyDocLint for the edited scripts. Whitespace checks passed. A direct diff against
the preserved feature head confirms no application, migration, integration-test
or shared migration-helper changes were introduced by this integration.

The new exact head still requires exhaustive clean-head local certification,
fresh hosted acceptance, CodeQL and PR gate before protected merge. Do not
rerun the old workflow or certify this feature with PR #84's receipt.

Issue #81 and umbrella #48 remain open. The Scheduling kernel remains dormant:
no editor, staffing adapter, approved Programme release, on-site output or
profile activation is claimed. No deployment, destructive cleanup, extra
database concurrency, increased timeout, test deletion or coverage relaxation
is authorized. Continue the Programme sequence only after protected delivery.
