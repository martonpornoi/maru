# ADR 0017: Credentials, offline check-in, and closure

Status: Accepted  
Date: 2026-07-28

## Context

Arrival must continue during an intermittent network without turning an offline
device into a full database replica. An archived edition must not hide unpaid
reservations, unresolved money, undelivered notices, restriction consequences,
privacy work, unsafe media, or conflicting scans.

## Decision

- Credentials derive from a confirmed registration entitlement. Issuance,
  reissue, revocation, and verification expose the minimum checkpoint result
  and append credential events.
- An authorized relay device receives a signed, edition-scoped manifest with a
  bounded validity window and only necessary credential state.
- Offline operations carry device and operation identity. Ingest is
  idempotent; stale, invalid, duplicate, revoked, or conflicting operations are
  rejected or queued for staff reconciliation.
- Edition closure has named readiness gates for finance, registration,
  communications, credentials, privacy, and recovery. Each approval requires a
  reviewer, summary, and evidence reference.
- A closure manifest can be generated only in `closing`, after every required
  gate is approved and all enumerated queues are zero. It records a canonical
  count digest and recovery reference.
- Archive transition rechecks the current counts against the immutable
  manifest. New unresolved work invalidates closure readiness.

## Consequences

Arrival can degrade safely without granting broad data access, and archival is
an evidence-backed transition rather than a status toggle. Production must
provision and revoke devices, rotate the manifest secret, test printers and
scanners, monitor conflicts, and keep independent outage procedures.

## Alternatives considered

- A full offline database replica was rejected due to data exposure and
  conflict complexity.
- Archiving from a manually checked spreadsheet was rejected because queues can
  change after the check.

## Requirements affected

REG-009, REG-020, ACC-001, ACC-004, ACC-005, ARC-001 through ARC-005,
NFR-005, NFR-008.
