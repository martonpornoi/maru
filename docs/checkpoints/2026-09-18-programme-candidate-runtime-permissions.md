# Programme isolated runtime permission preparation

Date: 2026-09-18

## Outcome and scope

Continuation of #108's recorded complete-fixture prerequisite under #48, after
protected PR #168 (`cc4cb08077ba4cc7b167fa798abb1050c28915db`). NFR-013,
PRG-001 through PRG-011, SCH-001 through SCH-012, INT-007, OPS-009 and ADRs
0081/0083/0100/0106 remain authoritative. This prepares actual runtime permission
verification; it does not activate Programme or finish the fixture.

The closed test-only permission inventory names 82 dormant relations and their
required INSERT, UPDATE and DELETE operations. Row-lock needs include retained
sources and the contributor-response command's joined profile revision. Native
immutable evidence guards remain mandatory. Only draft call tracks/formats need
all three operations. Migration history, provenance activation/latch, invitation
retention policy, native audit witnesses and Scheduling dependency-change history
remain SELECT-only. Production ACL SQL and production relation classes are unchanged.

The explicit write option requires candidate schema, then canonical provisioning
and its actual baseline runtime probe before an owned empty-schema ACL transaction.
The transaction checks the exact live resource, actual identity/PG17, migration
history, empty locked edition table and read-only target baseline. Four statements
grant only declared table DML. Failure requires exact owned-resource disposal;
there is no partial installation retry or existing-resource adoption.

A fresh isolated candidate child declares five relation classes and invokes the
unchanged real native role-safety query. No authorizer, result, probe, function
allowlist or native guard is replaced. Guarded construction installs the same
contract and denies table/column REFERENCES through current and SET-reachable
roles, including the two ordinary-CRUD tables. No ownership, DDL, grant option,
TRIGGER, TRUNCATE or MAINTAIN permission is added.

## Discovered receipt lock incompatibility

Generic, Programme and import retry readers requested FOR UPDATE on immutable
own/cross-family receipts, even for empty lookups. That requires UPDATE despite
canonical runtime SELECT-only/SELECT+INSERT limits. All three now retain their
existing shared edition/actor/retry transaction advisory lock and use plain reads.
The native insert guards use the same namespace; immutable receipts do not need
separate row locks. Admission, request-digest conflicts, foreign-family collisions,
aggregate locks, audit and writes are unchanged. No runtime grant was broadened
to work around this production-path incompatibility.

## Verification actually performed

- Focused fixture/provisioning/startup/retry feedback: 146 cases in 0.88s before
  the final additional drift/lock-closure checks.
- Complete database-free unit feedback: 10,561 passed in 69.85s; three existing
  Django URL-field transition warnings. Focused Ruff checks passed.
- Earlier iteration found two stale assumptions: an old chained receipt-lock
  mock and missing timing inventory for a proposed new native file. The assertion
  now matches plain reads; the native regression lives in the existing runtime-role
  test file. No historical weights were invented or inventory checks weakened.
- Exact-head retained certification and hosted acceptance are pending at this
  preparation checkpoint; no earlier receipt certifies this branch.
- No PostgreSQL collection, database/server/container startup, migration,
  schema-only execution or browser acceptance occurred.

## Maintained native debt and next work

`programme_provisioning_native.py` now holds five host-only cases, including a new
candidate-write mode. Three provisioning variants inspect all 82 actual table
privilege matrices, genuine runtime/owner identities and denied DDL. The existing
runtime-role integration file additionally checks five immutable receipt families:
the old lookup must fail with SQLSTATE 42501, while two genuine plain retry reads
use the advisory lock and need no UPDATE. These remain uncollected/unexecuted
under #102. They are not full user-journey or concurrency acceptance.

Finish genuine provenance/invitation readiness, three truthful setup modes,
separate synthetic people's own role actions, owned HTTPS serving and the P01–P12
runner. Then restore required PostgreSQL policy through protected delivery and
collect actual native, recovery, human and integrated evidence under #102/#97/#92/#109.
Only then may final supported-profile promotion complete #108/#48. Do not relabel
synthetic actions as representative human acceptance or deploy production state.
