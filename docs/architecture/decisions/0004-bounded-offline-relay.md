# ADR 0004: Bounded offline relay for venue-critical workflows

- Status: Accepted
- Date: 2026-07-26
- Requirements: REG-009, ACC-004, ACC-005, LOG-002, OPS-001 through OPS-006,
  NFR-005, NFR-008

## Context

Venue connectivity is too unreliable for check-in, credential verification,
staff coordination, current schedule, essential custody, and signage to depend
entirely on the central service. A complete second deployment at every venue
would multiply security, migration, synchronization, and operational risk.
Browser storage alone does not provide a shared desk view or robust device
coordination.

## Decision

Provide an optional Maru Relay: an edition-scoped, encrypted, registered edge
service with signed, expiring capability and data snapshots for explicitly
supported workflows.

Offline writes are append-only sequenced commands carrying actor, device,
snapshot version, policy version, and idempotency. The central service
reconciles each as applied, duplicate, superseded, rejected, or requiring human
review. No record silently uses last-write-wins.

Relay does not contain general administration, unrestricted search, planning
tools, or full restricted cases. Independent paper/radio procedures remain
mandatory for life safety.

## Consequences

- Essential functions can continue on a venue-local network.
- Every supported offline command needs an explicit conflict policy and test.
- Device management, encryption, expiry, clock, packaging, observability, and
  pre-event drills become product work.
- The limited dataset reduces but does not eliminate lost-device risk.
- A central recovery can take longer without immediately stopping event
  operations.
- Unsupported workflows fail clearly rather than appearing partially offline.

## Alternatives considered

- Central service only: rejected for venue-critical workflows.
- Full database or Django replica at the venue: rejected because bidirectional
  general synchronization and security scope are too broad.
- Independent app databases: rejected because they recreate app hell and make
  reconciliation an informal manual process.
- Browser-local storage only: useful for individual drafts but insufficient as
  the shared operational edge.
