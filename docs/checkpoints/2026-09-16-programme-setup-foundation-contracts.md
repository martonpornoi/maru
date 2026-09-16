# Dormant Programme setup input and owner references (#108)

The first setup implementation boundary adds an Events-owned closed input and
retry-digest contract and an Organizations-owned minimized foundation reference.
It does not yet provide a setup writer, durable receipt, authority activation,
HTML page, integrated fixture or Programme profile. No schema changes are included.

Requirement mapping: IDN-011/012, EVT-001/002/006/007, HR-009, UX-020/030 and
NFR-013 under ADR 0081. The [setup page contract](../product/page-contracts/programme-operations-adoption-setup.md)
and Events/Organizations module documentation record the original-intent boundary.

Input validation covers all three create/reuse modes, typed non-nil owner IDs,
an exact original source fingerprint, names, IANA zone, calendar-date interval,
the Workforce-owned Department normalizer and a bounded accountable reason.
Inapplicable hidden fields fail rather than being ignored. Canonical Unicode and
spacing produce one request digest; changing any semantic fact changes it.
This digest grants nothing and does not itself prove actor/key replay correctness.

The reference reads only the exact admitted organization and active same-parent
series, when requested. It returns organization defaults and truthful existing
representation metadata, never people, appointments or contact data. Missing,
foreign, inactive or incoherent sources produce no partial context. Its ordinary
reads are preview evidence, not a transaction: later writes must lock/reload and
compare complete owner facts, while visible consumers own independent admission,
audit and final disclosure checks. Current representation definitions are unchanged.

Focused feedback passed 156 database-free cases. Ruff, strict mypy and configured
NumPy docstrings passed after correcting initial formatting/complexity issues and
typing nullable reverse-one-to-one values explicitly. A mistaken `python -m
pydoclint` invocation could not run; the configured executable passed. Six native
PostgreSQL cases are maintained for the outer join, exact-parent series, source
version changes, inactive series, retained provisioning root and malformed IDs.
They were neither collected nor executed; #102 owns that verification debt.

The first complete unit run passed 9,103 cases and failed only the diagnostic
whole-file timing inventory equality check for the new native test file. Its
29.955-second entry is the documented median fallback, not an observed duration
or native acceptance. No existing weight is lowered; the authoritative group
planner keeps its conservative largest-known fallback for unmeasured groups.

The corrected complete database-free feedback passed 9,104 tests in 54.35s with
three existing Django URL-field deprecation warnings. Documentation validation
passed 587 Markdown files, four skills and 215 requirement IDs; semantic Python
documentation validation passed 713 source files. The sandbox initially prevented
the Python launcher from starting; the approved local execution completed normally.

Before delivery, run fresh clean exact-commit deferred certification, then the
protected hosted gate.
No prior receipt certifies this branch. No schema-only observation or new human
rehearsal has occurred for these pure/reference contracts. Schema-only observation
is now authorized for later setup schema; PostgreSQL suites remain deferred.

Next connect durable owner receipts and explicit scoped operator authority,
transactional orchestration, genuine-person continuation and the isolated fixture.
Do not widen `maru-operators@1`, invent a representation, collapse Department
review into edition planning authority, or infer new permissions from navigation.
#108 and the final #102/#97/#92/#109 gates remain open.
