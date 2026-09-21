# Programme native composition regression repairs

Date: 2026-09-21. Test-only continuation of #48's exit bundle; not protected
delivery, complete certification or profile activation.

The bounded diagnostic sweep at `371ded028cf22b31ae174c12b2d5353c2f1937b9`
executes the seventeen shards left incomplete by the preserved `e3635ab` failed
certification. It uses the unchanged source-bound selection and native worker,
with at most eight databases, original deadlines and verified cleanup. Unlike
certification, it collects later failures instead of cancelling after the first
failure. It creates no certification receipt and cannot replace fresh acceptance.

Three test contracts exposed five failed cases:

- Shard 57's three deliberately corrupted Board-lineage cases encountered a
  pending deferred stop-trigger event before they could restore their original
  guards. The shared Organization assignment has no edition, so that enabled
  stop guard legitimately performs no change. The fixture now sets only this
  constraint to immediate before corruption. The native lineage validator must
  still reject every malformed assignment, all original guards are restored,
  the transaction rolls back and the complete assignment row is unchanged.
- Shard 58's proposal-scope assertion expected the older message, although the
  new stop guard correctly rejected a mismatched parent pair first. The test now
  covers organization-only, edition-only and coordinated foreign-parent changes.
  The first two must fail exact-edition resolution; the valid foreign pair must
  still fail the original selection-to-proposal invariant. Every case requires
  SQLSTATE `23514` and unchanged complete submission, proposal and revision rows.
- Shard 63's legacy ACL round-trip restored only the base terminal migration,
  omitting supporting stop migrations required by the extended contract. The
  test captures the original full graph leaves, preserves legacy ACL assertions,
  requires base-only restoration to remain unready, then restores the full graph.
  Readiness, the exact applied-migration set, all function source hashes and ACLs,
  and all trigger metadata must match the original snapshot.

No application source, migration, readiness hash, security guard, selection rule,
timeout or coverage threshold changes. Privileged corruption fixtures are not
runtime-role or human acceptance evidence.

## Focused verification

Repairs were made in the isolated `codex/programme-native-test-repairs` checkout
while the primary diagnostic source remained frozen. Python imports were verified
against that checkout, using the root's locked virtual environment.

- The six Board/proposal cases and all sixteen native stop-authority cases pass:
  **22 tests / 272.37s**, no failures, errors or skips;
  `.tools/programme-diagnostic-repairs-native-1.xml`.
- The repaired legacy migration recovery round-trip passes: **1 test / 295.08s**,
  no failures, errors or skips; `.tools/programme-diagnostic-repairs-native-2.xml`.
- Complete fast unit run42 passes **13,222 tests / 104.38s**, with the three existing
  Django URL-field warnings; `.tools/programme-exit-bundle-units-42.xml`.
- Ruff lint and formatting pass for the three changed test files.

The task-labelled, loopback-only disposable database was inspected, stopped and
verified removed after both focused native runs. Reports remain available.

## Completed diagnostic sweep

All seventeen diagnostic shards completed: fourteen passed and three contain the
five failures above. Their JUnit reports contain **1,631 tests, five failures,
zero errors and zero skips**. Every result has measured timing headroom and
verified container removal; the longest took **2,507.328s (41m47s)**. The final
shard passed in 2,030.234s. The sweep's exit status is correctly nonzero, and the
five failed cases are resolved only by the separately recorded focused repairs.
Evidence: `.tools/programme-remaining-diagnostic-1/diagnostic-results.json` and
its original reports, timing records, coverage parts and logs. A Docker inventory
confirmed no remaining diagnostic integration container.

An explicitly diagnostic coverage preview combines the earlier 54 successful
shard parts and unit part with these seventeen completed diagnostic parts, keeping
all original files. Application/rehearsal source is unchanged across those heads;
the preview reaches **91.74%**, above the unchanged 90% threshold. It includes
failed-run observations, is not exact-head acceptance and creates no certification
receipt. It exists only to detect a potential shortfall before another full run.
Output: `.tools/programme-coverage-preview-1`.

Maintained documentation validation passes for 684 Markdown files in the isolated
checkout, four repository skills and 215 unique requirement identifiers; diff
whitespace checks pass. Final fresh clean exact-head certification and independent
hosted acceptance remain required before delivery. Preserve earlier failed
attempts; do not concatenate partial results into a success receipt.
#48/#108/#109/#92 remain open, including the genuine human acceptance and trusted
rehearsal-origin prerequisites.
