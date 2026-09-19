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
