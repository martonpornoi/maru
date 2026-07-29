# V02 supervised effect operations checkpoint

Date: 2026-07-27  
Requirements: INT-002, INT-003, AUT-002, NFR-004, NFR-005, NFR-008  
Decision: ADR 0005

## Outcome

The V02 outbox is now operable rather than only a synchronous delivery
contract. A long-running supervisor rotates fairly across tenant queues within
one workload pool and runs every delivery in a disposable child process with a
real hard timeout. Expired work recovers through the existing lease protocol.

All current internal event definitions have an explicit acknowledgment handler.
Tenant/pool-bounded status and stable Prometheus series expose status, attempt,
age, and replay health without personal labels. Quarantine replay requires the
new `effects.replay` capability, exact tenant scope, a reason, and correlated
allow/deny/error audit; an operator management command uses that application
path.

## Safety and failure behavior

- The scheduler sees only tenants with ready or expired work in its configured
  pool.
- Child failure or timeout cannot fabricate delivery success.
- A hard-killed child leaves a recoverable lease.
- Unknown event handlers and invalid payloads quarantine.
- Replay cannot decrease the retry budget and cannot cross tenant scope.
- Metrics never include event payload, destination detail, names, or error
  text.
- The process supervisor, not the worker loop, owns process restart.

## Verification

- Unit tests exercise deterministic tenant rotation and child
  success/failure/timeout classification.
- PostgreSQL integration tests exercise run-once delivery, idle behavior,
  readiness selection, option validation, metrics isolation, explicit handler
  coverage, audited replay, reason validation, and cross-tenant hiding.
- Focused effect operations: 10 tests passed.
- Ruff and strict mypy passed after implementation.
- The isolated PostgreSQL restore rehearsal passed with 37 migrations, 81
  accounts, two organizations, six editions, 15 audit events, and 12 outbox
  messages, then removed its drill database and temporary dump.

The complete repository gate is recorded in `CURRENT.md`.

## Operations

[`effects-worker-runbook.md`](../operations/effects-worker-runbook.md) defines
process topology, thresholds, diagnosis, quarantine replay, poison-item
rehearsal, recovery evidence, and the guarded restore command.

## Remaining V02 boundary

The user security history and staff operational timeline projections remain
partial MARU-ACT-001 work. A centralized telemetry scraper, signed/independent
audit checkpoints, queue wake-up adapter, and provider-specific worker
bulkheads remain beyond this checkpoint.
