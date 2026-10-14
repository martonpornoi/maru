# Guides full local certification and browser boundary — 2026-10-12

## Exact automated outcome

Full certification passed for commit
`c51814681ffff58ee4a60e37c01a5aec3c5b9a63`, tree
`dd4ae751fe33fb641a8256b1cf15cb905385219d`, against protected main
`bc09e8b63e4142c712178a067a123c61b0924e2f`.
It started at 03:30:26 UTC and finished at 08:48:42 UTC on 2026-10-12.
The wrapper measured 19,096.25 seconds; the authoritative version-three receipt
records success, all historical cases and 19,095.825 seconds.

All ten gates passed: locked dependencies, Python static analysis, NumPy
documentation, fresh Sphinx HTML, Django/OpenAPI contracts, staff console,
dependency security, units, PostgreSQL integration and combined branch coverage.
The unit stage passed 14,243 cases in 236.87 seconds. All 87 database batches
passed with measured timing headroom and at most eight concurrent PostgreSQL
instances. Measured coverage was 91.20 percent against the unchanged 90 percent
minimum. Every batch reports successful owned cleanup; an independent Docker
inventory confirmed that none of the 87 recorded container IDs remains.

The wrapper verified unchanged HEAD and a clean tree. The authoritative receipt
is `.local-ci/certification.json`. Complete evidence is preserved under
`.tools/guides-certification-c518146/passed-local-ci-evidence`, with a per-file
size/SHA256 inventory beside it. It is contributor evidence, not a signed hosted
attestation. Remote main was independently read back at the same base after the
run; no Guides pull request exists.

## Repairs and retained failed evidence

The completed candidate contains the integration repairs recorded in these
append-only checkpoints:

- [Historical lineage and Participation setup](2026-10-11-guides-historical-test-repair.md).
- [Conversion schema isolation](2026-10-11-guides-schema-isolation.md).
- [Historical orphan fixture](2026-10-11-guides-orphan-fixture.md).
- [Board corruption-fixture constraint timing](2026-10-11-guides-lineage-fixture-constraints.md).
- [Ordinary-authority validation order](2026-10-11-guides-control-validation-order.md).
- [Historical event fixture ordering](2026-10-11-guides-historical-event-fixtures.md).
- [Committed historical ACL isolation](2026-10-12-guides-runtime-readiness.md).

Every earlier failed full/focused attempt remains preserved. The final repair
retains real autocommit historical migration execution without contaminating the
current test database's exact physical schema. It uses a new empty database on
the same owned server, verifies its created name/OID/owner before non-forced
cleanup and restores the original connection on success or failure. Native
concurrent-index and original ACL/runtime assertions passed. The transactional
helper still rejects non-atomic migrations; no guard, source pin, coverage
threshold, worker limit or timing allowance was weakened.

## Remaining acceptance and stopping point

KNO-010–013, EVT-008, ADRs 0118–0119 and 0124 still require their applicable
adoption, reader/editor and operational acceptance. The browser checklist and
[maintainer walkthrough](../operations/guidance-maintainer-walkthrough.md) remain
unrun for the authenticated journey. Automated request/domain tests and the
older synthetic command-driven runtime fixture do not establish visible browser
behavior, independent-person comprehension, specialist accessibility or
production acceptance.

The existing V6 credential-entry approval refusal remains binding. The exact
fixture is stopped and its original volume/accounts remain preserved; its state
was checked without opening private configuration, restarting it or entering
credentials. Browser setup/combined expansion, separate role sessions, replacement
and withdrawal, stop/resume, native print/download, keyboard/no-script and
responsive checks remain outstanding. The older fixture must also be reconciled
with current source before any later authorized rehearsal.

The acceptance heartbeat is being paused because completing those checks needs
an authorized browser sign-in path. No alternate credential retrieval or fixture
restart is permitted as a workaround. No PR, hosted gate, CodeQL result, review
resolution or merge is claimed. The next delivery candidate must include final
status documentation and any acceptance fixes, with its own exact-commit proof;
this receipt certifies only `c5181468`. These status edits are left pending so
another expensive full run is not started merely while waiting for the blocker.

Ongoing/future demo coverage is unchanged and incomplete. Unrelated modules,
worktrees, stashes, stopped fixtures and paused delivery monitors are preserved.
