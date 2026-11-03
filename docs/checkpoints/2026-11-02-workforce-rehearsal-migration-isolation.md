# Workforce rehearsal: isolate committed authority-issuance history

Date: 2026-11-02

## Scope and contracts

The canonical Workforce-only rehearsal remains the bounded #42 outcome after
protected #235 delivery through PR #236. This repair follows the existing
[committed migration isolation rule](../development/local-certification.md)
under NFR-001, NFR-002, NFR-003, NFR-008 and NFR-010. OPS-008 and ADR 0080 still
govern the rehearsal; ADR 0098 retains complete selection and measured budgets,
and ADR 0113 continues to reject physical column drift. No ADR is superseded.

## Preserved failure and native diagnosis

The first clean final candidate, `a04dd97960ef9c4bd82ac98359ca4ef6bd8efba0`,
ran ordinary unchanged Auto against protected base
`92f59d227e2bdd247c404f7131cd0e58651504a9`. Its full all-history plan selected
392 groups and 111 shards. Only 51 started: 43 succeeded; shard 45 exited with
status 1, with 24 passing cases and two Guidance readiness failures. The ordinary
pool then interrupted seven active shards. Those results retained timing headroom;
this was not a timing-exhaustion failure. Sixty shards never ran. All 14,972
unit cases passed with the exact Windows POSIX skip. Combined coverage and the
success receipt were never reached; the 45 individual coverage parts remain
retained and do not certify the candidate.

A separate fresh unchanged checkout reproduced all 26 original shard cases in
their original global collection order: 24 passed and the same two Guidance
checks failed. All 78 setup/call/teardown identities, outcomes and durations
reconciled with JUnit. The reproduction took 780.688 seconds including cleanup;
that focused observation is not complete acceptance or a hosted speed claim.

Native catalog checkpoints establish the cause. Before
`test_nonempty_ledger_refuses_schema_downgrade`, the fresh Guidance contract
passes. Immediately after its committed downgrade and restoration, it fails in
the same shared database. Events and Authorization migration records are back
at their original current state, but `events_eventedition` retains dropped
physical slots 16, 17 and 18. The visible `adoption_profile_code`,
`adoption_profile_version` and `adoption_revision` columns move from positions
16–18 to 19–21. Names, types and nullability remain equal. The other four pinned
Guidance relations remain equal. The exact production shape guard correctly
rejects the changed relation before the later Guidance cases can continue.

All 3,333 source hashes matched preparation, before/after execution and live
verification. The exact owned container was removed and ten original stopped
fixtures stayed unchanged. The failed Auto's 6,684 originals are sealed under
disjoint manifests `0c0d074d97ffe3c78068c1f2146f4ad85a2d5682b93b9cc710b5bdf850a6c06c`
and `9c36b0539fbaa37454036e06eb27046676c4e7eee4033fa1c91ff6c93c22e749`.
The reproduction's 120 new originals are sealed under
`c1b4c93cdc436c9da4beee432c2eb3034f658c689a4fd67ece7f39ce2dd165c2`;
four independent derivations are separately sealed under
`7a669fb74f1967a7973630356e63de6ef52d27462e64790273632141d92243cd`.
Temporary caches and working directories are retained and excluded. No older
sealed original was rehashed or overwritten.

## Test-only repair and verification boundary

Only the offending committed historical case now uses the existing
`isolated_migration_database` helper. It initializes a fresh owned graph,
retains real autocommit, every original migration target and refusal assertion,
and restores the full current graph before exact owned cleanup. Before and
after that context, the fixture checks all pinned Guidance relation
fingerprints and the actual complete Guidance readiness query on the caller's
database. The case remains in ordinary collection and its historical group.

Production models, migrations, authority clocks, source and schema pins, guards,
ACLs, profiles, history selection, coverage, resource and timing limits are
unchanged. No test is omitted or reordered, no shared schema is rebuilt to hide
drift, and no fixture changes a retained environment.

Fresh repaired feedback passed all 26 original cases and all 78 real
setup/call/teardown phases with no failure, error or skip. Original selection and
global execution order match. The historical case's passing setup and teardown
execute the new exact caller-schema and real Guidance readiness assertions;
no separate raw catalog dump is claimed for this repaired run. Every original
test body, signature, migration target and historical assertion is unchanged.
The native interval measured 997.790 seconds; the complete feedback wrapper,
including metadata, startup and cleanup, measured 1,034.437 seconds. This is
focused feedback, not a timing-map refresh or a hosted speed guarantee.

All 3,334 before/after/live source hashes agree. Production source is equal to
protected #235. The exact owned container is absent and all ten original stopped
fixtures are unchanged. Targeted Ruff format/lint, documentation policy and
whitespace checks passed. The 125 new feedback originals, including exact copies
of the four tested task files, are sealed under
`cd2fc5940b2e7867c5bae76d9215522fce30312651162380af4f42c6ea120e73`.
Four new independent derivations are sealed under
`d3e56d6b0e740292c9fe3d7b1cc527c5a1f71b5ade731bd2b6c04e629e82cb4a`.
Current main was independently read from the repository remote and GitHub API
at 18:01 UTC and still equals protected base `92f59d227e2bdd247c404f7131cd0e58651504a9`.

A new clean commit and fresh source/output still require complete ordinary
local Auto, independent hosted acceptance, protected exact-head squash and
designated clean-main ff-only
synchronization before technical delivery. This checkpoint is not a receipt.

#42 remains open until the full four-role browser journey and final lifecycle
absence proof pass. Browser input remains stopped at the current-URL safety
control; there is no retry or alternate mechanism. The original human trial,
private invitation material, accounts, records and 113-checkbox guide remain
untouched. #35, #23 and #22 retain their separate full scope and acceptance gates.
