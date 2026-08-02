# ADR 0046: Non-delegable genuine runtime database login

- Status: Accepted
- Date: 2026-08-02
- Supersedes: only the runtime database-role boundary in ADR 0044
- Requirements: AUD-001, AUD-005, NFR-001, NFR-002, NFR-004, NFR-008,
  and NFR-010

## Context

ADR 0044 introduced a named PostgreSQL runtime role and a catalog probe, but
its first contract accepted `CURRENT_USER` after an owner used `SET ROLE` and
required ordinary DML on every application relation. That is not sufficient
proof of the credential that authenticated the backend, and it gives the
application login mutation access to the exact-provenance marker and
generation latch that select the authorization policy.

PostgreSQL exposes other authority paths that do not require ownership or an
obviously privileged role attribute. A reachable role can carry membership
`ADMIN OPTION`, an object ACL can carry a grant option, sequence `UPDATE` can
invoke non-transactional `setval`, and a parameter ACL or persistent
role/database setting can select `session_replication_role=replica` and disable
ordinary integrity triggers. A role name beginning with the reserved `pg_`
prefix is not an application-controlled identity even when it is the target
itself.

The marker and latch must remain readable by policy and health. Ordinary
authority writers also take a row lock on the latch. PostgreSQL requires
`UPDATE` for that row lock, so a select-only runtime login cannot execute that
lock directly as invoker. Finally, ordinary audit INSERT is intentionally part
of the runtime data plane, but the reserved activation operation must not be
forgeable without its exact same-transaction marker and latch transition.

## Decision

### Fixed 25-part proof

`database_role_safety.py` returns exactly 25 identifier-free booleans:

1. role exists;
2. login is allowed;
3. direct/reachable dangerous attributes are absent;
4. membership, reserved-name, predefined-role, and reachable `ADMIN OPTION`
   paths are safe;
5. current-database ownership is unreachable;
6. non-system schema ownership is unreachable;
7. non-system relation ownership is unreachable;
8. non-system function ownership is unreachable;
9. database creation and temporary-object privileges are absent;
10. non-system schema creation is absent;
11. table trigger, truncate, and maintenance privileges are absent;
12. no explicit effective PostgreSQL parameter `SET` or `ALTER SYSTEM` ACL
    reaches the role through direct grant, membership, or `PUBLIC`;
13. applicable global, current-database, and target-role settings do not set
    `session_replication_role` away from `origin`;
14. the probing session currently has `session_replication_role=origin`;
15. database `CONNECT` is available;
16. every non-system schema has `USAGE`;
17. every relation has its required runtime data plane;
18. no user sequence has effective `UPDATE`;
19. every user sequence has `USAGE` and `SELECT`;
20. no grant option reaches the role on the database, a non-system schema,
    relation, column, sequence, or function;
21. `PUBLIC` and every membership-reachable runtime function-execution
    boundary are closed, including `NOINHERIT` roles reachable with
    `SET ROLE`;
22. every function in the versioned runtime allowlist is executable;
23. `CURRENT_USER` is the configured target;
24. `SESSION_USER` is the configured target; and
25. this backend's `pg_stat_activity.usesysid` is the target OID, proving the
    login that authenticated the connection.

The parameterized probe returns no role, object, membership, setting, ACL,
database error, or credential identifier. `target_role_is_safe` requires gates
1 through 22, including the probing session's live origin setting, so the
controlled owner cannot activate while triggers are disabled. It deliberately
does not require gates 23 through 25, allowing a migration/cutover owner to
inspect the future login. `current_session_is_safe` requires the target proof
and all three identity gates. Neither `SET ROLE` nor even superuser
`SET SESSION AUTHORIZATION` is accepted as a runtime session.

The target name itself and every reachable membership are rejected when their
case-folded name begins with reserved `pg_`. Membership traversal is
conservative across PostgreSQL 17 inheritance/set-role options, and any
reachable `admin_option` edge is a failure.

### Select-only control relations

The exact protected-relation set is versioned in code and contains only:

- `public.django_migrations`;
- `public.authorization_authorityprovenanceactivation`; and
- `public.authorization_provenanceactivationlatch`.

Runtime must have table-level `SELECT` on all three and must have no effective
table- or column-level `INSERT`/`UPDATE` and no table-level `DELETE`. Every
materialized view is likewise SELECT-only. Other current runtime relations
retain `SELECT`/`INSERT`/`UPDATE`/`DELETE`; all sequences retain only
`USAGE`/`SELECT`.

