# Management experience first slice

- Date: 2026-08-15
- Status: Repository-verified first slice; complete rendered owner acceptance
  remains open
- Decision: ADR 0055
- Requirements: UX-001 through UX-013, UX-019, UX-024, UX-026 through UX-029,
  NFR-001 through NFR-004

## Outcome

Maru now has a task-oriented first management-experience slice without a new
product shell, route namespace, authority system, or data migration.

- The default navigation prioritizes durable work, retains one code-owned
  permission-filtered registry, classifies creation commands as contextual or
  search-only actions, and progressively discloses authorized specialist
  records.
- Search indexes code-owned labels, descriptions, and stable task vocabulary.
  The platform account inventory is named **User accounts**, and ordinary
  searches such as `users`, `staff`, `volunteers`, and `board` can find the
  relevant authorized destination.
- The administration home starts with current work and **Continue setup** and
  exposes one specialist-record gateway instead of repeating every registered
  model.
- At 1,100 CSS pixels and below, the shared sidebar becomes a closed overlay
  drawer with labelled controls, backdrop, Escape dismissal, focus trapping
  and return, background scroll lock, reduced-motion handling, and RTL support.
  The convention-context selector shrinks with its container and wide record
  regions no longer widen the document.
- User accounts and invitation pages lead with results and primary actions,
  explain their identity-only outcome, and offer status-aware next steps. Page
  8 keeps the three governance stages visible and exposes account-preparation
  links only to platform administrators.

## Preserved boundaries

- Account invitation still creates only a verified platform person account.
- Page 8 remains the sole normal Executive Board establishment ceremony:
  provision, invite exact verified people, invitee-owned response, and
  activation with at least two distinct accepted controllers.
- Link visibility, grouping, drawer state, search, and pins confer no authority.
  Every destination and mutation remains authorized by the existing server
  policy and command boundary.
- No schema, migration, retention, recovery, audit, or deployment behavior
  changed.

## Verification

- Focused source-contract/unit suite: 7 passed.
- Focused rendered integration behaviors across administration home,
  navigation/My Maru, unified routing, User accounts/invitations, and Page 8:
  56 passed.
- Ruff formatting and lint passed for the changed source/tests.
- Strict mypy passed for the navigation registry.
- Django system check passed with only the expected local fail-closed
  `identity.W001` warning when invitation encryption is unavailable.
- Whitespace/diff validation passed before documentation finalization.

## Remaining experience gates

This checkpoint does not claim broad browser or accessibility acceptance. The
first slice still needs authenticated evidence at 320, 390, 768, 958, 1,024,
1,280, and 1,920 CSS pixels, at 200 percent zoom, with keyboard-only,
automated-accessibility, representative screen-reader, empty/populated/denied/
validation/stale/dependency/success states, task-effort measures, and owner
rehearsal. Registration, Workforce, Venues, Logistics mutation roles, and
specialist records have not yet all adopted the new page primitives.

No deployment occurred and no development or production data was migrated.
