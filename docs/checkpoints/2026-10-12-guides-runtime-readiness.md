# Guides runtime readiness diagnosis — 2026-10-12

## Failed complete run

Full certification of `548658b74405bf33e8df2504024fdbb3dfc5649b` against
`bc09e8b63e4142c712178a067a123c61b0924e2f` ended with failure after
17812.875 seconds. 81 database batches passed. Shard 81 passed 922 cases but
failed `test_genuine_runtime_login_is_safe_and_persistent_replica_setting_is_not`
when `/health/ready` returned Knowledge integrity unavailable. Five other active
batches were interrupted by fail-fast, not independently proven faulty.
All 87 owned containers were removed. The entire 4,955-file evidence inventory
(502,136,743 bytes) is retained in the run's `failed-local-ci-evidence` directory.
No success receipt exists; units alone do not certify this candidate.

## Bounded diagnosis

KNO-010–013, NFR-001 and ADRs 0118–0119 retain genuine runtime and exact integrity
requirements. ADR 0113 still rejects physical schema differences. The next
source-pinned diagnostic runs the original genuine-login assertions first on a
fresh schema, then after the preceding real historical ACL migration case and
normal current-graph restoration. Data-free observations report integrity flags
and schema digests without changing the values returned by readiness checks.
The competing causes are not yet established. No production guard, permission,
schema fingerprint, assertion or test budget is changed.

## Remaining boundaries

A repair needs focused proof and new exact-commit full certification. Browser,
human, accessibility and operational acceptance remain separate. The existing
V6 credential-entry refusal remains binding and its stopped fixture is preserved.
The ongoing/future demo coverage gap is unchanged by this diagnostic work.

## Reproduction and scoped repair

The source-pinned diagnostic completed with one pass and one failure in
755.72 seconds (762.281-second wrapper). Fresh genuine runtime authentication,
role safety and all readiness checks passed. After the real historical ACL
round trip and normal current-graph restoration, `events_eventedition` changed
from the expected `44d54921e563ab839bb9ae15685dd0768fdf48ab5e5e0c327ce1a9679d4b4d47`
to `2ce6bdddd6c59d8436116490474394bf82fcc03e0ced94f2df5bd9d3bd222fe8`.
The unchanged schema check correctly refused that altered test database.
Identical before/after source inventories and exact owned-container removal are
verified. The failed diagnostic remains under `.tools/guides-runtime-diagnostic-20261012`.

Only the serial, empty ACL round-trip case now uses the existing
`rollback_migration_case` helper. All original migration, sentinel ACL, hardened
function ACL and reversal assertions remain. `migrate_test_targets` rejects
non-atomic plans inside this boundary; ordinary cases keep their normal plans.
New assertions require the original complete Guides setup schema and readiness
after rollback. No production schema, pinned digest, permission, native guard or
runtime assertion changed. Focused validation of the historical case followed by
the original genuine-login regression remains pending.

## Non-atomic boundary retained

The first repair was rejected by the existing atomic-plan guard before any
historical transition: Identity 0016 uses concurrent indexes. That failed
192.16-second native attempt and unchanged-source/owned-cleanup evidence remain
in `.tools/guides-acl-isolation-20261012`. The guard was not relaxed.

The revised test uses `isolated_migration_database` to create a fresh empty
`test_maru_history_*` database on the same owned test server. Its original real
historical migrations establish the baseline and execute the ACL round trip in
autocommit, with all assertions retained. The helper copies no schema or rows,
adds no container or worker, verifies created name/OID/owner before cleanup,
and never force-drops or terminates connections. The original current database
is restored on success or failure; its exact schema/readiness assertions remain.
Native helper regressions exercise actual concurrent index creation, different
schemas and rows, cleanup and reconnection after both success and a raised error.
Unit cases refuse non-test, non-PostgreSQL and active-transaction boundaries before
SQL. Complete certification and unchanged timing limits remain required.

## Focused verification completed

All four native cases passed in 207.34 seconds (213.516-second wrapper):
committed-isolation success and raised-error cleanup, the original historical ACL
round trip, and the original genuine-runtime login/readiness/unsafe-setting case.
Source inventories both equal
`9515c00a4a61b2ef1f1a011748e273c4f2263bad960f7933e44cec12ba7ec987`.
The exact owned container was removed; its identity and zero remaining matching
resources were checked. Evidence remains at
`.tools/guides-committed-isolation-20261012/native-reserve-20261012T030052Z-1905a255`.
This validates the selected historical isolation and real runtime regression,
not the entire Guides candidate or its unrun browser journey.

Focused support units passed 29 cases in 0.55 seconds. The first complete unit
attempt passed 13,750 cases but had 493 setup errors, all reporting access denied
to the shared Windows `pytest-of-TheMw` temp directory. That failed log remains
untouched. A fresh task-owned temporary directory, without changing shared temp
permissions or source, allowed all 14,243 units to pass in 74.68 seconds.
Scoped lint, format, documentation and whitespace checks passed. A new clean
exact-commit full certification remains mandatory with the same coverage,
worker, native-history and measured-headroom requirements.
