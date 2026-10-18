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

## Third exhaustive failure: provenance full-graph history

The ordinary Auto run on clean `bc5ee4f2d85df8239f3129ab82609fd47cf34900`
failed at 20:25:38 UTC after 6,478.5 seconds. All 14,304 units passed in 233.66
seconds. Shard 24 selected 48 of 5,270 collected native cases: 46 passed and both
convention-demo cases raised GuidanceSetupUnavailable after the provenance
full-graph historical test. Twenty-three batches passed; all 31 started batches
retained headroom. Seven active siblings were interrupted and 32 never started.
All 31 exact owned containers were independently absent. Complete 4,665-file
original and archive copies were hash-verified; no acceptance receipt or push
resulted. Earlier failures and their separately preserved originals remain failed.

A fresh unchanged two-case reproduction passed the provenance history and failed
the following demo case in 739.28 seconds (745.859-second wrapper). The current
schema initially matched. The historical target correctly omitted later Guidance
relations; after normal full-leaf teardown only EventEdition still differed.
Its adoption profile code, profile version and revision moved from physical
positions 16, 17 and 18 to 19, 20 and 21, leaving three dropped slots. Guidance
authority and activated runtime readiness passed before the demo body; setup
correctly refused its changed exact schema. All 3,238 before/pre-pytest/after/live
source entries matched digest
`107b0a0128573298bebe594aefcfe880210bb5451d218ab9b87ca917db2f9938`.
All 26 public artifact hashes and independent exact container absence were
verified before source release. The initial verifier expected the earlier
single-column drift and stopped; inspecting the complete column array corrected
that diagnostic expectation without changing source or rerunning the database.

Only the reproduced provenance full-graph ownership case now opts into a local
fixture using the existing committed empty-database helper. It installs the real
current graph, retains the original reverse/forward targets, body, ownership/latch
assertions and module restoration fixture, then flushes and restores every leaf
before exact cleanup. Caller Guidance schema/readiness checks prove preservation.
All other original function bodies, ACL and concurrency cases remain unchanged.
No product guard, schema pin, permission, selection, isolation, worker, timing or
coverage rule changes. Nine focused native regression cases and fresh ordinary
exact exhaustive certification remain pending. Earlier timing gains remain a
qualified observation on the earlier source, not a timing promise for this repair.

## Provenance repair verified at 21:18 UTC

All nine native regression cases passed in 965.85 seconds (972.281-second owned
wrapper), without failures, errors or skips. The sequence retained the repaired
provenance full-graph ownership round-trip, both previously failing convention-demo
cases, and six existing migration-isolation success/failure cases. No observation
plugin was loaded. All 21 original module function bodies remained structurally
identical, including the reverse/forward targets, ownership and latch assertions;
the module restoration fixture and other history, ACL and concurrency cases remain.

All 3,237 before/pre-pytest/after/live source entries matched digest
`3f36a3e8f5dde303034ce22418ec63048e209ae9f04f71982a9d095fbabed7d7`.
All 25 public artifact hashes were verified, and the exact owned container was
independently absent. The tested provenance module SHA256 is
`3d1e1c4c77b9998d19a239a59f52bf35575404994ebd1445c25f90ebcccb0b12`.
This releases the focused source pin; only CURRENT and this checkpoint change
after verification for the next clean candidate.

All three exhaustive failures remain failed and preserved. Focused passes do not
establish full acceptance or timing for the repaired source. Fresh ordinary Auto
exhaustive certification, exact-head hosted checks/review and protected delivery
remain required. Original assertions, physical pins, guards, permissions,
selection, isolation, worker, timing and coverage boundaries remain unchanged.
Maintained demo data and browser coverage are unchanged; these native demo cases
verify the existing behavior after isolated history, not human acceptance.

## Fourth exhaustive failure and remaining provenance history family

