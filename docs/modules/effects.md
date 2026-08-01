# Effects module

Status: Implemented V02 worker boundary and value-minimized aggregate facts
Last updated: 2026-08-01

## Purpose and requirements

`maru.effects` implements ADR 0005 for INT-002, INT-003, AUT-002, and NFR-004.
It prevents a committed canonical action from silently losing required
asynchronous follow-up.

## Owned data and invariants

- closed, versioned domain-event definitions and payload validators;
- append-only domain event envelopes with aggregate version and correlation;
- one durable outbox delivery per event and destination;
- explicit pending, processing, succeeded, quarantined, and cancelled states;
- bounded tenant/workload claims with expiring lease tokens;
- append-only attempt outcomes and safe error codes; and
- durable retry budgets and replay counts.

PostgreSQL prevents domain-event and attempt mutation, cross-tenant outbox
routing, routing-envelope changes, invalid state transitions, attempt-count
skips, unsafe replay transitions, and ordinary deletion.

## Publishing contract

`publish_domain_event(...)` refuses to run outside the canonical database
transaction. A rollback therefore produces neither fact nor delivery; a
commit produces both.

Handlers receive the domain-event UUID as their idempotency key. Delivery is
at least once: a provider timeout or worker crash can cause a repeat, so every
handler or adapter must make that key an idempotency boundary or reconcile the
ambiguous result.

`aggregate_domain_facts(...)` is the public read boundary for a bounded record
history. The caller must provide exact organization, aggregate type/identifier,
an event-name allowlist, and a limit. It returns event name, occurrence time,
optional actor ID, and validated minimized payload for an already-authorized
projection. It does not bypass the caller's page/domain authorization and is
not a replacement for security audit.

## Worker contract

- `claim_next_effect(organization_id, workload_pool, lease_duration)`
- `run_claimed_effect(claim, handlers, execution_timeout)`
- success, transient, permanent, timeout, unexpected-error, and lease-lost
  outcomes;
- `cancel_pending_effect(...)` before handler execution; and
- `replay_quarantined_effect(...)` with an additional attempt budget.
- `python src/manage.py effects_status --organization UUID [--pool NAME]`
- `python src/manage.py effects_worker --pool NAME`
- `python src/manage.py effects_metrics --organization UUID --pool NAME`
- `python src/manage.py effects_replay --organization UUID --message UUID
  --actor EMAIL --reason TEXT`

Expired claims are recoverable and record the lost attempt. Claims always name
one organization and workload pool, preventing a caller from accidentally
draining another tenant. Payloads are revalidated before dispatch; unknown
handlers and poisoned payloads quarantine safely.

The supervised worker rotates deterministically across eligible tenant queues
inside one workload pool. Each claimed delivery runs in a disposable child
process. A hard timeout kills only that child; its processing lease then expires
and is safely recovered by a later claim. Execution timeout must be shorter than
the hard timeout, which must remain shorter than the lease.

The status and Prometheus commands report only one explicit tenant and workload
pool: status and attempt counts, oldest ready/expired-lease age, and replay
count. Monitoring can request a non-zero result when quarantined work exists;
no payload or personal field becomes a metric label.

The built-in internal destination explicitly acknowledges every currently
registered event definition. This is a durable no-op delivery boundary for
facts that have no projector yet; provider connectors and future projectors use
separate destinations and idempotency stores.

Replay is no longer a raw storage operation. The application command and
management command require `effects.replay`, a non-empty reason, exact tenant
scope, a quarantined target, and append an allow/deny/error audit.

## Integrated behavior

Convention-series creation/update and event-edition creation/profile update
publish their closed versioned facts in the same transaction as canonical
state and audit. Every successful edition lifecycle transition likewise
publishes `events.edition.lifecycle_transitioned.v1`. A forced publish failure
rolls the complete canonical change back.

Authority management publishes closed, minimized facts for direct grants,
grant revocation, role-bundle version creation, role assignment, and role
revocation. These use the security workload pool and contain stable capability,
role-version, and scope labels rather than personal data or command reasons.

## Tests

Tests cover commit/rollback, registry closure, handler coverage, payload bounds, database
immutability, tenant routing, crashed leases, stale claims, duplicate delivery,
ambiguous external success, transient/permanent/timeout/unexpected failures,
attempt exhaustion, poison quarantine, reordering convergence, cancellation,
fair tenant rotation, child success/failure/hard-timeout classification,
tenant-safe metrics, and authorized/audited operator replay.
The edition-spine tests additionally cover registered series/edition facts,
aggregate version order, value-minimized payloads, and record-activity query
scope.

## Limitations

There is no queue wake-up adapter, handler-specific concurrency bulkhead,
operator UI, or centralized metrics scraper yet. The first worker polls
PostgreSQL, processes one effect per disposable child, and is intended to be
restarted by the process supervisor. Provider connectors, webhook fan-out, and
domain projections arrive in later vertical slices.

See the [effect worker runbook](../operations/effects-worker-runbook.md).
