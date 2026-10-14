# Guides historical schema isolation

- Date: 2026-10-11
- Requirement: NFR-001; retained KNO-010 and ADR 0113 integrity boundaries.

Full certification of `34a3103` failed after 2231.485 seconds. Thirteen database
batches passed. Shard 10 passed its historical Applications conversion round trip,
then all 15 Guides foundation cases failed at the setup integrity boundary.
Seven other active batches were interrupted by fail-fast. All owned containers
were removed; no success receipt exists. Complete artifacts remain under
`.tools/guides-certification-34a3103/failed-local-ci-evidence/`.

The source-pinned fresh-versus-roundtrip probe failed its final readiness assertion
in 434.99 seconds (441.36-second wrapper), with unchanged source and owned cleanup.
Before the real round trip, readiness passed and `adoption_revision` occupied
column slot 18. Afterward, slot 18 was dropped and the recreated column occupied
slot 19. The other four Guides setup relation digests were unchanged. The probe
is retained under `.tools/guides-schema-diagnostic-20261011/` with source digest
`54cbb6c379fc5d0cbdf5b2effae394808b3e607eb0cd584188d4d39276d2f344`.

ADR 0113 deliberately retains physical column positions and dropped slots.
No production fingerprint, migration or readiness rule changes. The empty,
single-connection historical test instead uses the existing PostgreSQL DDL
rollback helper. It executes the real reverse and forward plans, rejects non-atomic
migration plans, retains all old assertions and checks deferred constraints before
rollback. New assertions require the original complete Guides setup relation
fingerprints and ready state after isolation. Commit visibility and concurrent
migration tests are not changed by this scoped repair.

All 16 focused history-plus-current cases passed in 492.60 seconds
(498.906-second wrapper), without failures, errors or skips. The before/after
source inventories matched
`edb756c293dd61ece677217c264707edaba8e388ffc1192df8cb321d16a564e7`;
the exact owned container was removed. Evidence remains under
`.tools/guides-schema-repair-20261011/native-reserve-20261011T092606Z-260f10d1/`.
Scoped lint, formatting and documentation checks passed. Fresh full exact-commit
certification remains required. Browser and operational acceptance remain open. This test-only
repair does not change ongoing/future demo samples. CURRENT's accidentally
misencoded range punctuation is also repaired using explicit UTF-8.
