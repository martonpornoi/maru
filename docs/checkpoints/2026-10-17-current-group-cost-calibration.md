# Complete current-group cost calibration

Date: 2026-10-17. Requirements: NFR-001. ADRs: 0090 and 0098.

## Problem and bounded change

PR #217's exact local certification took 5,311.588 seconds; its hosted workflow
took 5,365 seconds. Each executed all 5,114 current native cases in 275 groups,
across 38 batches with at most eight workers. The `affected` receipt selected no
historical groups. Some current tests intentionally exercise native migration
recovery/refusal and remain included. First-case setup accounted for about 56%
of local and 55% of hosted test-phase time; this includes fixtures and is not an
individual-migration profile. Dependency caching was already active.

Thirty-seven current groups lacked measurements and each received the largest
known cost, 1,573.166 seconds. Those fallbacks contributed 78.65% of the old
current plan estimate. Complete local and matching hosted reports support
refreshing all current measurements, retaining known floors and historical costs.
The maintainer explicitly approved this bounded optimization and measurement.

The helper now supports explicit `--current-only` calibration from complete
successful current/affected receipts with every current group and no historical
groups. Exhaustive calibration remains the default. Tests exercise rejection of
wrong/failed/diagnostic receipts, changed source or inherited inputs, incomplete
group coverage and invalid reports, plus maximum known/local/hosted costs.

The refreshed map adds 37 missing current costs and increases 146 known costs.
All 96 historical entries remain identical; 15 unmeasured historical groups keep
the existing fallback. Source-derived inventories are unchanged. The unchanged
planner produces 20 current batches instead of 38 and 63 exhaustive batches
instead of 89. Largest predicted batch costs are 3,511.930 and 3,591.994 seconds,
respectively, below the existing 3,600-second target. Actual timing is pending.

## Evidence and provenance

Measured head: `c3787577e32015715e8d42f7564d200420effc58`; measured base:
`de4fe1cf5ca205a1f34ce303e8baef88fc98eda3`. PR #217 was protected-merged as
`98c2b7c02fc38e6df232f374848e42536e489ab3` with identical tree. The preserved
local receipt, 38 reports and selections were reconciled to all 5,114 identities.
The 38 hosted artifact archives were checked against GitHub SHA256 digests and
workflow/head provenance. Reports have no failures, errors or skips.

Two cross-environment parameter-ID differences prevent hosted cost comparison:
`tests/integration/test_admin_edition_context.py` and
`tests/integration/test_page10_account_invitation_api.py`. The explicit exclusions
omit only those hosted comparisons; local costs and every test remain included.
The other 273 groups use the larger usable local/hosted observation, bounded below
by their existing estimate. The generated version-2 provenance sidecar records
the actual receipt scope, calibration scope, report hashes and inherited
map/provenance commit and SHA256 hashes. Historical costs are not new evidence.

Initial focused feedback passed 167 cases; a test-discovery warning was corrected
and the same 167 passed without warnings. Lint's function-size feedback was
resolved by extracting argument parsing and source verification. An installation
guard initially assumed every historical group had a measured cost and stopped
before writing; inspection confirmed 15 already used fallback. The corrected
guard verifies these remain unmeasured with a nondecreasing fallback. All feedback
and prior run evidence are preserved. Final feedback passed all 14,304 units in
83.29 seconds, including the two added maximum-cost cases, with three pre-existing
Django URL-field deprecation warnings. Scoped lint/format, NumPy docstring checks,
docs763 and whitespace passed. The benchmark and exhaustive acceptance are pending.

## Acceptance and limits

This changes scheduling estimates and their evidence tooling only. It does not
remove tests, alter selection, reuse populated databases, increase eight-worker
concurrency, or weaken density, coverage, timeout, slowdown, measured-headroom or
protected delivery requirements. No product, schema, permissions, dependencies,
credentials or deployment change. Reverting the helper/map restores the prior
schedule; no data migration or recovery operation is needed.

A clean current-scope benchmark will measure actual runtime against PR #217's
matching scope. It is diagnostic, not acceptance. Because CI infrastructure is
changing, ordinary Auto must then run exhaustive history against current main,
with independent hosted PR gate/CodeQL and review before protected delivery.
Neither plan counts nor older receipts certify this candidate. Issues #36/#42
remain open, and the separate Workforce recipient-password boundary is preserved.

## Benchmark verified at 15:34 UTC

The pending benchmark above completed on clean commit
`e7f5c4d20fa89b318cf69663edb83d2dbacfa6c2`, tree
`4aba1c4bec65e5f5acc61d1d0b1a82cd61af9cb1`, against base
`98c2b7c02fc38e6df232f374848e42536e489ab3`. Ordinary `CurrentDiagnostic` returned
`diagnostic_success` in 3,669.867 seconds (wrapper 3,670.094 seconds). It ran only
unit, PostgreSQL and combined-coverage gates; all static and hosted acceptance
remains required separately.

| Comparable native measurement | Prior PR #217 | Refreshed plan |
| --- | ---: | ---: |
| Complete current groups | 275 | 275 |
| Passing native cases | 5,114 | 5,114 |
| Fresh database batches | 38 | 20 |
| Maximum simultaneous workers | 8 | 8 |
| Native execution window | 5,254.017 s | 3,615.559 s |
| Aggregate first-case setup | 19,818.395 s | 9,653.047 s |

The observed native window improved by 1,638.458 seconds (27m18s), or 31.18%.
It uses the same earliest pytest-start to latest pytest-finish definition for
both runs. This is one local before/after observation, not a controlled repeated
benchmark or a guarantee for hosted runners. The earlier full certification
took 5,311.588 seconds, but the new diagnostic total is not a like-for-like full
certification comparison because it skips static gates and their contention.
First-case setup includes migrations and other fixtures, not only migration SQL.

All 14,304 units and 5,114 native cases passed with zero failures/errors/skips.
Combined branch-aware coverage was 91.14% with the unchanged 90% gate. Every
batch passed measured headroom; the longest was 2,235.109 seconds. All 20 exact
owned containers were independently absent. The complete 1,628-file diagnostic
archive was hashed and reverified against its original before source release.

All 275 group memberships, per-group case counts and function variant counts
match PR #217, and native runtime/test sources are unchanged. The two previously
documented unstable parameter-ID files differ across runs; each run separately
has exact complete JUnit/selection identity reconciliation. Their cases were
retained and are not claimed to have byte-identical cross-run IDs.

This diagnostic does not recalibrate costs or authorize push. The timing map and
helper remain as benchmarked; only this checkpoint and CURRENT are updated for
the next clean candidate. Fresh ordinary Auto exhaustive certification, review,
exact-head hosted PR gate/CodeQL and protected merge remain pending. Maintained
fictional demos are unaffected.
