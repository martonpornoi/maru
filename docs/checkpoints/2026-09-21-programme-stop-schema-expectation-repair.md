# Programme stop schema: historical versus completed admission

Date: 2026-09-21. Local test repair within #48; not a product-policy change,
protected delivery, certification success or profile activation.

Full certification of `8f3f825f180438953630c2fb39eacbf2f12a9eca` against
`b056aa253a39df2648752daf35ac5a158a9950d7` failed after 46m35s in shard 33.
The old `test_native_stop_receipt_insertion_is_closed_until_full_owner_admission`
still expected Events 0015's unconditional preparation-stage message, although
Events 0016 had installed the completed native admission guard. The actual guard
correctly rejected the malformed insertion with `Programme stop requires exact
bounded intent`; no unsafe receipt was admitted.

Thirty-two shards passed, containing 1,620 native cases without failures/errors/
skips. Shard 33 passed 77 cases and failed that one expectation in 655.86s;
its total job time including cleanup was 665.938s. Seven remaining active shards
were cancelled. All 40 started containers report removed. The slowest passing
job was 989.031s, and no timing headroom was exhausted. All 13,222 certification
units passed in 176.41s. There is no successful receipt or partial-result waiver.
Evidence remains in
`.tools/certification-evidence/programme-exit-8f3f825-stop-expectation-failed`
and the outer `.tools/programme-certification-8f3f825.log` transcript, which does
not capture all nested command output.

The correction changes tests only. The current-schema case now expects the exact
bounded-intent refusal and retains the zero-written-rows assertion. An additional
real migration-executor case reverses an unused graph to Events 0015, verifies
its original unconditional refusal and zero rows, restores the complete current
graph, verifies exact stop readiness and repeats the current bounded-intent refusal
with zero rows. The historical check is executed at its actual schema revision,
not emulated by replacing a live function or relaxing a guard.

Focused PostgreSQL execution passed **44 cases in 291.56s (4m52s)**, with no
failures, errors or skips: current schema/ACL, whole-exit recovery and real stop
command tests. Report: `.tools/programme-stop-schema-native-1.xml`.
Complete fast unit run40 passed **13,222 cases in 72.21s**, with the three existing
Django URL-field warnings. Ruff, formatting and maintained documentation checks pass.

No application/rehearsal source or applied migration changed. Events 0017 and 0018
retain their recorded source hashes; the [populated run26](2026-09-21-programme-retained-recovery-verification.md)
remains evidence of its exact unchanged application/rehearsal source, not a receipt
for a later commit. Fresh complete exact-head local and hosted certification is
still mandatory after this test/documentation correction. Preserve all previous
failed reports and keep parent human/integrated/promotion gates open.
