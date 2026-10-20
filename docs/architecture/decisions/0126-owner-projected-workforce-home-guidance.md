# ADR 0126: Owner-projected Workforce home guidance

- Status: Accepted
- Date: 2026-10-20
- Clarifies: ADRs 0049, 0055, 0080 and 0116
- Requirements: UX-002, UX-029, UX-030, UX-031, UX-032, AUD-003, NFR-013
- Parent: issue #35

## Context

The authorized home registry now avoids invented setup status, but people still
have to choose a tool without a current continuation. The maintainer authorized
one bounded state-aware Workforce home slice, using existing owner state.

## Decision

Keep one canonical home and one read-only owner projection. Only
Workforce-only version 1 contributes in this increment. The shell filters that
exact profile before invoking Workforce; Workforce independently checks the
persisted profile, exact organization/edition authority and full structure field
ceiling.

The first provider covers active Departments, Positions and their paired
volunteer-opportunity publication states. It reads no names, holders, personal
availability, applications, reasons or hidden counts. A small immutable result
contains an owner-derived step, optional exact Position identifier, current
management permission and last authorization time. There is no mutable Task
model, generic provider plugin system, new permission or domain transition.

The owner uses its existing short repeatable-read/version-fenced structure
snapshot and bounded department/Position probes. Overflow, legacy missing
control, incomplete opportunity state, persistent movement or a failed dependency
produces unavailable guidance rather than partial facts or a false all-clear.
Existing organization and edition lifecycle rules control whether setup is
offered. Current policy is repeated and existing minimized structure-read audit
must succeed before disclosure.

The shell maps the closed result to plain text and exact existing owner routes.
A viewer without management permission gets a waiting explanation and a read-only
review link. Every destination independently authorizes again. A publication
state says only that current non-closed Positions have published opportunity
copy; application windows, staffing readiness, assignments and Shifts are not
inferred. No current publication or record existence establishes whole-event
readiness.

Missing workspace and other profiles retain their existing home behavior.
Unavailable guidance leaves the authorized tool registry usable. Guidance is
private and request-local, includes a checked-at time and must be refreshed to
observe later changes. It does not confer action authority or promise that
state cannot change after rendering.

## Consequences and evidence

Native tests cover the state sequence, exact scope/field/action authorization,
revocation, closed lifecycle, bounds, snapshot movement, audit failure and
unadopted-provider exclusion. Browser evidence covers the rendered state,
continuation links, keyboard semantics and shell reflow; synthetic component
evidence stays separate from native authority and human acceptance.

This is the first contribution under #35, not closure of its cross-module,
recent-outcomes or complete Workforce operating-home scope. The separate #42
recipient-password boundary remains human. There is no schema, runtime ACL,
credential, notification, provider integration or production-activation change.
