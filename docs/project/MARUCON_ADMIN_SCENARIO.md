# Marucon admin-first rehearsal

Status: Complete
Last updated: 2026-07-31

This is the crash-safe implementation ledger for the admin-first Marucon
rehearsal requested on 2026-07-31. It is intentionally more detailed than
`CURRENT.md` while work is active. The final durable outcome belongs in
`CURRENT.md` and an append-only checkpoint.

## Requested outcome

- The original first registered account is the Maru platform administrator
  and can drive the complete rehearsal.
- The administrator creates the first organization, Marucon convention
  series, and dated edition.
- Local-only rehearsal accounts can use the public volunteer handles from the
  requested Awoostria roster source and one shared, documented test password.
- A separate hierarchy page shows:
  - Executive Board at the root;
  - Helper Board below Executive Board;
  - Board responsibility for all other departments;
  - nested subdepartments;
  - several leads, deputies, and volunteers where present; and
  - the same person in several department positions.
- People complete a registration copied from a selected template. Later
  profile fields can be added without rewriting the immutable original
  submission, and field write policy distinguishes attendee-editable,
  staff-editable, and shared fields.
- Infinity-ticket status remains an authoritative staff-controlled entitlement
  rather than an attendee-asserted answer.
- Convention work uses the same visual language as specialist record pages.
- The large Quick Start strip is removed; setup guidance remains in the
  purpose-built Setup guide.
- An educational integration/smoke test proves the journey and its permission
  boundaries.

## Repository starting point

- The worktree already contained an uncommitted, passing redesign that restored
  the original Django `/admin/` shell and embedded the React workflows at
  `/admin/workspace/`.
- Focused pre-change verification:
  `31 passed` for admin usability, staff-console authentication, and guarded
  convention bootstrap tests.
- ADR 0022 deliberately added the large Quick Start strip. ADR 0026 restored
  the original administration shell but retained custom Convention work inner
  styling. The requested behavior therefore needs a superseding ADR.
- Existing account authentication is email-only.
- Existing `Department.parent`, `Position.reports_to`, position headcount, and
  `PositionAssignment` already model nested departments, reporting lines,
  multiple holders, and multiple positions per person.
- Existing registration submissions are immutable snapshots. The current
  editable attendee profile already contains address/contact fields, but
  convention-defined answers cannot be added after submission.
- `QuestionVisibility.REGISTRATION_STAFF` exists, but the bundled public form
  currently renders every question and submission validation does not enforce
  writer visibility. This must be fixed before staff-only fields are usable.
- Infinity status already derives from the admission product entitlement
  `infinity-ticket`, matching ADR 0009 and REG-013.

## External roster boundary

Source inspected:
`https://awoostria.at/about-us/our-volunteers`.

The rendered source currently contains 23 populated groups, 240 role entries,
and 206 unique public handles. Some people appear in several groups, and names
include spaces, underscores, apostrophes, slashes, and Unicode.

Repository tests, examples, and fixtures must not check in live personal data.
The implementation therefore separates:

- a local-only, explicit public-roster import adapter used by the operator; and
- a checked-in synthetic miniature roster used by automated tests.

Only display handles, department names/descriptions, and public role labels
are in scope for the local import. Avatar files, contact details, and other
personal data are not copied. Generated login emails use the reserved
`.invalid` domain.

## Implementation checklist

### Discovery and decisions

- [x] Read `CURRENT.md`, `ROADMAP.md`, requirements, relevant module docs,
  domain model, clean onboarding walkthrough, ADR index, and ADRs 0007, 0009,
  and 0019 through 0026.
- [x] Inspect current admin shell, embedded frontend, identity, registration,
  workforce, authorization, demo fixture, and focused tests.
- [x] Inspect the requested public roster as rendered rather than guessing
  names or roles.
- [x] Add a superseding ADR for record-oriented Convention work, removal of
  global Quick Start, readable login handles, public hierarchy projection, and
  append-only registration-profile extensions.
- [x] Update stable requirement identifiers before or with implementation.

### Administration experience

- [x] Remove `_quick_start.html` from the global header and remove Quick Start
  from the administration home.
- [x] Keep setup order and guarded first-authority ceremony inside Setup guide.
- [x] Make embedded workflow headings, modules, forms, buttons, tables,
  spacing, and responsive behavior match specialist record pages.
