# Runtime database role safety boundary

Date: 2026-08-02

## Outcome

Maru now has ADR 0046's identifier-minimizing, read-only PostgreSQL catalog probe for
the explicitly configured `MARU_RUNTIME_DATABASE_ROLE`. It can inspect the
future application role from a migration-owner connection and distinguishes
that target-role proof from the stricter current-session proof used by public
runtime readiness.

This proof is now exercised by the local synthetic ADR 0044 activation and
recovery slice. It does not mean that a production runtime login has been
provisioned, that ordinary production legacy authority has been reconciled, or
that a production cutover or PITR drill has occurred.

The fixed 25-boolean contract rejects a missing/non-login or reserved-name
role; privileged attributes; dangerous, predefined, or administratively
delegable membership; database or non-system schema/relation/function
ownership; database `CREATE`/`TEMPORARY`; user-schema `CREATE`; table
`TRIGGER`/`TRUNCATE`/`MAINTAIN`; effective parameter-control ACLs; persistent or
live non-origin trigger settings; sequence `UPDATE`; and database/schema/
relation/column/sequence/function grant options. It positively requires
database `CONNECT`, user-schema `USAGE`, ordinary runtime-relation DML,
sequence `USAGE`/`SELECT`, and SELECT-only materialized-view and exact
`django_migrations`/marker/latch access. The versioned v2 execute allowlist
contains all 19 non-trigger helpers reachable from current database triggers
or direct runtime policy, including the narrow definer latch-lock helper.
`PUBLIC` may execute no
non-system function. Neither runtime nor any membership-reachable role,
including a `NOINHERIT` role available through `SET ROLE`, may execute an
unlisted function.

Migration-owner activation proves gates 1 through 22 while its live trigger
setting remains `origin`. Runtime readiness additionally requires
`CURRENT_USER`, `SESSION_USER`, and the backend-authenticated
`pg_stat_activity.usesysid` to identify the target. `SET ROLE` and
`SET SESSION AUTHORIZATION` therefore cannot impersonate a healthy login. Role
names, protected-relation identities, and function identities are query
parameters; health responses contain no role, object, membership, setting,
database-error, or credential detail.

The migration recorder and marker/latch remain mutation-owned by the
controlled migration/cutover owner. Ordinary runtime writers use the
fingerprinted narrow definer helper to take the required latch row lock without
obtaining latch `UPDATE`. Audit's
reserved activation operation is independently guarded to require the frozen
same-transaction marker/latch/audit shape; ordinary audit appends remain part
of the runtime data plane.

Production settings require the role name. CI and the production-settings
verification exercise both explicit authority-provenance fence modes. The
public exact-provenance health path now requires the complete fingerprinted
runtime contract before it proves that its current database user is the safe
configured role.

## Operator boundary

[`postgresql-runtime-role-provisioning.sql.example`](../operations/postgresql-runtime-role-provisioning.sql.example)
documents a credential-free PostgreSQL 17 provisioning baseline with explicit
post-blanket migration-recorder/marker/latch DML, sequence-update, and
parameter-control revokes. Operators must adapt identifiers, provision
credentials through the secret manager, and rehearse grants and default
privileges before a production activation.
The executable example is transaction-wrapped and explicitly preserves the
named migration role's database and schema DDL plane before closing `PUBLIC`;
existing-object ownership remains a reviewed prerequisite rather than an
implicit or broad reassignment.

## Verification

- combined runtime-role unit and real PostgreSQL matrix: 50 passed, including
  all six grant-option surfaces, membership admin option, parameter-trigger
  suppression, sequence update, table/column cutover-control mutation,
  a `NOINHERIT`/`SET ROLE`-only function escape, `SET ROLE`/`SET SESSION
  AUTHORIZATION` impersonation denial, wrong-password rejection, and one
  genuine password-authenticated login;
- the genuine login passed all three identity gates, read all three protected
  control relations, received SQLSTATE `42501` for direct
  INSERT/UPDATE/DELETE on each, and completed active exact-mode `decide` plus
  batched issuance projection;
- the genuine runtime backend also received the exact minimized 200 response
  from the real public `/health/ready` endpoint after activation and complete
  catalog verification;
- a persistent role/current-database `session_replication_role=replica`
  survived reconnect and failed both stored-setting and live-origin gates;
- active projection resolves every tenant target through five fixed queries;
  exact issuance checks add one database call per 256-item chunk. This bounds
  query amplification but does not close the representative unbounded
  candidate-cardinality latency and memory gate;
- organizations `0013`, workforce `0005`, and authorization `0009` harden and
  fingerprint four direct runtime helpers plus 12 persistent callers, with 57
  of 57 security-critical definitions and all 12 exact trigger attachments in
  readiness. Fresh hardening passes 9 tests; the corrected fence/hardening
  rerun passes 10; populated organization/workforce history passes 31;
- hostile-path, shadow-relation, body/config tamper, trigger detachment/shape,
  missing-recorder, ACL/OID symmetry, and activated-downgrade regressions pass;
- the transaction-wrapped provisioning artifact has an automated late-failure
  rollback proof and a successful 22-of-25 owner-session proof. It preserves
  the migration DDL plane, grants the three runtime controls SELECT-only, emits
  no credential, and leaves no synthetic role behind;
- production settings in both exact modes, OpenAPI/generated-client
  determinism, 19 frontend tests, frontend build, Python and Node dependency
  audits, Ruff, mypy, Django checks, migration drift, whitespace, and
  documentation validation pass; and
- the definitive fresh current-graph repository invocation applies all 117
  migration-plan entries and passes 1,199 tests in 930.63 seconds with 90.33
  percent branch coverage and no warnings.

These are separate focused invocations and are not an aggregate test count.

## Integrated readiness behavior

The authority-provenance readiness report evaluates the configured future
role with `target_role_is_safe`, because activation runs through the migration
owner. Public runtime readiness deliberately uses `current_session_is_safe`.
Both paths fail closed with minimized output. Their local evidence supports the
activation implementation, not a claim that a real deployment has completed
its role transition, legacy reconciliation, cutover, restore, or PITR exercise.
