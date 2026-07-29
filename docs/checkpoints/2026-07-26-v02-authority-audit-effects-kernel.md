# Checkpoint: V02 authority, audit, and effects kernel

Date: 2026-07-26  
Phase: Platform foundation V02  
Related requirements: IDN-002, IDN-004, IDN-005, AUD-001, AUD-005, INT-001,
INT-002, INT-003, AUT-002, NFR-001, NFR-004  
Related ADRs: 0003, 0005

## Outcome

Maru now has an executable deny-by-default authority and reliable-effects
spine. The edition lifecycle transition is the reference integration:

```text
account + exact organization/edition capability
  -> policy decision and obligations
  -> row lock, valid state edge, aggregate version
  -> append-only transition and security audit
  -> registered domain fact and outbox row
  -> leased, idempotent, retryable handler contract
```

The transition, audit allow record, domain event, and outbox commit together.
A forced outbox failure rolls back the canonical transition. Denials and safe
failures leave audit evidence without domain facts or sensitive payload.

## Delivered

### Authorization

- closed namespaced capability catalog with scope ceiling, field ceiling,
  sensitivity, delegability, and obligations;
- organization/edition grants with effective time, expiry, revocation,
  grantor, reason, and delegation ancestry;
- immutable versioned organizer role bundles and scoped assignments;
- delegation that cannot broaden tenant/edition scope, duration, or a
  non-delegable capability;
- ancestor revocation invalidation;
- deterministic allow/deny decisions with safe reason and policy version; and
- basic edition read and lifecycle transition API enforcement.

### Audit

- append-only event envelope with opaque principal/scope/target/request
  identifiers, outcome, capability, operation, obligations, and retention;
- typed, bounded allowlist metadata with no general payload slot;
- PostgreSQL mutation/delete guard including bulk ORM bypass;
- serialized canonical digest batches linked to the previous digest;
- sequence, count, and digest verification; and
- `audit_integrity` management command with machine-readable output and
  non-zero invalid-chain result.

### Domain events and effects

- closed, versioned domain-event definitions and bounded payload schemas;
- aggregate identity/version, correlation, and causation;
- publish helper that requires the canonical database transaction;
- durable outbox with tenant/workload routing, lease token, expiry, retry
  budget, quarantine, cancellation, and replay count;
- append-only attempt ledger and safe error taxonomy;
- handler registry and event-ID idempotency context;
- recovery of crashed claims, stale-claim rejection, payload revalidation, and
  poison quarantine; and
- PostgreSQL routing, state-machine, attempt-count, immutability, and deletion
  guards.

### Edition integration

- monotonic lifecycle version and database-valid lifecycle edges;
- append-only transition history;
- edition-scoped `events.transition` authorization;
- correlated allow, deny, validation-error, and unexpected-error audit;
- `events.edition.lifecycle_transitioned.v1`; and
- transactional outbox message in workload pool `core`.

## API

```text
GET  /api/v1/organizations/{organization_id}/editions/{edition_id}
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/transition
```

The transition accepts `to_state` and a required reason, propagates the safe
request UUID, and returns only edition identifier, lifecycle, and lifecycle
version.

## Verification

```text
Ruff format/lint: pass
strict mypy: pass (67 source files)
PostgreSQL migrations: applied
migration drift: none
pytest: 153 passed
branch-aware covered source: 93.67%
coverage gate: 90%
```

The suite includes cross-tenant denial, field projection, grant expiry and
revocation, delegation ancestry, database bypass, audit payload rejection,
audit mutation/delete, digest gap/mismatch, commit/rollback, tenant-bounded
claims, crash recovery, stale claims, ambiguous provider success, duplicate
delivery, transient/permanent/timeout/unexpected failure, exhaustion,
quarantine, poisoned payload, reordering, cancellation, replay, and integrated
state/audit/event/outbox rollback.

## Data, migration, and deployment notes

- New tables: capability grants, role bundles, role assignments, audit events,
  audit integrity batches, domain events, outbox messages, effect attempts.
- Event editions gain `lifecycle_version`, default zero.
- New PostgreSQL functions/triggers enforce authorization scope, immutable
  ledgers, outbox routing/state, and edition lifecycle/version.
- Audit and effects are not registered in general Django admin.
- Existing local synthetic database migrations applied successfully.
- No production data migration or provider credential was introduced.

## Known risks and incomplete work

- Policy has no department/resource-state execution or service/device
  principals yet.
- Only the reference read and transition APIs exercise full enforcement; the
  reusable list/search/count/write matrix remains.
- Capability grant/delegation commands are not yet audit-integrated.
- Audit checkpoints are not signed or independently stored, and there is no
  restricted audit query UI.
- The worker runner is not a supervised process and cannot hard-stop a blocked
  handler. Fair tenant scheduling, bulkheads, metrics, alerts, and operator
  authorization/audit remain.
- Bootstrap authentication is not production identity.

## Recommended next actions

1. Complete endpoint-level policy enforcement and isolation harness.
2. Integrate authorization mutations with audit.
3. Add protected, minimized audit query and integrity alert definitions.
4. Add supervised worker entrypoint, fair scheduling, metrics, and replay
   control.
5. Re-run all gates and checkpoint the completed V02 boundary before starting
   registration.
