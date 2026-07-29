# ADR 0015: Canonical service notifications

Status: Accepted  
Date: 2026-07-28

## Context

Registration deadlines, wait-list offers, payment results, and restrictions
must remain understandable even when email is delayed, suppressed, or rejected.
Sending email inside a registration transaction would couple canonical state
to a fallible provider and make retries unsafe.

## Decision

- A versioned domain event creates one localized, canonical inbox message for
  the account and edition.
- Email is an optional delivery projection created from that message.
  Operational service delivery is distinct from optional marketing preference.
- Event, message, and channel deduplication make delivery idempotent.
- Delivery records retain status, attempts, remote identity where available,
  safe result code, retry timing, and terminal failure.
- Transient errors are retried through the transactional outbox. Permanent
  failure appears in an edition-scoped staff queue and closure cannot ignore it.
- Message templates contain edition-local deadlines, price/currency, a safe
  next action, and support route. They do not copy protected registration
  profile fields.

## Consequences

Email failure never rolls back or advances registration. Attendees retain a
canonical in-product notice and operators receive a repair queue. Production
must configure SMTP, schedule the effects workers, monitor age/failure, and
define a manual fallback for a mail-provider outage.

## Alternatives considered

- Email as the record was rejected because delivery and long-term access are
  provider dependent.
- Direct synchronous send in lifecycle commands was rejected because it breaks
  transaction isolation and safe retries.

## Requirements affected

MSG-001, MSG-004 through MSG-007, REG-004, REG-010, NFR-004.