- [x] Use the Django administration edition selector for administrators on
  workflow pages and keep a safe selector for non-admin participants.
- [x] Add Organization structure to Convention work navigation.

### Identity and local roster import

- [x] Add an optional, case-insensitively unique human login handle without
  weakening normalized unique email.
- [x] Authenticate local accounts by exact email or handle with one
  non-enumerating password response.
- [x] Expose the handle in account administration and local sign-in guidance.
- [x] Add a local/test-only Marucon rehearsal command with deterministic
  organization/series/edition/admin structure.
- [x] Require explicit opt-in for live public-roster import and never copy
  avatars or contact data.
- [x] Generate collision-safe `.invalid` emails while preserving exact display
  handles.
- [x] Keep reruns idempotent without deleting or duplicating fixture-owned
  records. Existing fixture passwords are retained.

### Workforce hierarchy

- [x] Add a minimized, edition-scoped hierarchy query/API guarded by
  `workforce.view_structure`.
- [x] Add the separate responsive hierarchy page.
- [x] Render nested departments, reporting positions, multiple holders, and
  each person's other positions without exposing email or technical IDs.
- [x] Seed Executive Board, Helper Board, Board-owned departments, selected
  nested subdepartments, and all imported public role entries.
- [x] Prove cross-tenant denial and absence of unauthorized person disclosure.

### Extensible registration profile

- [x] Enforce registration-question writer visibility in the bundled form,
  headless submission, and service layer.
- [x] Add edition-owned, append-only profile-extension field definitions and
  value revisions with explicit attendee/staff/shared write policy, purpose,
  classification, visibility, and retirement.
- [x] Retain optional selected-template and prior-edition provenance on
  extension definitions; copied active fields still require explicit review.
- [x] Let a registered person fill attendee-writable missing information.
- [x] Let authorized registration staff fill staff/shared fields with reason
  and audit evidence.
- [x] Prevent attendees from reading or writing staff-only values.
- [x] Keep Infinity-ticket status in product/entitlement records and show it as
  a derived staff-controlled fact.
- [x] Test schema/version history, tenant isolation, field authorization, and
  immutable original submission.

### Educational scenario and documentation

- [x] Add an end-to-end integration/smoke test using a synthetic miniature
  roster, the first-created admin, bootstrap ceremony/service, hierarchy,
  template inheritance, self completion, staff-only completion, and role
  visibility assertions.
- [x] Add a concise operator walkthrough with credentials and cleanup safety.
- [x] Reconcile outdated/redundant Quick Start, separate-console, and
  registration-editing statements across product/module/operations docs.
- [x] Generate and validate OpenAPI/types if API contracts change.
- [x] Build frontend assets.
- [x] Visually inspect desktop and narrow layouts.
- [x] Run focused tests, migration drift, Django checks, frontend tests/build,
  and the full appropriate quality suite.
- [x] Update `CURRENT.md` and add an append-only milestone checkpoint.

## Decisions that must not be lost

- The platform administrator and Convention Chair remain different accounts.
  The first admin is the bootstrap controller; the public `LilNoodles` handle
  may be the first Chair in the local rehearsal.
- A display role is not authority. Imported roster positions must use the
  workforce appointment path and exact immutable role bundle versions.
- The original registration submission never changes. Later requested
  information is a current profile extension with its own definition and
  append-only value history.
- An “Infinity holder” checkbox is not safe attendee-entered form data. The
  staff-controlled admission product/entitlement remains authoritative and may
  be displayed beside extension fields.
- Selected edition is working context, not authorization.
- Live public handles are opt-in local rehearsal input, never a checked-in
  automated-test fixture.

## Resume point

The implementation, documentation, browser rehearsal, and final quality gate
are complete. The isolated `marucon_rehearsal` database is deliberately
retained for education and permission review. It contains the first-account
administrator plus 206 explicitly acknowledged public-handle accounts, 23
departments, 92 positions, and 245 assignments. All 207 accounts use the
documented shared local password. The ordinary `maru` database, which already
had 82 accounts before this work, was not reset or modified for the rehearsal.

For the next task, begin with `CURRENT.md`, this ledger, and the append-only
checkpoint. Use the retained role accounts to collect permission/usability
findings before expanding the hierarchy editor or adding the next module.
