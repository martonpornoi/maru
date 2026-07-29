# Checkpoint: V02 security enforcement expansion

Date: 2026-07-26  
Phase: Platform foundation V02  
Related requirements: IDN-002, IDN-004, IDN-005, AUD-001, AUD-005, QRY-001,
QRY-003, INT-001, NFR-001, NFR-004  
Related ADRs: 0003, 0005

## Outcome

The authority/audit/effects kernel now protects list/search/count, restricted
audit access, and capability delegation in addition to the original edition
detail and lifecycle mutation.

## Delivered

- Organization-scoped edition list with bounded pagination, lifecycle filter,
  literal name/slug search, and authorized count.
- Tenant filter and organization-scope policy decision occur before query
  evaluation; an edition-only grant remains detail-only.
- All edition projections fail closed if the capability field ceiling no
  longer contains the serializer contract.
- Purpose-bound audit search for security investigation, privacy request,
  compliance review, subject support, or integrity review.
- Audit search is tenant-first, capped at 100 rows, optionally filters edition,
  correlation, principal, and outcome, and audits its own allow/deny access.
- Audit results exclude safe metadata, obligations, request context, retention,
  and all domain/event payload.
- Capability delegation now requires both a delegable active parent grant and
  separate `authorization.delegate` authority.
- Delegation cannot broaden tenant/edition scope, begin before, or outlive its
  parent; the full ancestor chain is locked and revalidated before commit.
- Child grant, control audit, registered domain event, and security-workload
  outbox message commit atomically. Effect failure rolls the grant back and
  records a safe error.
- `effects_status` emits tenant/pool-bounded counts and ready/expired age
  without payload or personal labels, with an alert-friendly quarantine exit.

## API and commands

```text
GET /api/v1/organizations/{organization_id}/editions
GET /api/v1/organizations/{organization_id}/audit-events?purpose=...
python src/manage.py effects_status --organization UUID [--pool NAME]
```

## Verification

```text
Ruff format/lint: pass (99 files)
strict mypy: pass (73 source files)
migration drift: none
Django system check: pass
OpenAPI 3.1 validation: pass without warnings
pytest: 164 passed
branch-aware covered source: 92.93%
coverage gate: 90%
```

Tests demonstrate list/search/count tenant isolation, edition-grant
non-broadening, bounded page size, audit minimization and self-audit, denial
without count disclosure, bounded purpose, dual-authority delegation,
delegation domain-event correlation, and atomic rollback on delegation effect
failure.

## Data, migration, and deployment notes

- No new database migration was required after the preceding V02 kernel
  checkpoint.
- The capability catalog field ceiling for `audit.view_security` expanded in
  code and is enforced before serialization.
- Domain event
  `authorization.capability.delegated.v1` is now registered.
- Outbox status is a read-only infrastructure command, not an application
  superuser bypass.

## Known risks and incomplete work

- Direct grant, revoke, role-bundle, and role-assignment mutations do not yet
  have application commands; raw model creation remains test/bootstrap only.
- Autocomplete and bulk target freezing need a reusable enforcement harness.
- Audit query uses bounded recent results rather than opaque cursor pagination
  and has no signed export.
- Replay remains a service contract without application authorization/audit.
- A supervised effect process, hard timeouts, fair scheduler, metrics exporter,
  and alerts remain.

## Recommended next actions

1. Implement audited direct authority-management commands.
2. Add reusable endpoint isolation cases for autocomplete and bulk writes.
3. Add supervised worker scheduling and operational telemetry.
4. Finish V02 acceptance evidence, then begin registration.
