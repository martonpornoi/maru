# Programme candidate installation preparation

Date: 2026-09-18
Scope: #108 beneath #48; EVT-006/007, NFR-013, ADRs 0081 and 0100.

Prepared a closed explicit candidate-schema provisioning mode and a test-only
Events migration overlay. All production history remains the same physical
source; only one fixture migration follows Events 0014. It adds the exact
Programme pair/field choice without changing existing pairs, native guards or
runtime grants. The real migration login runs both ordinary current migrations
and the overlay through normal checks. Candidate registration is separate, before
model imports in a fresh policy-fenced runtime child; current manifest objects
remain identical and no production settings entrypoint activates it.

Before either schema direction, require actual run-scoped PG17 migration-login
identity, an atomic transaction and empty editions under an exclusive table lock.
Compare the validated physical constraint to an independent literal reference
deparsed by PostgreSQL itself. No guessed fingerprint or weakened comparison is
used. Both directions fail closed on use or drift. Failed runs are disposed by
their exact owned context; no fake migrations, data rewriting or partial retry.

Initial focused feedback: **81 passed in 0.84s**, database-free. The first full
unit invocation passed 10,201 cases but hit 263 setup errors because Windows
denied pytest's shared temporary folder. The retry uses a fresh repository-local
temporary directory and passed **10,464 cases in 60.40s**; no tests, thresholds
or filesystem permissions were changed. Ruff lint/format and diff checks passed.
Exact-commit certification and hosted delivery are recorded separately once done.

Maintained native provisioning evidence expands from one to four host-only cases:
current/candidate provisioning with genuine runtime/owner/DDL/history observations,
fresh-child registration/catalog validation, empty reverse/reapply and physical
constraint drift refusal. None was collected or executed. The existing four
transport/expiry cases also remain unexecuted. Doubles and migration-state graph
comparison are not PostgreSQL acceptance. No native resources or schema-only
exception was used in this increment.

Guarded joined startup and independent compatibility with the three preserved
owner dormancy checks are next, followed by genuine setup/role scenarios and
P01–P12. No complete launcher, activation, integrated proof or pilot readiness is
claimed. #48/#108 remain open; #102/#97/#92/#109 remain mandatory final gates.