The ordinary Auto run on clean `8388566400331e8b8d682ef86ea07730c5a04636`
failed at 23:21:35 UTC after 7,269.922 seconds. All 14,304 units passed in 232.76
seconds. Shard 29 selected 44 cases: 26 passed, five failed and 13 had setup
errors in Guidance foundation after missing-latch authorization reversal.
Twenty-nine batches passed; all 37 started batches retained headroom. Seven
siblings were interrupted and 26 never started. All 37 exact owned containers
were independently absent. Complete 4,713-file original and archive copies were
hash-verified; the original remains intact until preservation for another run.
No acceptance receipt or push resulted. Prior failing shards 1, 4 and 24 passed,
but this failed run does not certify the whole suite or a runtime improvement.

An unchanged two-case reproduction passed the missing-latch history and failed
the following direct-body Guidance setup case in 702.53 seconds (728.469-second
wrapper). After ordinary full-leaf restoration, only EventEdition's fingerprint
differed: adoption profile code, version and revision moved from physical
positions 16, 17 and 18 to 19, 20 and 21, leaving dropped slots. Authority and
activated runtime readiness passed; Guidance setup correctly refused the exact
schema mismatch. All 3,238 before/pre-pytest/after/live entries matched digest
`dd64db2542ecea5f791d953117f25c248b582e46a4ab87ed4de3dcc218937911`;
all 26 public artifact hashes and independent exact owned cleanup were verified
before source release. No guard, pin or diagnostic assertion was weakened.

A read-only audit evaluated Django's actual migration plans from the complete
current graph without a database. The first targets of authorization reverse,
audit reverse and missing-latch reverse unwind all three adoption AddField
operations. The two reserved-audit upgrade targets unwind adoption_revision only.
All five therefore expose the shared current database to the observed physical
slot mechanism. This is plan evidence, not five separately executed failures.
An initial audit assertion expected three fields for every target and stopped
before writing evidence; the exact plans corrected that expectation without
database execution, source changes or a retry of the failing diagnostic.

Those five historical cases now opt into the existing local committed-isolation
fixture. Real current-graph setup in a fresh empty database, original bodies,
targets, ownership/latch assertions, full restoration and exact cleanup remain.
Caller Guidance schema/readiness assertions protect the shared database. The
existing full-graph fixture body and ACL test's own isolated database are unchanged;
current-state and concurrency tests also remain unchanged. All original module
function bodies are structurally identical. No product schema, guard, pin,
permission, selection, worker, timing, coverage or protected gate changed.

Two sequential source-pinned focused runs are planned: missing-latch history,
all Guidance foundation cases, authorization/audit history and six native
isolation success/failure cases; then the remaining provenance module cases,
including both reserved-audit histories, ACL, full-graph, current and concurrency
coverage. Each uses a fresh owned database and the unchanged one-hour diagnostic
limit. Focused and full exhaustive acceptance are pending. Every earlier failure
stays failed and preserved; the earlier 31.18% observation predates these repairs
and is not a repaired-source or hosted speed promise.

## Complete provenance family verified on 2026-10-18

Both sequential native regressions passed with unchanged tracked source. Batch A
passed all 27 cases in 2,432.28 seconds (2,439.062-second wrapper): missing-latch
history, all 18 Guidance foundation cases, authorization/audit history and six
native isolation success/failure regressions. Batch B passed all nine remaining
provenance cases in 2,419.87 seconds (2,445.969-second wrapper): reserved-audit
histories, full-graph history, ACL history, current validation and concurrency.
There were no failures, errors or skips and no observation plugin in either run.
Selection/JUnit identities reconcile exactly. Together they cover 36 distinct
cases: all 12 provenance module cases, all 18 Guidance foundation cases and all
six native isolation cases. All 21 original provenance module function bodies
remain structurally identical; the existing fixture body is also unchanged.

Each run's 3,237 before/pre-pytest/after/live source entries matched. Batch A digest
is `559d478f1c5cc8db3dd8cf2835e44aa7efbf834502de13187b3a75f2f48784ce`;
batch B is `be1461cafaadca3ded2fff667e5ae27c35ecec7d9ed3ba6332c36bff33639c55`.
All 3,236 tracked/unignored entries are identical across the two inventories;
only their ignored runner paths differ. All 25 public artifact hashes per run
were verified, and both exact owned containers were independently absent. The
tested provenance module SHA256 remains
`c6cb928e3142a9a28128abc51d749e425cd938b028a870641c9ddf790bc5e0a7`.
Both source pins are released; only CURRENT and this append-only checkpoint
change afterward for the next clean candidate.

