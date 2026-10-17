# Catalog source-review delivery and adapter baseline

Date: 2026-10-17
Status: Source review delivered; final 20-case baseline passed, exact delivery pending

## Delivered review

PR #216 protected-squashed as `de4fe1cf5ca205a1f34ce303e8baef88fc98eda3`, with tree
`97e8a53fb71e6267cd650b39ee402e10840f3454`, identical to certified candidate
`dc377521cc44022f89149d1b70db02cce35e7544`. Its parent is delivered main
`c95bb69fe7b7cc308e030563fbd4856ea5201fd6`. Designated clean main was synchronized
with a fast-forward only. Its completed heartbeat was deleted.

All ten ordinary Auto local gates passed in 5,292.976 seconds: 14,285 unit cases,
5,094 native cases in 38 batches with at most eight workers, 91.13% coverage,
measured headroom and no native failures/errors/skips. All exact owned containers
were independently absent; 5,082 evidence files and their manifest were preserved.
Fresh Sphinx output had its main landmark, two operation rows and 17 local links.

Hosted PR run 38989898731 and PR gate 117272901293 passed with app15368 provenance.
CodeQL run 38989897653 and acceptance 117269869511 passed, the latter from app57789.
Hosted documentation selection skipped native/unit/risk lanes as policy requires;
those skips are not additional test execution. Exact-head Copilot review at
01:16:29 UTC reported no findings, with COMMENTED state and no threads. Live
ruleset 21093924, current base and mergeability were verified before exact-head
squash. No bypass or protected policy changed.

## Next bounded scope

The [conformance plan](../development/catalog-edition-api-conformance-plan.md)
defines 20 native adapter cases for the existing read/create boundary and records
unresolved owner decisions separately. Existing assertions remain unchanged.
No product code, schema, permission, migration, dependency or gate changes.
INT-001, NFR-009, NFR-013, AUD-001 and existing ADRs apply; no new policy is accepted.

The initial 19 native cases passed in 219.04 seconds (225.781-second wrapper)
with no failures, errors or skips. Before, pre-pytest, after and live inventories
matched at 3,236 files; all 25 public artifact hashes verified and the exact owned
container was independently absent. All 14,285 database-free units passed in
80.73 seconds with an owned temporary directory and unreachable database URL.
Review then distinguished absent and empty retry headers: the old empty case is
retained, and one actually absent-header case brings the baseline to 20.

The final 20-case run passed in 219.28 seconds (225.906-second wrapper), with zero
failures, errors or skips. Its 3,236-file before/pre-pytest/after/live inventories
were identical; 25 artifact hashes and independent exact owned cleanup were
verified. All 11 original definitions remain structurally unchanged. Lint, format,
docs762 and whitespace passed. Both copies of the preceding 5,082-file full
certification were rehashed before the original was moved intact into its prior
run directory. No earlier result certifies this new candidate.

Complete exact-head certification and hosted delivery remain pending. The
in-process DRF client supplies authenticated test principals; it does not test
real credentials, session/Basic authentication,
CSRF, a network listener, restricted runtime or human/browser acceptance. The
separate Workforce password handoff and all its uncommitted work remain preserved.
No fixture restart or credential workaround is involved. Demos are unaffected.

Stop after this bounded evidence is independently reviewed and delivered. Keep
issue #36, the explicit behavior decisions and issue #42 open. Earlier receipts
do not certify the new source or establish production readiness.
