# ADR 0116: Make convention work understandable before exposing technical detail

- Status: Accepted
- Date: 2026-10-08
- Supersedes: ADR 0049 only where one flat visible list prevents purpose-based
  grouping of authorized destinations
- Refines: ADRs 0055, 0070, and 0074
- Requirements: UX-003, UX-006, UX-007, UX-008, UX-019, UX-027, UX-029,
  UX-031, NFR-012, and NFR-013

## Context

The maintainer has authorized a change of direction while Programme umbrella
#48's remaining acceptance and activation are deferred. New and occasional
volunteers need to understand their next action without learning software or
professional event-management terminology. The full-permission menu, visible
policy mechanics, and engineering vocabulary make exploration unnecessarily
hard. Furry conventions remain the primary product audience.

## Decision

Keep one server-authorized navigation registry, context selector, canonical route
per task, search, and reauthorized pins. Present ordinary destinations in a small
set of purpose groups: Overview, People & teams, Registration & shop,
Applications, Places & equipment, and Settings. Account controls and Advanced
records remain secondary. Grouping follows work rather than nested organization,
series, and edition folders. Empty or unauthorized groups disclose nothing.
The current task's group opens automatically. Native disclosures work without
JavaScript; search reveals matching tasks without broadening authorization.

Use concrete language at the point of action. Applications retains `call` and
`proposal` in its implementation and API, while the human journey uses Collect
activity ideas, Ask for activity ideas, Suggest an activity, and Activity idea.
Workforce's overview is Team workspace. Specialist records becomes Advanced
records. Legacy words remain useful search terms. These display aliases do not
rename domain concepts, persisted identifiers, permissions, or public APIs.

Optional policy/evidence/version details are progressively disclosed under an
explicit heading. Required decisions, errors, consequential changes, and approval
responsibilities remain visible and understandable. No default may be invented
for a required policy reference. Expanded error details must be keyboard
reachable. Configurability remains available to authorized people.

Preserve native semantics: links navigate and may have button styling; buttons
submit or change interface state. Related page views may use tabs only when their
focus and selection behavior is implemented. Do not replace every link with a
button or make navigation depend on JavaScript.

The public introduction leads with the furry-convention purpose, concrete current
capabilities, honest development status, and a verified newcomer route. Keep ADR
0074's six documentation hubs and five-step newcomer path. Consolidate repeated
setup instructions and stale current-state narration into their existing owning
pages. Preserve historical ADRs, checkpoints, and evidence; Git retains prior
versions of maintained handoffs. Remote repository settings are a separate change.

## Verification and consequences

Exercise the full-permission and limited-role menus, current group, search,
pins, narrow widths, keyboard behavior, and no-JavaScript fallback. Check rendered
activity forms including required fields and errors, and preserve source-level
permission/isolation tests. Technical verification and synthetic browser work are
not evidence of independent-person or production acceptance.

This is a presentation and documentation contract. Existing policy, persistence,
publication, approval, and profile-activation boundaries remain authoritative.
New operational capabilities follow complete, independently adoptable journeys.
#48's open gates remain recorded for a later explicit return.
