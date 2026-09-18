# Programme runtime resource preparation: protected delivery

Date: 2026-09-18
Scope: PR #165, a bounded #108 prerequisite beneath #48; no profile activation.

Protected squash `4519e5b01469eb236fc524706ad48c31bc631d4e` merged at
2026-09-18 06:46:30 UTC from exact head
`f055a74a4792a8a23a221b0968ffc16ac37a3a94`. Certified and protected trees both
equal `1997342e3bcd65239f7aa4d56a19cee5a69da128`. Clean separate main was
fast-forwarded; local main, origin/main and protected squash matched. The detached
repair worktree was untouched.

All eight retained local gates passed in **322.085 seconds**: 10,383 units in
60.42s, 103 frontend cases, static/type/documentation/generated contracts,
packaging and dependency audits. Receipt v4 is `postgresql_deferred`, development
passed, zero database instances and null combined coverage/headroom. Five
receipt/plan/JUnit/package artifacts were copied and hash-verified under
`.tools/certification-evidence/issue108-f055a74-deferred/`. Receipt SHA256:
`8D542453E20AD73164CA94C56DFF2FABC012A5AAE0783545D5737B2D9BDE7DEC`.

Initial head `5e2d000` had separate passing local evidence. Final review corrected
the startup probe to TCP rather than the temporary initialization socket and
added a regression. That old receipt remains separately archived and was not
reused for the corrected commit.

Hosted run `35315309557` passed units in **1m29s**, quality in **12m13s** and
PR gate in **2s**. CodeQL run `35315306606` processed Actions, JavaScript/TypeScript
and Python results for the exact head with no processing errors; combined CodeQL
passed. Pre-merge state was CLEAN/MERGEABLE, with no unresolved reviews or
issue-closing references. No bypass or setting change was used.

#108 records only this completed resource preparation; #108/#48 remain open.
Four host-only native transport cases remain uncollected/unexecuted #102 debt.
No Docker resource, database, migration, server or browser fixture was started.
Next are genuine migration/runtime provisioning, candidate installation, real
setup/roles and the complete acceptance journey, followed by the separate
#102/#97/#92/#109 gates before promotion.
