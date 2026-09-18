# Programme provisioning preparation: protected delivery

Date: 2026-09-18
Scope: PR #166, #108 beneath #48; no candidate activation or native execution.

Protected squash `1f493acc47d121768adf0f5d3b0724e8479914e6` merged at
2026-09-18 07:20:44 UTC from exact head
`1dbb93b824d9e321a86fa1b94583f98a24e38813`. Both trees equal
`daa32fdf22f9914e694dcd498c7dfef227078456`. Clean separate main was
fast-forwarded and verified equal to origin/main and the protected result.
The detached repair worktree remains untouched.

All eight retained local gates passed in **331.333 seconds**. Exact evidence:
10,430 units in **59.60s**, 103 frontend cases, locked inputs, packaging,
static/type/documentation/generated contracts and dependency audits. Receipt v4
reports `postgresql_deferred`, development passed, zero database instances and
null combined coverage/headroom. All five receipt/plan/JUnit/package artifacts
were copied and hash-verified under
`.tools/certification-evidence/issue108-1dbb93b-deferred/`. Receipt SHA256:
`44C1818C1ADDF5B6DB25E2CFE150107DDA3FC1B3ADDF86F27A28A7715ABE1C88`.

Hosted run `35317923867` passed units in **2m21s**, quality in **12m00s** and
PR gate in **3s**. CodeQL run `35317921035` processed Actions,
JavaScript/TypeScript and Python for the exact head with no errors; combined
CodeQL passed. Final review state was CLEAN/MERGEABLE, no unresolved reviews and
no issue-closing references. Ordinary match-head squash used no bypass.

#108 records the completed provisioning preparation only; #108/#48 remain open.
One new host-only native provisioning scenario is explicitly uncollected/unexecuted
#102 debt, supplementing PR #165's four transport cases. No Docker command,
database connection, migration, role provisioning, server or browser fixture was
started. The source-pinned SQL and mocked tests are not native role/schema proof.

The next branch `codex/programme-fixture-candidate` begins at the protected squash
with this handoff only. Next: explicit candidate registration and real isolated
schema installation with independent compatibility validation, joined startup,
real setup/roles and P01–P12. Existing production dormancy checks correctly deny
Programme adoption. A future isolated compatibility contract must not hide
unknown errors, widen current profiles or bypass native authorization/DDL guards.
No complete candidate launcher exists yet. #102/#97/#92/#109 remain mandatory
before final promotion; no prior receipt certifies later checkpoint or code edits.
