# ADR 0005: Transactional outbox and idempotent asynchronous work

- Status: Accepted
- Date: 2026-07-26
- Requirements: ANN-004, ANN-005, QRY-006, AUT-001 through AUT-004, INT-002,
  INT-003, NFR-004, NFR-005, NFR-008

## Context

Maru commits actions that require later work: notifications, schedule
projections, exports, provider calls, webhooks, files, search indexing, and
automations. Calling providers inside a database transaction couples user
latency and correctness to external availability. Publishing to an ordinary
queue after commit can lose the follow-up between the two writes.

## Decision

Write a versioned outbox entry in the same PostgreSQL transaction as the domain
transition. Workers claim entries and deliver at least once.

Every handler and provider adapter is idempotent or records an idempotency
boundary. Attempts, retry schedule, result, remote identifiers, quarantine, and
operator action are durable and observable.

Domain events are facts, not instructions to assume a state transition
succeeded. High-impact consumer actions perform their own authorization and
invariant checks.

The queue implementation remains an operational choice; it can accelerate
wake-up and distribution but is not the only copy of required work.

## Consequences

- A committed action does not silently lose required asynchronous follow-up.
- Consumers must tolerate duplicates, delay, and reordering across aggregates.
- Outbox storage needs partitioning, retention, lag monitoring, and replay
  tooling.
- User interfaces distinguish canonical success from downstream delivery.
- Background work can be isolated into workload pools and degraded safely.
- Exactly-once external delivery is not promised where a provider cannot
  support it; reconciliation makes uncertainty visible.

## Alternatives considered

- Direct provider call in the request: rejected for latency, failure coupling,
  and unresolvable commit ambiguity.
- Best-effort queue publish after commit: rejected because it can lose work.
- Distributed transaction with providers: unavailable and operationally
  disproportionate.
- Full event sourcing: not selected as a platform-wide persistence model;
  append-oriented ledgers are used only where domain integrity benefits.
