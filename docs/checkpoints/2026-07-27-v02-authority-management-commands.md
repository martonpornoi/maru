# V02 authority-management command boundary

- Date: 2026-07-27
- Phase: Platform foundation V02
- Related requirements: IDN-002, IDN-004, IDN-005, HR-004, AUD-001, INT-002,
  NFR-001, NFR-003, NFR-004
- Related ADRs: 0002, 0003, 0005

## Outcome

Maru now has command-owned root grants, revocation, immutable role-bundle
versioning, role assignment, and role revocation. Direct ORM editing remains a
bootstrap/test concern; the ordinary administrative pages stay read-only.

The successful authority spine is:

```text
actor policy + independent approver policy
  -> controller scope and expiry ceiling
  -> locked tenant and canonical authority record
  -> separate correlated actor/approver audits
  -> minimized domain fact
  -> transactional security outbox
```

Revocation uses one explicit controller so removal is not delayed:

```text
revocation policy
  -> locked tenant and authority record
  -> revoker and reason provenance
  -> immediate policy invalidation
  -> correlated audit, fact, and outbox
```

## Decisions

- Root grants and role changes require an actor and a distinct approver.
- A recipient cannot approve their own new authority. An actor may request
  their own authority, but another controller must approve it.
- Both controllers need the exact management capability in the requested
  organization/edition scope.
- A new grant or assignment cannot outlive either controller's active direct
  grant or role assignment.
- Relationship-derived capabilities remain policy relationships and cannot be
  persisted as root grants or role-bundle entries.
- Revocation is single-control by design. Prolonging unwanted access is a
  greater risk than requiring a second approval to remove it.
- Issuance reason and revocation reason are separate fields. Revocation never
  overwrites the historical issuance rationale.
- Actor and approver receive separate audit events because they are separate
  exercises of authority.

No new ADR was needed. These commands make ADR 0003's scoped, reviewable,
expiring, revocable authority and approval obligations executable, while ADR
0005 governs their atomic domain facts and outbox delivery.

## Changed areas

- Added non-delegable `authorization.grant_direct`,
  `authorization.manage_roles`, and `authorization.revoke` capabilities.
- Added direct-grant, grant-revocation, role-version, role-assignment, and
  assignment-revocation application commands.
- Added persistent approver, revoker, revocation-reason, and role-version
  provenance.
- Registered five minimized authority domain-event schemas.
- Added actor/approver audit correlation and security workload routing.
- Extended read-only Django administration to show issuance, approval, and
  revocation provenance.
- Clarified IDN-005 and MARU-AUT-002 acceptance around independent control,
  authority horizons, and immediate removal.

## Verification

- 227 PostgreSQL tests pass.
- The authority command module has 99% branch-aware coverage.
- Repository branch-aware coverage is 93%, above the 90% gate.
- Ruff formatting and lint pass.
- Strict mypy passes 82 source files.
- Migration drift check passes with the new additive migration present.
- Django local and production deployment checks pass.
- Documentation validation passes.

Tests exercise success, missing permissions, same-person approval, recipient
self-approval, unknown and relationship-derived capabilities, missing or
cross-tenant targets, scope requirements, effective intervals, controller
expiry ceilings from direct and role authority, duplicate active authority,
immutable sequential role versions, descendant invalidation, repeated
revocation, and forced outbox rollback for every command family.

## Migration and recovery notes

Authorization migration `0003` adds nullable approver/revoker references and
blank reason fields so existing grants, role versions, and assignments remain
valid. New command-created records always populate their applicable
provenance.

Rollback of the schema migration removes only the new provenance columns; it
does not reverse authority decisions already represented by `revoked_at`.
Before schema rollback, preserve audit/domain-event evidence and verify whether
operators need the new reason fields for an investigation.

The command transaction rolls back authority state, successful audits, domain
facts, and outbox messages together. A safe error audit is written after the
rollback. Retrying a failed command should use a new correlation identifier
until general write idempotency is implemented.

## Known risks and incomplete work

- Initial production bootstrap of the first two independent controllers is not
  yet a documented operator procedure.
- Independent approval is a synchronous service invariant, not yet a pending
  request, inbox, notification, or expiry workflow.
- Grant review reminders, step-up authentication, purpose binding,
  department/resource scopes, and service/device principals remain.
- The effects worker is not yet supervised, fairly scheduled, or monitored.

## Recommended next actions

1. Build the supervised effect-worker entrypoint and fair tenant scheduler.
2. Add authorized, audited replay plus operational metrics and alerts.
3. Complete V02 activity projections and recovery evidence.
4. Document and rehearse initial controller bootstrap and recovery.