All four exhaustive failures stay failed and preserved. The fourth 4,713-file
original and its archive must be rehashed against the saved manifest and the
intact original preserved before another full run. These focused results do not
establish full acceptance, repaired-source timing or hosted performance. Fresh
ordinary Auto exact exhaustive certification against current main, all ten gates,
complete selection, coverage, headroom, owned cleanup and protected hosted review
remain required. No assertion, physical pin, guard, permission, isolation,
selection, worker, timing, coverage, hook or protection is weakened.

## Fifth exhaustive failure: invitation-token history

The ordinary Auto run on clean `a47a890c8cdd66a487f6d293a9f0f7be8b45cf7d`
failed at 04:23:09 UTC on October 18 after 9,620.516 seconds. All 14,304 units
passed in 236.63 seconds. Shard 34 selected 54 of 5,270 native cases: 52 passed
and two Knowledge withdrawal-reserve fixtures rejected Guidance setup after
invitation-token digest-key history. Thirty-four batches passed; all 42 started
batches retained headroom. Seven siblings were interrupted and 21 never started.
All 42 exact owned containers were independently absent. Both complete 4,753-file
original and archive copies were hash-verified; the original remains intact until
its separately verified preservation before another full run. No success receipt
or push resulted; all earlier failed and focused evidence remains preserved.

The unchanged first two shard cases reproduced one pass and one setup error in
505.04 seconds (511.672-second wrapper). Read-only observations after the failed
fixture showed that full-leaf restoration left only EventEdition different:
`adoption_revision` moved from physical slot 18 to 19, leaving dropped slot 18.
All earlier columns stayed exact. Authority and activated runtime were ready;
Guidance setup correctly refused the changed schema. All 3,238 before/pre-pytest/
after/live entries matched digest
`b8e90bb426ef0649365f92eb65563d8e40e898a1413e7cbc07e00e338187069a`.
All 26 artifact hashes, exact case identities and independent absence of the
owned container were verified before source release. This diagnostic is not
acceptance or timing-calibration input.

A database-free audit of Django's actual full-current migration plans found
revision-field reversal in both serial tests' first Identity targets: 0013
requires 135 backward migrations and 0012 requires 139. This is shared plan
exposure, not a claim that both tests were separately reproduced as failures.
Both tests now explicitly use the existing committed empty-database helper with
real current-graph setup, original bodies and targets, full restoration, exact
cleanup and caller Guidance schema/readiness checks. All four original functions
remain structurally identical. Active legacy-token refusal, terminal-evidence
upgrade, keyed-token downgrade refusal and audit retry uniqueness are preserved.
No product, schema, pin, guard, permission, selection or gate changes. The focused
native regression and fresh ordinary exact exhaustive certification are pending;
earlier timing gains remain a limited observation on earlier source.

## Invitation history regression verified on 2026-10-18

All 11 focused native cases passed in 1,343.66 seconds (1,350.172-second wrapper),
with zero failures, errors or skips and no observation plugin. The exact order
retained the original first invitation history followed by both previously
blocked Knowledge withdrawal-reserve cases, then the second invitation history,
a Guidance foundation case and six native isolation success/failure regressions.
The fresh owned database retained the 1 GiB tmpfs, 2 GiB memory and one-hour limit.

All 3,237 before/pre-pytest/after/live source entries matched digest
`641a0a89b31ee761aeb9193e78c28946fd47eedddf2077b27a92e5c840a97149`.
All 25 artifact hashes and exact selected/JUnit case identities were verified.
All four original invitation-module function bodies remain structurally identical;
the tested file SHA256 is
`b76f302bfd67a2207237a09605875d91debca9e028a66563cc65a21dbea7ef4e`.
The exact owned container was independently absent before source release. Only
CURRENT and this append-only checkpoint change afterward for the clean candidate.

