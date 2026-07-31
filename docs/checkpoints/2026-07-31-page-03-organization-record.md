# Checkpoint: Page 3 organization record

Date: 2026-07-31
Branch: `codex/page-03-organization-record`
Requirements: IDN-002, IDN-011, IDN-012, EVT-005, UX-013, UX-014,
UX-016, UX-017, AUD-001, AUD-002, PRI-001
Decision: ADR 0034

## Outcome

The owner accepted revised Page 2 and requested the preserved administration
interaction in the controlled rebuild: one organization row with **+ Add**
beside it, plus the ability to modify or delete an existing organization.

Pages 1 through 3 now share one responsive Platform administration row. The
primary **Organizations** link and compact adjacent **+ Add** action have
independent focus and current-page semantics. Page 1 organization names link to
`/admin/organizations/<slug>/`.

Page 3 prepopulates the complete Page 2 public, legal/imprint, contact, and
locale profile. An active platform administrator may update those fields;
stable slug and lifecycle are displayed but are never posted fields. The
transaction locks and reloads the organization, repeats authorization,
normalizes and validates the profile, writes only actual changes, and appends
an audit event containing changed field names but not their values. An
unchanged save produces no write or audit event.

A separate danger-zone form posts to
`/admin/organizations/<slug>/delete/`. It requires the current organization name
exactly and an acknowledgement. The service repeats authorization and permits
only Draft lifecycle. All direct organization relationships use `PROTECT`, so
the delete cannot cascade; any series, edition, membership, authority,
participation, registration, workforce, communication, restriction, payment,
or other related record refuses it. Successful empty-Draft deletion and its
UUID-only audit event commit atomically. Organizations with history require the
future closure/data-exit workflow.

No organization membership, Executive Board, authority, convention series,
edition, participation, registration, volunteer, or workforce record is
created. Platform administration remains non-participating. IDN-012 still
requires the later governance workflow to add active Executive Board authority
to property editing and to block activation before that representation exists.

## Preserved behavior used

The pre-reset `OrganizationAdmin` and `_descriptive_app_list.html` were
inspected. Their useful behavior was the model row with adjacent Add/Change
actions and linked records. Page 3 inherits that interaction pattern without
restoring the raw Django model directory or its unreviewed lifecycle fields.
The preserved `NoDeleteAdminMixin` remains intact; deletion exists only through
the purpose-built guarded command.

## Data and migrations

Page 3 introduces no model or migration. `maru_rebuild_empty` remains migrated
through `organizations.0004` and contains exactly the platform administrator
and the owner-created MaruCon Draft. Post-QA verification shows:

- name `MaruCon`, slug `marucon`, lifecycle Draft;
- complete optional profile still blank;
- defaults `en` and `UTC`;
- zero convention series and event editions; and
- one audit event, the original organization creation.

Neither Page 3 form was submitted during live QA. The preserved `maru` and
`marucon_rehearsal` databases were not modified.

## Verification

- 57 focused Page 1–3 integration checks pass.
- 496 complete backend tests pass against PostgreSQL 17.
- Branch-aware coverage is 90.14%, above the 90% gate.
- Ruff formatting/lint and strict mypy pass.
- Django system check, migration drift check, production-shaped deployment
  check, OpenAPI validation, generated TypeScript contract validation, and
  documentation validation pass.
- The preserved staff console passes its component tests, typecheck, generated
  contract check, and production build.
- Live browser QA verified the compact navigation, linked MaruCon row,
  prepopulated record, Save changes action, and separate danger zone at 1280
  pixels and 390 by 844 pixels. Document width remained below viewport width at
  both sizes.

An initial full-suite process was killed by a three-minute command timeout at
73%. Reusing that abruptly interrupted disposable test database made two
Marucon rehearsal clean-database preconditions fail on the next attempt. The
test database was recreated; the clean complete run then passed 496/496. This
did not involve `maru_rebuild_empty` or either preserved database.

## Recovery and rollback

The Page 2 tip remains on `codex/page-02-create-organization`. Removing Page 3
means switching back to that branch; no database rollback is necessary because
Page 3 added no migration. The pre-reset experience remains at commit `548f15a`
on `codex/pre-reset-20260731`, and the dated reset snapshot remains available.

## Next gate

The product owner should inspect Page 3 and accept or revise it. Only after
acceptance should Page 4 define and implement Create convention series on a
dedicated branch.
