# ADR 0128: Workforce operating-home continuation

- Status: Accepted
- Date: 2026-10-29
- Clarifies and extends: ADR 0126
- Requirements: UX-002, UX-029, UX-031, UX-032, HR-012–014, AUD-003, NFR-013
- Parent: issue #35; maintainer-authorized Workforce operating-home milestone

## Context

The home can guide Departments, Positions and opportunity publication. Existing
Assignment, person-owned Availability and Shift workflows still require an
organizer to discover their next action separately. The maintainer authorized
completing this operating-home milestone and its technical delivery without
routine input. Existing lifecycle, authority and independent decisions remain
the source of truth.

## Decision

Extend the exact `workforce_only@1` contribution with three independently admitted
areas: Assignments, shared Availability consequences and Shifts. Core consumes
closed immutable Workforce-owned continuation items; it reads no domain models
and invents no writable task, provider-plugin or activity-tracking system.

The owner returns at most one item per area and four items including setup.
Operating conflicts and ended work take precedence over pending decisions,
missing setup and informational retained history. Tie-breaking is deterministic.
Show one best continuation and at most three other items. Their scope and state
remain explicit; a quiet checked area cannot establish overall event readiness.

Assignment admission retains complete structure-read authority and
`workforce.manage_assignments`, as the existing management route requires.
Issuance/revocation authority and independent proposer identity affect explanation,
not read admission. Availability and Shift admission retain their respective
complete existing field ceilings. Every component checks current exact-Edition
policy before source reads and again before audit/disclosure. Missing authority
omits that component. A failure yields minimized unavailable guidance for that
component while other admitted work and the authorized tool registry survive.

Read only bounded current-state metadata needed for the decision. Do not load
holder names, identity contact fields, organizer rationale, onboarding documents,
or exact personal Availability periods. Private drafts and absent plans have the
same not-shared explanation. Shared-empty means deliberately unavailable, not
missing input. Existing Shift suitability rules supply current-evidence warnings;
no new qualification, coverage, attendance or readiness rule is introduced.

Short read-only repeatable snapshots bind source metadata and lifecycle. Compare
bounded complete signatures in fresh reads; retry the complete component once
on movement, then report unavailable. Reauthorize and persist existing minimized
read-audit operations before releasing any component. Recheck after audit and
after all areas finish, so a later area cannot leave an earlier revoked area
visible. Bind the next relevant Assignment expiry or Shift start/end; crossing
that boundary before release requires a fresh read instead of an old action.
A setup-only recheck failure remains local to setup. Results are request-local
and private/no-store, show their checked time and edition-local decision times,
and require refresh to observe changes. Destination routes authorize again.

Events exposes only a coherent edition work-phase/version/time-zone reference;
Organizations retains its existing editable-lifecycle projection. These owner
seams grant no access and cannot be public discovery endpoints. No migration,
runtime ACL, account kind, profile meaning, grant or domain write is added.

## Acceptance and limits

Cover source bounds, missing/corrupt evidence, source movement, principal or grant
revocation, independent decisions, lifecycle/time boundaries, partial failure,
tenant/edition/field isolation, and actual home-to-owner authorization. Exercise
the rendered primary and attention states, keyboard paths, narrow layouts and
honest read-only/empty behavior using isolated fictional data. Extend maintained
ongoing/future practice incrementally without altering any existing preview.

Use focused feedback during implementation, then complete fresh exact-head local
and hosted acceptance, CodeQL, review disposition and protected delivery. Human
and specialist accessibility acceptance remain separately recorded. Broader
cross-module home contributions, recent-outcome feeds, #24 attendance/handover,
production deployment and the #42 recipient-password ceremony stay separate.

Source rollback removes the added projection and presentation without changing
domain records. Existing direct workflows remain available if guidance fails.