Web and worker processes read migration history during readiness but never
write it. Only the separately credentialed migration role records an applied
or reversed migration. This prevents a compromised runtime session from
inventing or removing the recorder evidence used by the exact schema contract.

The provisioning specification applies explicit migration-history and
marker/latch DML revokes after blanket and default table grants and explicitly
revokes sequence `UPDATE`.
Activation and any recovery mutation run only as the audited, controlled
migration/cutover owner. Web and worker logins only read the committed controls.

Provisioning is one transaction: an unavailable role, relation, function
signature, or grant aborts the complete change instead of leaving global
`PUBLIC` revokes or a partial runtime plane committed. Before those defaults
are closed it explicitly preserves database `CONNECT`/`CREATE`/`TEMPORARY` and
schema `CREATE`/`USAGE` for the named migration role. Existing Maru objects
must already be owned by that role (or a deliberately inherited owner role);
the provisioning file never guesses or performs a broad ownership transfer.

The invoker-security latch-lock trigger calls a separate narrowly scoped
`SECURITY DEFINER` helper owned by the controlled migration owner. The helper
has a fixed trusted `search_path`, schema-qualified objects, a readiness
fingerprint, and explicit runtime execution only through the v2 allowlist;
`PUBLIC` remains closed. It performs only the writer-barrier row lock/read
needed by the trigger and does not expose a general mutation API.

Audit's reserved `authorization.authority_provenance.activate` INSERT is
separately guarded at the database boundary. It is accepted only for the exact
frozen marker/audit shape, matching marker and latch, and the marker's current
transaction. Orphan, malformed, or later reserved rows are rejected while
ordinary audit appends remain available to runtime. This is a companion
invariant; it does not change the marker contract or lineage meaning.

### Nondelegation and trigger integrity

The runtime role receives no object grant options and no reachable membership
admin option. This includes column ACLs, which can otherwise reintroduce
INSERT/UPDATE after a table-level revoke. Sequence `UPDATE` is always denied
because `setval` can durably disrupt issuance ordinals even when the surrounding
transaction rolls back.

Every explicit effective parameter ACL is rejected, not only the currently
known dangerous parameter. Provisioning explicitly revokes `SET` and
`ALTER SYSTEM` on `session_replication_role` from both `PUBLIC` and runtime.
Applicable persistent settings and the live value are checked independently;
one cannot compensate for the other.

### Deployment and extension rule

The runtime credential is provisioned through the secret manager and is never
placed in SQL examples, test output, health output, or logs. Release evidence
must include a fresh password- or managed-identity-authenticated connection,
not an owner session after role switching. Every pool is restarted at cutover.

Adding a non-system schema, relation kind, protected control relation,
sequence, function, parameter privilege, foreign-data surface, or other
database authority plane requires a reviewed extension to the probe,
provisioning specification, readiness fingerprints, and real PostgreSQL
tamper tests before deployment. Unknown future surfaces are not assumed safe.

## Consequences

- Public readiness now proves the genuine application login and cannot be
  satisfied by owner impersonation.
- The runtime application cannot activate, acknowledge, reset, delegate, or
  disable the database integrity boundary while retaining its ordinary data
  plane.
- Migration-owner activation remains possible, but only with live trigger
  semantics and a separately proved future runtime role.
- Provisioning and schema changes require explicit negative ACL maintenance in
  addition to ordinary positive grants.
- PostgreSQL 17 catalog and real-login tests become release evidence, not an
  optional local smoke.

## Alternatives considered

### Keep `CURRENT_USER` as the only identity proof

Rejected. `SET ROLE` changes it without changing the authenticated backend.

### Add `SESSION_USER` but omit backend identity

Rejected. A superuser can use `SET SESSION AUTHORIZATION` to change both SQL
identity values. The backend activity identity remains the independent proof.

### Grant runtime UPDATE on the latch for `SELECT FOR SHARE`

Rejected. It would make a cutover-control mutation privilege part of the
  application data plane. A fingerprinted narrow definer helper is smaller.

### Check only direct ACLs

Rejected. Membership, `PUBLIC`, column ACLs, grant options, role/database
settings, and parameter ACLs are effective authority paths.

### Trust application code not to use `session_replication_role` or `setval`

Rejected. Direct SQL and compromised runtime code are within the database
threat model; durable invariants must reject the privilege itself.
