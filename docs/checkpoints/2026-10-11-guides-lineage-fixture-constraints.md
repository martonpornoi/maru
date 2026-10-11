# Guides integration: lineage corruption fixture constraints

- Date: 2026-10-11
- Requirements: NFR-001, IDN-005 and KNO-013; ADRs 0044 and 0119.

Full certification of clean `29f9c57` failed after 4484.656 seconds. All 14,239
unit tests and 30 database batches passed, including historical orphan recovery.
Shard 32 passed 68 cases and failed six parameterized Board lineage corruption
cases. Seven other active batches were interrupted by fail-fast, not independently
failed. All 38 owned containers were removed. Complete evidence remains under
`.tools/guides-certification-29f9c57/failed-local-ci-evidence/`.
There is no certification success receipt.

The existing corruption fixtures intentionally suspend selected Board immutability
checks, mutate synthetic rows, restore those checks and assert SQL lineage refusal,
then roll back. Guides adds deferred graph checks on the same role tables. Their
queued events prevented ALTER TABLE from restoring the original guards, before
the intended lineage assertion ran. The repair keeps the new Guides guards enabled
and sets only their timing to immediate inside those fixtures, as the assignment
fixture already does for the Programme stop guard. No additional guard is disabled,
no production function or migration changes, and rejection/rollback assertions stay
intact. This remains owner-login corruption testing, not runtime acceptance.

All six focused native cases passed in 205.10 seconds (211.313-second wrapper),
with no errors or skips. Before/after source inventories matched digest
`c1f3503606ba27bdd729af5a429ed5547b610bd74ea4aa90100c3d1e1ccb033f`,
and the exact owned container was removed. Evidence remains under
`.tools/guides-lineage-constraints-20261011/native-reserve-20261011T145630Z-c38e5ca3/`.
Scoped lint, format, documentation and whitespace checks passed. A changed
candidate needs fresh full certification. Browser acceptance and the preserved V6 credential refusal
remain separate gates; demo coverage is unaffected.
