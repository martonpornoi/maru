# Checkpoint: Page 2 create organization

Date: 2026-07-31
Branch: `codex/page-02-create-organization`
Outcome: Implemented and verified; product-owner inspection pending

## Delivered behavior

The controlled browser rebuild now exposes
`/admin/organizations/new/` from the Page 1 organization inventory. Only an
authenticated, active platform administrator may load or submit Page 2. The
form asks for the recognizable organization name and nothing else.

The application command normalizes whitespace, derives a lowercase ASCII
slug, applies a bounded numeric suffix on collision, and uses `organization`
when transliteration is empty. It creates one Draft organization with English
and UTC defaults and blank optional legal, contact, country, website, and
descriptive properties. The successful audit event and organization row share
one transaction.

Success returns to `/admin/`, where the Draft row and a one-time confirmation
are visible. Validation remains field-local. Database or audit failure returns
a generic `503` response and leaves neither partial tenant state nor false
success evidence.

## Boundaries preserved

Page 2 creates no organization membership, Executive Board, capability grant,
role assignment, convention series, event edition, department, participation,
registration, volunteer, onboarding, or workforce record. The platform
administrator is an audit actor only and remains outside every convention.

IDN-012 and ADR 0032 record the deferred governance invariant: the later
workflow must provision or backfill an Executive Board before activation, and
only active Executive Board authority or platform administration may modify
organization properties. Page 3, not Page 2, will own those properties.

## Data and migration

`organizations.0003_organization_draft_lifecycle` changes the model default for
new organizations from Active to Draft without rewriting existing rows. Demo
and Marucon rehearsal builders now request Active explicitly so their existing
meaning does not change.

The migration was applied successfully to `maru_rebuild_empty`. The preserved
`maru` and `marucon_rehearsal` databases were not migrated or reset.

## Verification evidence

- 40 focused Page 2, empty-baseline, and tenant-model tests pass.
- 466 complete PostgreSQL tests pass with 90.02% branch-aware coverage.
- Ruff format and lint pass for 256 files.
- Strict mypy passes for 182 source files.
- Django system check, production-shaped deployment check, and migration drift
  check pass.
- OpenAPI 3.1 generation and validation pass; generated TypeScript remains in
  sync.
- Preserved frontend typecheck, 20 component tests, and production build pass.
- Documentation validation passes for 128 Markdown files and 188 unique
  requirement identifiers.
- Browser QA covers Page 1 navigation, Page 2 initial and validation states,
  and a 390-by-844 layout. The page has no horizontal overflow and emitted no
  runtime warnings or errors. Automated tests cover successful submission to
  avoid adding a sample organization to the owner’s empty rebuild database.

The suite retains one known Django 6 transition warning about the future URL
field default scheme; it is unrelated to Page 2 and remains a documented
upgrade item.

## Recovery and next action

The smallest next action is product-owner inspection of Page 2 with the local
administrator. Do not design or implement Page 3 until the owner accepts this
page. After acceptance, write the Organization record contract before exposing
property editing, activation, or governance behavior.
