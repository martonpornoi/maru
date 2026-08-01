# ADR 0043: Global emergency Executive Board controller containment

- Status: Accepted
- Date: 2026-08-01
- Supersedes: ADR 0040 only for emergency ending and suspension
- Requirements: IDN-011, IDN-012, ACC-005, AUD-001, AUD-005

## Context

An account is platform-global while Executive Board appointments and authority
are organization-scoped. Deactivating a controller after changing only one
organization can strand an invitation elsewhere or leave another Board's root
authority dependent on an inactive person. Removing one of two controllers
also cannot leave a single person controlling the organization.

## Decision

Maru provides one platform-administrator-only, reasoned emergency containment
command. It may start from any current Invited, Accepted, or Active Executive
Board appointment and requires that representation's current aggregate
version. In one transaction it inventories and locks every open representation
relationship for the person, closes all invitations and terms, ends matching
Board memberships, revokes linked root assignments, revokes sessions, and only
then deactivates the global account.

Each affected active Board remains Active only when at least two controllers
remain. Otherwise its organization and representation become Suspended and all
of that Board's active terms and root assignments end. Historical activation
and cross-approval evidence remains immutable and valid when its approver's
activated term is now Ended; current authority and membership remain
Active-only.

Every affected representation advances once and emits minimized, correlated
audit, domain-event, and outbox evidence. Database guards serialize
relationship creation against account eligibility changes, validate the final
state at commit, and reject downgrade after emergency evidence exists.

## Consequences

- A global identity change cannot silently leave an open Board relationship.
- Quorum loss favors containment over administrative availability.
- Routine expiry, replacement, voluntary ending, reactivation, and quorum
  recovery remain separate future workflows.
- Old writers must be drained before migration. After emergency evidence
  exists, recovery is fix-forward or a whole-database restore to a consistent
  pre-emergency point.

## Alternatives considered

- Deactivate only within the selected organization: rejected because account
  activity and sessions are global.
- Leave a one-controller Board active: rejected because it defeats independent
  representation and cross-approval.
- Delete appointments or rewrite approval provenance: rejected because the
  governance history must remain durable and auditable.
