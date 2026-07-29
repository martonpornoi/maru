# Bootstrap administration usability

- Date: 2026-07-27
- Phase: Platform foundation V02
- Related requirements: IDN-003, UX-001, UX-003, UX-006, UX-008, NFR-001,
  NFR-002, NFR-003
- Related ADRs: 0001, 0002, 0003

## Outcome

Every registered Maru Django admin page now provides a deliberate bootstrap
data-management or inspection experience. Lists lead with people, convention
names, tenant scope, status, and compact domain summaries instead of raw UUIDs.
Search, filters, stable ordering, related-record counts, and grouped forms make
the two-convention demonstration dataset practical to explore.

The original participation label such as
`Danube Furry Convention 2025:<account UUID>` is now a person and edition
label. Its list also summarizes capacity labels such as attendee, volunteer,
staff, host, or board membership.

## Decisions

- Django admin remains a bootstrap surface; it does not satisfy the future
  role-oriented Staff Console required by UX-001.
- Technical UUIDs and timestamps remain available in collapsed detail
  sections but do not lead ordinary lists.
- Search and filters preserve exact codes, emails, scopes, and visibility
  controls even when list columns use concise human-readable summaries.
- Authorization grants, role bundles, role assignments, lifecycle
  transitions, and archive amendments are command-owned and view-only.
- Archived editions, participations, and capacities are view-only. Ordinary
  deletion is disabled for protected historical/tenant records.
- Django `Group` is removed from navigation because Maru uses scoped
  capabilities and immutable role-bundle versions.

No new ADR was required. The work applies ADR 0001's bootstrap-admin allowance,
ADR 0002's tenant/edition hierarchy, and ADR 0003's authority model without
changing them.

## Changed areas

- Added shared Maru admin branding and read-only/no-delete mixins.
- Added custom account, organization, series, membership, edition,
  participation, capacity, authorization, and history admin classes.
- Added readable model string representations for relationships and history.
- Corrected the Django plural from `participation capacitys` to
  `participation capacities` with a metadata-only migration.
- Added integration coverage for all 12 changelists, search and labels,
  command-owned immutability, archived-state protection, and compact summaries.
- Updated all affected module and current-state documentation.

## Verification

- All 12 registered Maru changelists returned successfully against PostgreSQL.
- Focused admin usability tests pass.
- The populated local dataset was inspected in the in-app browser across
  account, organization, edition, participation, capacity, and authorization
  pages at a normal desktop width.
- Ruff formatting and lint, strict mypy, Django checks, migration apply/drift,
  the full PostgreSQL test suite with branch-aware coverage, production
  deployment checks, OpenAPI validation, and documentation validation pass.
- The final suite has 175 passing tests and 92.00% branch-aware coverage
  against the 90% gate.

## Data, migration, and deployment notes

Migration `participation.0003_alter_participationcapacity_options` changes only
model metadata and ordering; it does not rewrite participation records.
Existing UUID primary keys and API contracts are unchanged.

## Known risks and incomplete work

- Django admin still relies on broad Django staff/superuser access and is not a
  production organizer authorization surface.
- Recurring operational work still needs the purpose-built Staff Console.
- Direct participation and tenant data entry remains bootstrap-only until
  audited domain commands and scoped staff workflows exist.

## Recommended next actions

1. Keep the new admin pages as a development and recovery aid.
2. Reuse their person/edition/scope vocabulary in the first Staff Console
   slices.
3. Add the reusable endpoint-isolation and autocomplete/bulk authorization
   harness before exposing organizer operations.
