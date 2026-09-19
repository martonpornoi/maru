# Programme exit item collection preparation

Date: 2026-09-19
Status: local preparation for #189 within #108/#48, not exit acceptance

## Contract and implementation

EVT-007, INT-007 and ADR 0081 require each owner's authorized retained evidence,
not a database dump or public timetable pack. The new Programme item collector
composes the existing core, host roster/history/current dependencies, and complete
fixed-ceiling staffing histories through their actual public owner readers.

All six independent field/capability sets are checked before collection and again
before disclosure. The outer audited transaction calls the host roster first:
its canonical parent/edition and complete person locking precedes actor-only core
locking. Current item identity/version/lifecycle and exact host/dependency sets
must agree. Retained histories must be contiguous and reach their current source
projections. Overflow, gaps, repeated pages, missing evidence and audit failure
refuse the whole result. No private data appears in the composed DTO repr.

The existing host reader ceiling excludes historical exact availability and
invitation copy; currently withheld or ended availability is not reconstructed.
Retired staffing requirements remain retired, never renewed work or Shift proof.
No new capability, current profile, route, migration, runtime grant, dependency,
CI policy, production data, destructive operation or unrelated-domain write.
Unused read composition can be removed without a data migration.

## Verification and remaining work

Database-free focused composition tests cover exact scope, roster-before-core
ordering, every initial/final authorization denial, current-version/set mismatch,
audit failure, host history, staffing continuation and availability distinctions.
Two actual-command PostgreSQL cases are maintained in the existing host/staffing
test modules: ended shared availability, canonical person order, exact scope and
default-policy denial; and retired staffing history plus required final audit.
They remain **uncollected/unexecuted** under ADR 0100 and are #102 debt. Mocked
orchestration is not native locking/race, runtime or integrated acceptance proof.

Source bindings, placement decisions, owner inventory/serializers/schemas, the
other seven profile owners, authorized files, complete supported-volume handling,
retrieval reauthorization, UI, recovery, stop-use and P11/P12 remain open. Neither
#189 nor #108/#48 can be closed by this component. Exact local and protected
delivery evidence will be recorded at the delivered candidate boundary.

Focused core/item feedback passed 77 cases in 0.37s. Complete database-free unit
feedback passed 11,710 cases in 65.96s with three existing Django URL-field
warnings and a fresh repository-owned temporary directory. Ruff, strict typing,
NumPy and semantic documentation passed. These remain iteration results, not
exact certification, PostgreSQL or protected acceptance.

## Exact local certification and submitted PR

PR #193 was opened on clean head `35fedf448f07404fc993e27077bedf143a5cffdd`,
tree `ec2839b54372fc15493ffbef54f96b178d2090a2`, against protected
`d4a4f9d37d98688c907ad1a418d19cc0f00e0437`. All eight retained gates passed
in 425.043s (7m05s), completing 2026-09-19 18:22:45 UTC: 11,710 units/82.93s,
103 frontend cases and complete static/docs/contracts/security/packaging checks.
The v4 `postgresql_deferred` receipt reports zero databases and null combined
coverage/headroom. Receipt, plan, actual unit report, wheel and sdist were
preserved outside `.local-ci` with matching hashes. Receipt SHA-256:
`1308b56b7aee6ece439a049818c09f6bcb037ed726d74a8d98a7be7f46d5e17a`.
Native additions remain uncollected/unexecuted. #189/#108/#48 stay open;
the submitted PR has no closing reference. Protected acceptance is independent.
