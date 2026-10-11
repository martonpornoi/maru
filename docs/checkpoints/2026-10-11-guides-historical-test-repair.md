# Guides historical test setup repair

- Date: 2026-10-11
- Requirement: NFR-001; retained identity/provenance and migration boundaries.

Full certification of a6fd408 stopped after shard 1 reported four failures.
Seven batches had passed; seven other active batches were interrupted by the
pool's fail-fast behavior. Every created container was removed. The complete
failed evidence remains under `.tools/guides-certification-a6fd408/failed-local-ci-evidence/`.
There is no successful certification receipt for that source.

Three accountable-lineage cases still assumed Authorization 0042 was the newest
native function definition. Guides introduces 0044 and 0047 successors. The
round-trip test now reapplies through the real 0047 target, preserving exact OID,
owner, ACL and function-state equality assertions. Direct downgrade probes unwind
0047 and 0044 before 0042, then reinstall them in forward order for the permitted
board case; all existing denial and current-provenance assertions remain.

The Participation legacy-platform-account test created an EventEdition with
current models after reversing a dependent Events field. It now creates the
ordinary event before that historical migration, matching the neighboring legacy
graph tests. The deliberately invalid Participation row is still inserted only
after reversal, and the same preflight rejection and cleanup remain required.

Scoped lint and formatting pass. All five selected native cases passed in
596.17 seconds (602.485-second wrapper), with no failures, errors or skips.
The before/after source inventories matched digest
`336c809b8a9ba5f60e4fad700bb338b6734c7768cdf6f3cad3424a8f2e69377b`.
The exact owned container was removed. Evidence remains under
`.tools/guides-history-repair-20261011/native-reserve-20261011T072641Z-ee15e013/`.
The reused diagnostic helper's scope label names the older withdrawal check;
its recorded selection and five JUnit case identities establish only the historical
test repairs described here, not a new withdrawal result.
Complete exact-commit certification remains required. No production SQL, migration source,
permission, assertion, inventory, coverage or timeout is weakened. This test-only
repair does not change ongoing/future demo samples or the unresolved browser gate.
