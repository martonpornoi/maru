# CI delivery and Catalog creation retry conformance

- Date: 2026-10-19
- Requirements: INT-001, AUD-001, NFR-001, NFR-002, NFR-003, NFR-009, NFR-013
- Decisions: ADRs 0001, 0003, 0050, 0056 and 0098 remain unchanged
- Status: CI delivery verified; bounded Catalog focused evidence passed; exact delivery pending

## Verified CI delivery

[PR #218](https://github.com/martonpornoi/maru/pull/218) was protected-squashed at
20:47:31 UTC as `ff1dc989f63d8a67cfa510d065aa04bb15abeb5c`. Its tree
`eabeeb7b21a8e4a07cd4bfdba981ef2486c877ac` equals the tree of the exact locally and
hosted-certified source `77e882684bf1c0de98951c5e05e805df74a559ee`. Parent and base
were `98c2b7c02fc38e6df232f374848e42536e489ab3`. Clean designated main was advanced
with `--ff-only`; local main, origin and the protected result matched at 20:47:52 UTC.

Final ordinary Auto exhaustive local certification passed all ten gates in
21,430.714 seconds, with 14,314 unit and 5,270 native passes, no failures/errors/
skips, 386 groups, all 111 histories, 111 batches and at most eight workers.
Coverage was 91.247876%; longest batch was 2,494.343 seconds and all unchanged
headroom gates passed. Fingerprint:
`63173586044f1e3f3927966581a02408900ba9eb2a4cb2364d31ae7780c9ca49`.
All 111 owned containers were independently absent. All 24 reviewed source hashes,
5,761 preserved evidence files and 14 run metadata files were verified.

Hosted run `39256627764` attempt 1 failed: shard 38 exceeded the existing 120-minute
limit after a 4,001.542-second setup; its call/teardown did not complete. Complete
selection reconciled, with 14,314 unit and 5,269 native passes plus one incomplete
native case. Its 113 artifacts, 4,527 extracted files and 500-file log archive remain
preserved. The same local case and same-fixture hosted comparison passed; successful
shard/local elapsed ratios ranged from 0.6702 to 1.3399. That supports an isolated
slowdown without proving its cause. The failed attempt remains failed.

One evidence-supported targeted retry ran on unchanged source. Shard 38
`118270642521` passed its original selected case with setup/call/teardown of
1,076.288 / 901.554 / 521.386 seconds and pytest elapsed 2,527.697 seconds.
Attempt 2 finished successfully at 20:32:58 UTC, with 122 successful jobs and three
normal alternative skips. All 118 carried successes retained their original
execution timestamps. Only shard 38, combined coverage, Full CI gate and PR gate
executed anew. The 14,314 unit and 5,270 native passes reconcile without test skips.
Combined hosted coverage is 91.252849%, with all 112 selected artifact IDs/digests
checked and the original partial shard excluded. Two new artifacts (537 extracted
files) and the complete 41-file retry log archive were preserved separately.
All exact hosted container removals were verified in logs; that is not a live
Docker inspection. No further retry or altered test/resource/time budget occurred.

Final ruleset `21093924` was active with no bypass actors and strict PR gate app
`15368`. Final CodeQL app `57789` succeeded, with exact-head analyses `1980819950`,
`1980817628` and `1980815371` covering Python, JavaScript/TypeScript and Actions,
all without results/errors/warnings. Fresh Copilot review `5571991517` reported
no open issues. The valid ownership finding was repaired and resolved on evidence.
All conversations were resolved; the merge used an exact-head match and no bypass.

Nine earlier full failures remain preserved. The preceding `77525db` local success
certifies only that old source; its hosted acceptance was cancelled for ownership
repair. The original successful `.local-ci` and all archives remain intact.
Earlier current-only timing savings are one diagnostic observation, not a hosted
or repaired-source speed guarantee. No production or human acceptance is claimed.

## Next bounded outcome and change map

The maintainer's continuing authorization permits one useful bounded task after
verified CI delivery. Fresh roadmap and live issues keep Programme deferred and
Workforce at its real recipient-password boundary. Catalog's delivered API baseline
already identifies retries, concurrency and dependency rollback as missing evidence.
This increment therefore tests exactly the existing Catalog draft-creation boundary.
It advances issue #36 without closing that umbrella or accepting its broad future scope.

Catalog owns `CatalogDetailApi`, `create_catalog`, the edition catalog and immutable
receipt. Authorization retains tenant/edition/principal policy; Audit and Effects
retain their append contracts. No runtime, schema, migration, profile, permission,
authentication, public error, generated schema or dependency changes are introduced.
No architecture decision or requirement is reversed. Fictional demos are unaffected.

The 12 new native cases cover two original-metadata/version replays, three rejected
actor/key/blank-reason retries, two edition/organization key boundaries, two late
evidence-write rollbacks and three controlled concurrent creates. Existing case
bodies and assertions remain intact. The complete module selects 40 cases.

Concurrency uses independent connections and observes both actual PostgreSQL
edition-row lock waits before release. It proves only stable-authority competition;
revocation, closure and profile changes during a command remain outside this slice.
Dependency faults are injected after real event/outbox or audit writes. The caller
sees the existing unhandled exception, followed by no persisted partial evidence;
same-key recovery must create anew. This does not promise a public `503` response.

Changed valid retry rationale currently preserves the original receipt; it does
not amend approval history. Recording that observation does not decide whether a
future supported integration policy should include reason in its digest. All
compatibility choices in the owning conformance plan remain explicit and open.
In-process authenticated test principals do not prove password/session/CSRF,
restricted runtime roles, browser journeys or production readiness.

## Verification and remaining gates

The complete 40-case native module passed on source digest
`f750a021de354d03d8eb557dc8690641dd33f8816a93689e0c65fef122973f22`:
12 new cases and all 28 existing cases, zero failures/errors/skips, 243.83 seconds
in pytest and 250.329 seconds including runner work. Verification at 21:03:32 UTC
reconciled all 3,240 before/pre-run/after/live source entries, all 25 artifact hashes,
exact case names and all 18 original function/class definitions. The exact owned
container was independently absent. Nine unrelated stopped fixtures were preserved.

All 14,314 unit cases passed in 86.63 seconds. Those units preceded a test-only
keyword-forwarding correction found by source review in the fault helper; the
complete native run includes that correction. No failed native attempt occurred.
Scoped Ruff lint/format, documentation validation (765 Markdown files, four skills,
223 requirement identifiers) and whitespace checks passed. Source was released only
after verification, before recording these focused results in documentation.

Clean-commit ordinary Auto certification, independent hosted acceptance and
protected delivery remain pending. Every failure must be preserved and investigated;
source changes invalidate previous certification.
The unrelated Workforce worktree and human-password boundary remain untouched.
Issues #36 and #42 stay open.