All five exhaustive failures remain failed and preserved. The fifth 4,753-file
original/archive and run logs must be rehashed before preserving the original
intact for a fresh ordinary Auto exact exhaustive run against current main.
Focused success is not complete acceptance or a timing promise. Every ordinary
gate, complete selection, physical schema pin, security assertion, coverage,
headroom, worker limit, exact owned cleanup and hosted protection remains required.

## Sixth exhaustive failure: activation-schema history

Ordinary Auto certification on clean `9d4d0196b2c6b077643ae8969a6fe7f06cc1eefa`
failed at 08:04:31 UTC on October 18 after 9,751.047 seconds. All 14,304 units
passed in 231.72 seconds. Shard 38 selected 82 of 5,270 native cases: 53 passed
and 29 Knowledge domain fixtures rejected Guidance setup. Thirty-five batches
passed; all 43 started batches retained headroom. Seven siblings were interrupted
and 20 never started. All 43 exact owned containers were independently absent.
Both complete 4,761-file original and archive copies were hash-verified; the
original remains intact until separate preservation before another full run.
There is no success receipt or push; all six full failures remain failed.

The unchanged activation-schema clean-reverse/forward test followed by the first
Knowledge domain case reproduced one pass and one setup error in 701.77 seconds
(708.187-second wrapper). These were adjacent in actual shard order; six earlier
current Registration API cases were omitted from this minimal reproduction.
After ordinary full-leaf restoration, only EventEdition's fingerprint differed:
adoption code, version and revision moved from physical slots 16/17/18 to 19/20/21,
leaving dropped slots. Every other captured physical column remained exact.
Authority and activated runtime were ready; Guidance correctly refused setup.
All 3,238 before/pre-pytest/after/live entries matched source digest
`5da751fde7a9c5540b72bb55991a7ec51e6808c577ae307612c9ab68b896c362`.
All 26 artifact hashes, exact selected/report identities and independent absence
of the owned container were verified before source release. The read-only
observer changed no assertion, schema, record or outcome. This is diagnostic
evidence, not acceptance or timing-calibration input.

A database-free audit of actual Django plans from the 316-node current graph
found all three adoption-field reversals in all four serial activation-history
tests. Authorization 0006 has 201 backward migrations; 0005 has 202. Field
removals occur at zero-based plan indexes 10 and 172, before the runtime-latch
downgrade fence at 198 in the activated-latch refusal plan. This is shared plan
exposure, not four separately reproduced failures. The four histories now opt
into the existing committed empty-database helper with real current-graph setup,
original bodies/targets/assertions, flush/full restoration, exact cleanup and
caller Guidance schema/readiness checks. Their original restoration fixture
remains. Current catalog, guard and concurrent-writer cases keep their existing
scope. No product, schema, pin, guard, permission, selection or gate changes.
Two sequential focused regressions and fresh ordinary exact exhaustive
certification remain pending. Earlier timing savings predate these repairs.

## Activation history regressions verified on 2026-10-18

Two sequential runs passed all 62 distinct native cases with zero failures,
errors or skips and no observation plugin. Batch A passed 37 cases in 1,780.71
seconds (1,787.266-second wrapper): clean symmetry history, all 29 previously
blocked Knowledge domain cases, prior owned-definition history and six native
isolation success/failure cases. Batch B passed 25 cases in 1,723.11 seconds
(1,729.735-second wrapper): foundational-definition and activated-latch refusal
histories, all 18 Guidance foundation cases, exact current catalog/dormant latch
and three concurrent-writer cases. Each fresh owned database retained the
1 GiB tmpfs, 2 GiB memory and one-hour limit. The second run began only after
the first had complete source/artifact/case/cleanup verification.

Both 3,237-entry before/pre-pytest/after/live inventories matched. A's digest is
`31717c62792bff6b6d5ae6e921f330a60741899916dc86222a8cfb11056afb02`;
B's is `c85d797e4ed60d59b4e0813b0e7aabde435c547e5f04c54c1ab514ca1eea27b8`.
The 3,236 tracked/unignored entries are identical across runs; only ignored runner
paths differ. All 25 artifact hashes per run and exact selected/JUnit identities
were verified. All 49 original activation-module function bodies remain
structurally identical; the tested file SHA256 is
`22dff94dd74f0a6a26c51c285d78b0a1d5bd5f9bc5836ce1fa1aad2911a0e056`.
Both exact owned containers were independently absent before source release.
Only CURRENT and this append-only checkpoint change afterward for the candidate.

