# Effects module

Status: Implemented V02 worker boundary, exact-profile delivery guards, and
value-minimized aggregate facts
Last updated: 2026-08-31

## Purpose and requirements

`maru.effects` implements ADR 0005 for INT-002, INT-003, AUT-002, EVT-006,
NFR-004, and NFR-013. It prevents a committed canonical action from silently
losing required asynchronous follow-up or delivering an edition-scoped effect
outside that edition's immutable adoption manifest.

## Owned data and invariants

- closed, versioned domain-event definitions and payload validators;
- append-only domain event envelopes with aggregate version and correlation;
- one durable outbox delivery per event and destination;
- exact-profile permission for every edition-scoped event/destination route;
- explicit pending, processing, succeeded, quarantined, and cancelled states;
- bounded tenant/workload claims with expiring lease tokens;
- append-only attempt outcomes and safe error codes;
- append-only, tenant-bound replay receipts retaining actor, normalized reason,
  exact retry-budget change, replay sequence, and correlation; and
- durable retry budgets and replay counts.

PostgreSQL prevents domain-event and attempt mutation, cross-tenant outbox
routing, routing-envelope changes, invalid state transitions, attempt-count
skips, unsafe or unreceipted replay transitions, replay-receipt mutation, and
ordinary deletion.

## Publishing contract

`publish_domain_event(...)` refuses to run outside the canonical database
transaction. A rollback therefore produces neither fact nor delivery; a
commit produces both.

An edition-scoped publish or secondary enqueue resolves the edition through
its exact organization and identifier, reads both persisted adoption-profile
fields through the Events public query, and requires the event/destination
route to be pinned by that exact manifest. Unsupported, foreign, or unpinned
publishes create neither a domain event nor an outbox row; a denied secondary
enqueue creates no additional outbox row for its existing event. Facts with a
null edition identifier remain explicitly platform- or organization-scoped,
must match the closed non-edition route catalog, and do not infer an edition
profile. Omitting an edition is therefore not a fallback for edition-owned
work. Hybrid authorization facts additionally bind their validated
`scope_level`: only `organization` may omit the edition, while edition,
department, and resource scopes require one.

The `effects.E001` Django compatibility check resolves every route in both the
exact adoption manifests and the closed non-edition catalog against the
versioned event registry and built-in handler registry. A missing event or
destination is therefore a deployment error rather than durable poison work.

The registry includes the dormant `programme.item.changed.v1` schema with an
exact minimized code-only payload. It has no current-profile route and no
built-in handler. A real current-profile Programme command therefore fails at
the delivery-adoption check before event or outbox persistence. Future
activation must add the exact route and matching handler together; registering
the event name alone is not execution permission.

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
- `python src/manage.py effects_replay_history --organization UUID --message UUID
  --actor EMAIL [--limit 20]`

Expired claims are recoverable and record the lost attempt. Claims always name
one organization and workload pool, preventing a caller from accidentally
draining another tenant. Payloads are revalidated before dispatch; unknown
handlers and poisoned payloads quarantine safely.

After claiming an edition-scoped delivery, the worker resolves and checks the
exact profile again before handler lookup or invocation. Work that cannot
resolve a permitted route is quarantined without calling the handler and
records only the stable `effect_profile_not_allowed` reason. Replay cannot
override this guard; restore a compatible reviewed manifest deployment before
replaying affected work.

The supervised worker rotates deterministically across eligible tenant queues
inside one workload pool. Each claimed delivery runs in a disposable child
process. A hard timeout kills only that child; its processing lease then expires
and is safely recovered by a later claim. Execution timeout must be shorter than
the hard timeout, which must remain shorter than the lease.

The status and Prometheus commands report only one explicit tenant and workload
pool: status and attempt counts, oldest ready/expired-lease age, and replay
count. The status command also returns a bounded, value-safe grouping of
quarantine error codes for operator diagnosis; these codes do not become
Prometheus labels. Monitoring can request a non-zero result when quarantined
work exists, and no payload or personal field is exposed.

The built-in internal destination explicitly acknowledges every currently
registered event definition. This is a durable no-op delivery boundary for
facts that have no projector yet; provider connectors and future projectors use
separate destinations and idempotency stores.

Replay is no longer a raw storage operation. The application command and
management command require `effects.replay`, a non-empty reason, exact tenant
scope, a quarantined target, and append an allow/deny/error audit. A successful
transition first appends an immutable replay receipt and then changes the outbox
row in the same transaction; PostgreSQL refuses the retry-budget increase when
the exact next receipt is absent and refuses a receipt whose actor is not an
active platform account. Before that transition, replay re-resolves the
persisted event's tenant, scope, exact edition profile, event name, destination,
and payload; a route that is still forbidden leaves the quarantine state,
budget, sequence, and receipt history unchanged. The runtime database role has
SELECT/INSERT only on this evidence relation. Initial publish/enqueue budgets
and replayed cumulative budgets share the same database-enforced ceiling.
Reasons are NFC-normalized, whitespace-
collapsed, and limited to 240 characters. One replay may add at most 20
attempts, and the cumulative message limit may not exceed 100. The bounded
history command requires the scoped `effects.replay` capability and appends a
minimized read audit before returning newest-first rationale for one explicit
tenant and message without event payloads or cross-tenant existence disclosure.
Receipts carry the `operations-extended` retention class. Reasons are sensitive
operator evidence: do not enter credentials, secrets, or unnecessary personal
data.

Migration `effects.0003_effect_replay_receipts` refuses downgrade after the
first receipt exists because rollback would destroy retained operator rationale
and let older code increase retry budgets without evidence. Stop replay writers
before an empty-state rollback; otherwise fix forward or restore a mutually
consistent database and release. Activation also refuses to add the 100-attempt
constraint while any pre-existing outbox row exceeds it; reconcile those rows
through the reviewed operational process before retrying the migration.

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

Tests cover commit/rollback, registry closure, handler coverage, payload bounds,
database immutability, tenant routing, crashed leases, stale claims, duplicate
delivery, ambiguous external success, transient/permanent/timeout/unexpected
failures, attempt exhaustion, poison quarantine, reordering convergence,
cancellation, fair tenant rotation, child success/failure/hard-timeout
classification, tenant-safe status/metrics, authorized/audited operator replay,
bounded rationale and retry budgets, append-only replay evidence, database-
coupled retry increases, and tenant-bounded history inspection.
Focused profile tests also cover pre-persistence denial, secondary enqueue
denial, exact tenant binding, defensive worker quarantine without handler
invocation, hybrid authorization-scope consistency, deployment-check route
resolution, and preserved explicit organization-scoped delivery.
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
