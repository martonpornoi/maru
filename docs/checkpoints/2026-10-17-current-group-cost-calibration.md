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

## Exhaustive failure and isolated reproduction

The ordinary exhaustive Auto run on clean `ef2290ed67dc1b8a5fd51c710044dd3bcac48c87`
failed at 15:59:57 UTC after 1,298.313 seconds. Its all-history plan retained 386
groups and 111 historical groups in 63 batches. All 14,304 units passed in
235.27 seconds. Shard 4 reported 44 passes and one failed initial Knowledge
readiness assertion; the pool interrupted its other active workers. Every one
of the 13 started batches retained timing headroom. Their exact owned containers
were independently absent. The complete 4,513-file failed evidence tree was
copied and both copies hash-verified; no success receipt exists.

A fresh isolated two-test reproduction ran the unchanged Programme-import
per-relation downgrade test followed by the unchanged Knowledge round-trip
test. It reproduced the latter's initial failure (one pass, one failure) in
470.81 seconds, with a 477.343-second owned wrapper. Read-only observations
showed the fresh pinned schema initially matched. After real history and leaf
restoration, only `events_eventedition` differed: position 18 was a dropped slot
and `adoption_revision` had moved to position 19. Guidance setup readiness was
false while Guidance authority and activated runtime readiness were true.
All 3,238 before/pre-pytest/after/live source entries matched, all 26 public
artifact hashes were verified, and the exact owned container was absent.

The bounded repair opts the six serial committed Programme-import history cases
into the existing `isolated_migration_database()` helper. It builds the actual
current graph in a fresh empty database, retains the original test bodies and
full restoration, then restores the caller connection and removes only its own
database. Added schema/readiness assertions prove caller preservation. Real
autocommit and the original local replica-setup transaction scopes are retained;
an outer rollback would change those semantics. No product guard, physical pin,
assertion, migration target, worker, timing, coverage or selection rule changes.
The current contract-inspection case retains its ordinary database.

Focused repair verification and fresh full exact-head acceptance are pending.
The earlier measured current-scope improvement remains a single observation on
the earlier source, not acceptance or a guaranteed timing for this repaired
candidate. Failed evidence and both prior benchmark copies remain preserved.

## Focused repair verified at 17:17 UTC

The repaired source passed all 14 native cases in 2,709.55 seconds (owned wrapper
2,716.157 seconds), without failures, errors or skips. The selection contained
the complete seven-case Programme-import module, the previously failing
Knowledge round-trip, and six existing native migration-isolation success and
failure regressions. No observation plugin was loaded. All original six test
function bodies were structurally identical, including migration targets and
assertions; the ordinary current contract case was unchanged.

Before/pre-pytest/after/live inventories matched all 3,237 source files with
digest `6e75d5ec93f685cebefb50bb9626fc91e4112353f79ad9e9f55791515e510bf0`.
All 25 public artifact hashes were verified, and the exact owned container was
independently absent. The tested import module SHA256 is
`c38fb099bfc1d30a168abc385445f76ad4f774e5d8d4e814d31c368c4c6c44b8`.
This evidence releases the focused source pin; only status documentation is
updated for the next clean candidate.

This pass confirms the bounded repair and caller preservation in the selected
sequence. It does not turn the failed exhaustive result into a pass, establish
full-suite timing for the repaired source, or authorize push. Fresh ordinary
Auto exhaustive certification and exact-head hosted acceptance remain required.
All previous failed, diagnostic and passing evidence remains preserved.

## Second exhaustive failure: file-custody history

The ordinary Auto run on clean `d7102393ff37b26bcdba353f297cf9e789b5ebbb`
failed at 17:35:50 UTC after 745.734 seconds. All 14,304 units passed in 231.39
seconds. The 386-group/111-history/63-batch plan collected 5,270 native cases.
Shard 1's file-custody historical round-trip passed; the next import-isolation
fixture failed its initial Guidance setup assertion before the test body (one
pass, one setup error). All eight started batches retained timing headroom;
seven siblings were interrupted. Their exact owned containers were independently
absent. All 4,473 failed evidence files were copied and both copies hash-verified;
the original remains intact and no success receipt was issued.

An unchanged fresh two-case reproduction confirmed this sequence in 268.44
seconds (274.828-second wrapper). Before the file-custody call the exact schema
matched; afterwards only `events_eventedition` differed: `adoption_revision`
moved from physical slot 18 to 19 and left dropped slot 18. Guidance setup changed
from ready to unavailable; authority remained ready. Activated-runtime readiness
was unavailable both before and after under this fixture, not an additional
regression. All 3,238 before/pre-pytest/after/live source entries matched digest
`44ed4edd7fd3428f7af442803dff19288912ba5829b9d3fd49228197c03d3ea7`.
All 26 public artifact hashes and independent exact container absence were
verified before source release.

Only the single file-custody history case now opts into the existing committed
empty-database helper. It installs the real current graph, executes its original
unchanged body and reverse/forward readiness assertions, and retains full
restoration before exact cleanup. Additional before/after caller Guidance schema
and readiness assertions retain the same physical-schema boundary. All original
functions and ordinary custody tests remain unchanged. No product schema, pinned
hash, guard, permission, selection, timing or coverage rule changes. Focused
native regression and fresh exact exhaustive certification remain pending.

## File-custody repair verified at 18:32 UTC

All nine native regression cases passed in 968.55 seconds (974.906-second owned
wrapper), without failures, errors or skips. The sequence retained the repaired
file-custody history, the previously blocked import history, Knowledge readiness
round-trip, and six existing migration-isolation success/failure cases. No
observation plugin was loaded. All 26 original file-custody function bodies were
structurally identical, including the historical migration targets and assertions;
ordinary current tests and the original full-restoration fixture were retained.

All 3,237 before/pre-pytest/after/live source entries matched digest
`b5ce686a5eb16a911ad8b32e0346c2313cb5b3259841faebb28e9e4aac97b5d2`.
All 25 public artifact hashes were verified, and the exact owned container was
independently absent. The tested file-custody module SHA256 is
`22837152d4fb589f0fe306f68c033b3f35fa9d52ee49315d1bd33997cdefa220`.
This releases the focused source pin; only CURRENT and this checkpoint change
after verification for the next clean candidate.

Both exhaustive failures remain failed and preserved. The focused passes do not
establish full acceptance or timing for the repaired source. Fresh ordinary Auto
exhaustive certification, exact-head hosted checks/review and protected delivery
remain required. Every original assertion, physical pin, guard, permission,
selection, isolation, worker, timing and coverage boundary remains unchanged.
