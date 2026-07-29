# ADR 0002: Multi-convention event editions and durable history

- Status: Accepted
- Date: 2026-07-26
- Requirements: IDN-001 through IDN-005, EVT-001 through EVT-005, ARC-001
  through ARC-005

## Context

One Maru deployment must serve multiple independent organizers. Each recurring
convention produces editions that need independent configuration and operations.
Users also need a meaningful record of attendance, volunteering, hosting, and
other contributions extending far into the past.

A single global user table with unrestricted organizer access would create
unacceptable privacy and authorization coupling. Reconstructing history from
current roles would make old records inaccurate when names or structures change.

## Decision

Model:

```text
Organization -> ConventionSeries -> EventEdition
PlatformAccount -> OrganizationMembership
PlatformAccount + EventEdition -> Participation
```

Every tenant-owned operational record belongs to an organization. Every
edition-specific record also belongs to an event edition.

Participation stores historical capacity and status through explicit records
and snapshots. Archived editions are read-only by default. Corrections are
separate audited actions.

Configuration may be copied from prior editions. Mutable operational records are
never shared between editions.

## Consequences

- A person gets one coherent personal history without granting cross-tenant
  staff visibility.
- Reports and authorization must always carry organization and edition scope.
- Historical labels require snapshot or versioned-reference strategies.
- Retention operates by data category; archiving does not justify indefinite
  retention of all personal information.
- Tests must attempt cross-organization and cross-edition access for every
  module.

## Alternatives considered

- One deployment per convention: rejected because it recreates separate
  accounts and prevents a coherent user experience.
- Convention series as the operational root: rejected because yearly editions
  need independent lifecycle, configuration, permissions, and archives.
- Reconstruct history from audit logs: rejected because audit logs are not a
  stable product-facing history model.
