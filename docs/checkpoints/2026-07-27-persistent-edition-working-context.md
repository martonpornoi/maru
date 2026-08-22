# Persistent edition working context

Date: 2026-07-27  
Requirements: IDN-002, IDN-004, EVT-002, EVT-003, UX-003, UX-006, UX-008,
UX-009, REG-001  
Decision: ADR 0008

## Outcome

Staff and bootstrap administration now preserve one explicit event-edition
working context. Selecting MaruCon 2027 focuses routine operational lists,
details, counts, ordinary relationship choices, and new-record defaults on
MaruCon 2027. Bootstrap administrators can deliberately clear the context with
`All foundation data`.

An authenticated Django staff account without any convention participation is
redirected from `/staff/` to `/admin/`, allowing first-time organization,
series, edition, and participation setup instead of showing an empty Staff
workspace. Active non-administrators retain the safe empty-workspace behavior.

## Registration reuse exception

Registration remains edition-owned under ADR 0007. With a selected edition:

- routine configuration and operational records show only that edition;
- reusable templates remain selectable only when they belong to the same
  organization and apply organization-wide or to the selected series;
- the source-edition control can select another edition in the same
  organization, including when the target has no configuration yet;
- the selected edition itself and other organizations are excluded; and
- copying always creates an independent target-edition draft requiring review.

This exception is exposed through named copy controls rather than mixed into
routine lists.

## Safety and architecture

- The session stores only the selected edition identity.
- Admin model querysets are scoped before object lookup, so a direct detail URL
  for another edition is unavailable while context is selected.
- Ordinary organization, series, edition, and nested relationship choices are
  constrained to the context.
- Organization-wide authority applicable to the selected edition remains
  visible.
- Platform-wide records remain explicit rather than being falsely attributed
  to an edition.
- Selected context is a usability and query-minimization aid, never an
  authorization decision. APIs and commands continue to enforce trusted
  tenant and edition scope.

## Verification

- 282 PostgreSQL-backed backend tests pass with 90.68% branch-aware coverage.
- Focused tests cover sign-in fallback, Staff-to-admin context transfer,
  selection persistence and clearing, safe return paths, stale context,
  changelist/detail isolation, form defaults, relationship choices, applicable
  authority, eligible templates, and source-edition tenant/series rules.
- Ruff formatting and lint pass 148 Python files; strict mypy passes 105 source
  files.
- All 11 Staff Console tests, TypeScript checking, and the production build
  pass.
- Django system and migration-drift checks pass; no migration is required.
- Documentation validation passes 68 Markdown files and 164 unique requirement
  identifiers.
- A populated real-browser walkthrough selected MaruCon 2027 and verified its
  scoped registration rows, eligible template visibility, reduced filters,
  `/staff/` admin fallback, desktop/mobile layout, and zero runtime errors.

## Known limits and next action

Bootstrap Django staff/superuser access remains broad. The working context
reduces accidental cross-edition work but cannot replace Maru's capability
system. New module admin pages must explicitly declare their edition
relationship or their platform-wide behavior.

The next interaction boundary is the Staff Console visual registration form
builder: named sections, ordering, preview, source comparison, and an explicit
review checklist.