All six exhaustive failures remain failed and preserved. The sixth 4,761-file
original/archive and run logs must be rehashed before preserving the original
intact for a fresh ordinary Auto exact exhaustive run against current main.
Focused success is not full or hosted acceptance, or a timing promise. Every
ordinary gate, complete selection, physical schema pin, security assertion,
coverage/headroom threshold, worker limit, cleanup and hosted protection remains.


## Seventh exhaustive timing failure and capacity repair (2026-10-18)

Clean `e247d695920572df358add3ec9790677792e0a37` failed ordinary Auto exhaustive
certification after 10,267.218 seconds. All 14,304 units passed in 233.21 seconds;
36 native batches passed, seven siblings were interrupted and 19 never started.
Shard 34 exceeded measured headroom at 3,201.625 seconds. Incremental evidence
records all 54 calls and 53 teardowns passing; final Workforce structure-history
teardown was incomplete. No final JUnit or success receipt exists for that shard.
All 44 exact owned containers were independently absent. Both full 4,767-file
original/archive copies and run logs were hash-verified; the original is retained
until verified preservation before the next run. All seven failures stay failed.

The single unchanged complete-shard diagnostic used the original frozen plan,
ordinary coverage/acceptance runner and collection/timing hooks, a fresh database,
1 GiB tmpfs, 2 GiB memory and a 3,200-second ceiling. All 54 cases passed in
2,406.72 seconds (wrapper 2,436.687), with zero failures, errors or skips and all
162 phases complete. The invitation history spent 714.467/332.117/199.704 seconds
in setup/call/teardown; Workforce spent 0.002/560.822/321.754 seconds. The failed
pool's partial timings remain lower bounds, not complete group costs.

Before/pre-pytest/after/live inventories match all 3,239 entries at digest
`37267c1d22c789eb4221eecfc2d9dbd58c4eadd14a7abaeeaa598cb983da681e`.
All 28 artifact hashes, exact 5,270-collected/54-selected/report identities,
original order and phases were verified; exact owned cleanup was independently
confirmed. Proof is retained under `ci-cost-shard34-headroom-probe-20261018` as
`verified-result.json`; source was released before edits. This isolated pass does
not establish CPU/IO saturation, its sole cause, or concurrent/hosted acceptance.

NFR-001 and ADR 0098 permit capacity replanning after measured headroom failure.
Tighten the frozen historical density from two to one complete group per shard.
Keep every test and original committed history/restoration operation; retain
shared baselines and parameter groups intact. Current groups still share capacity
under the existing cost budget. The complete former shard's unchanged order pass
and prior isolation regressions remain preserved; repartitioning does not replace
contamination repair. Cost map/provenance, workers, all timing limits, coverage,
security, selection and protected checks remain unchanged. More exhaustive
batches add startup overhead and are not a total-speed promise. Focused policy
verification and fresh complete exact-head local/hosted acceptance are pending.
Issues #36/#42 and the human Workforce boundary remain open and unchanged.


### Capacity candidate feedback

All 169 focused planner, selection, pool and calibration safeguards passed in
19.61 seconds using fresh owned temporary storage. Scoped Ruff/format, docs
validation (763 Markdown files), whitespace and coherent branch review passed.
The source-derived audit retains exactly all 386 groups, including 111 historical
groups, in 111 exhaustive batches instead of 63. Every new shard has one complete
historical group; all 20 current-only assignments remain exactly unchanged.
The frozen policy fingerprint is
`7e97e7e07f19ee422c117c6ccd967418f7ab439d93a0adc485841b65299673be`.
Estimates and focused tests do not establish native headroom; fresh ordinary
Auto exhaustive certification remains pending. Earlier local command setup
errors (incorrect paths/settings and denied shared pytest temp storage) are
preserved; no test assertion failure was hidden or retried unchanged.
