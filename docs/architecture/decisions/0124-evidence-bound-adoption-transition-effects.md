# ADR 0124: Evidence-bound adoption transition effects

- Status: Accepted; implementation in progress
- Date: 2026-10-09
- Partially supersedes: ADR 0080 only for manifest-exclusive routing of the
  explicitly declared foundation transition facts below; all manifest meanings
  and ordinary module effect boundaries remain immutable
- Extends: ADRs 0005 and 0119
- Requirements: EVT-006, EVT-008, INT-002, NFR-013

## Context

Adding Guides to an existing Announcements edition requires a proposal and each
actual controller decision before the selected profile changes. Those foundation
facts must retain an internal outbox event in their owning transaction. The old
`announcements_only@1` manifest deliberately has no Guides adoption event route.
Requiring its future target profile before recording a proposal makes the
approved transition impossible. Widening the old manifest would change existing
meaning; omitting the edition would misstate ownership.

The first native expansion test reached this contradiction after nine setup and
access cases passed. A pending proposal grants no Guides access. Its internal
foundation evidence needs an explicit boundary separate from content effects.

## Decision

Keep every existing profile literal, version and digest unchanged. Add one closed
foundation transition route for `events.guidance_adoption.changed.v1` to the
`internal` destination, for the exact recorded edge
`announcements_only@1 -> announcements_guidance@1`. It is not a generic permission
for new Events, Knowledge or Authorization effects. Notifications, other edges,
unsupported profile versions and null/foreign edition scope remain denied.

Ordinary exact-profile routing keeps its existing behavior. When that route is
absent, Events' public owner query must verify the actual scoped immutable
request, decision or receipt and the complete minimized event envelope: canonical
row type and ID, aggregate/schema version one, closed operation, original actor,
audit causation, correlation and recorded source/target pairs and digests. Missing,
malformed or inconsistent evidence fails closed. A caller-supplied target profile,
identifier or claimed transition cannot substitute for retained owner evidence.
Native request/decision/receipt guards continue to require the same event and
internal outbox atomically; no raw write, role or profile-change bypass is added.

The same admission applies to initial publication, secondary enqueue, worker
execution and quarantined replay. Every call supplies the complete original
envelope. Deployment checks validate this explicit route against the registered
schema and handler, just as they validate existing route catalogs.

Routing a retained fact does not repeat mutation admission. Current expiry,
controller/root validity or parent lifecycle cannot erase a completed decision or
turn delayed delivery into a new authorization ceremony. Exact tenant/edition and
supported source/target profile identity remain required. Current command
permissions, locks, acceptance, versions and lifecycle checks still govern every
new proposal, response and apply. A delivered fact grants no present authority.

## Consequences and verification

The existing in-place expansion can retain its pre-adoption evidence without
changing Announcements content, existing roots, immutable manifests or event
identity. The additional owner lookup is bounded by the exact evidence ID and
returns only the minimized original event-identity reference, without reasons,
private text or current authority projections.

Tests must preserve manifest fingerprints and deny wrong scope, edge, operation,
actor, causation, correlation, row identity, version and destination. Exercise
retained declined/expired decisions, delayed delivery, enqueue and replay, plus
transaction rollback when evidence or routing is absent. Genuine native expansion
and worker acceptance remain required after source verification; this decision
alone activates no workflow.

## Alternatives considered

- Widening the old manifest changes its exact-version meaning and is rejected.
- Publishing without an edition loses the actual scope and is rejected.
- Delaying all events until apply loses declined and pending evidence and breaks
  the existing atomic request/decision contract.
- A generic foundation event exemption could admit unrelated facts and is
  rejected in favor of one evidence-bound edge and destination.
