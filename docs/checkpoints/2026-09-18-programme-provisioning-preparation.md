# Isolated Programme migration/runtime provisioning preparation

Date: 2026-09-18
Scope: #108's disposable fixture beneath #48; current-schema preparation only.

The test-only provisioner requires the tracked native policy, explicit run and
exact still-owned Docker identity/port before opening any connection. It verifies
database name, genuine administrator session/current user and PostgreSQL 17,
rejects pre-existing migration/runtime roles, and generates distinct credentials.
DDL ownership moves to a non-superuser migration role. Migrations run through
that real login in a separate process; no role impersonation or fake migration
is used.

Runtime provisioning consumes the existing operations SQL at normalized SHA256
`9a7ee52f30eb2dd071e548676999934a10faf296280d4a83b5a8cbbcdec15c17`. Exactly five
database-name references change to the run-scoped identifier; role/relation/
function grants do not change. Source drift fails closed for deliberate review.
A second process logs in as `maru_runtime` and runs the real owner role-safety
probe before an endpoint may be returned. The endpoint contains a generated
credential: its representation hides it, but callers must not log or serialize it.

Child settings inherit base, not local/test settings. They retain exact authority,
step-up and edition-closure controls, without test authorizers, fake migrations or
silenced checks. Ambient database/provider secrets and Python/settings overrides
are excluded from child environments. Process/driver errors are minimized. Email
uses in-memory storage for these non-serving provisioning processes; this is not
invitation-delivery acceptance. No application requests or domain setup occur.

Focused pure/mocked feedback passed **145 cases in 0.49s**, including 47 new
provisioning cases. Ruff lint and formatting passed after corrections. Complete
database-free feedback passed **10,430 cases in 59.86s**, with three existing
URLField warnings. Clean exact-commit certification remains pending.

One host-only native case is maintained separately from ordinary discovery and
the eight-worker pool. It requires actual migrations and role-safety verification,
independently checks genuine runtime identity and migration ownership, proves
runtime DDL denial and refuses re-provisioning existing roles in the same owned
fixture. It remains **uncollected and unexecuted** under #102, alongside the four
transport cases. Mocks do not certify schema, role permissions or recovery.

There was no Docker invocation, database connection, migration, role provisioning,
native collection or browser/server launch. Existing profile registries, candidate
registration, schema installation, domain records and authority remain unchanged.
Next: isolated candidate installation/startup, real setup/role scenarios and
P01–P12, then mandatory #102/#97/#92/#109 acceptance before promotion. The
provisioner does not extend the containing resource lease; a partial failure must
discard that resource rather than retry or repair an existing installation.
