# Checkpoint: Page 4 create convention series

Date: 2026-07-31
Branch: `codex/page-04-create-convention-series`
Requirements: IDN-011, EVT-001, EVT-003, UX-013, UX-014, UX-017,
UX-018, AUD-001, AUD-002, PRI-001
Decision: ADR 0035

## Outcome

After accepting Page 3, the product owner requested Page 4 and authorized use
of the durable pre-reset branch as reference. The preserved generic
ConventionSeries administration established the useful field vocabulary and
the distinction between a continuing public brand and a tenant. Page 4 keeps
that vocabulary in the controlled journey without restoring generic model
administration.

Page 3 now has a Convention series section before its complete profile. It
lists only rows owned by the selected organization and provides **+ Add
series** unless the parent is Closed. The shared sidebar remains the single
**Organizations** row with its compact organization **+ Add** action.

Page 4 is nested at
`/admin/organizations/<organization_slug>/series/new/`. It displays the parent
but accepts no parent or slug control. Name is the sole required value;
description, HTTPS-default website, public contact email, and initial
availability are optional. Active is the default and means available to a
future edition, not published and not an edition itself.

## Safety and domain behavior

The view authorizes an active platform administrator before parent lookup. The
application service repeats that authorization, locks the organization,
refuses Closed lifecycle, normalizes and bounds the input, validates the
complete model, and generates a stable slug unique case-insensitively within
the organization. Same-tenant collisions receive numeric suffixes; another
organization may reuse the same slug.

Series creation and value-minimized audit evidence share one transaction. The
event identifies the parent, target, and changed field names but copies no
name, description, website, or contact value. Database or audit failure leaves
no series. Creation produces no event edition, membership, Executive Board,
authority, role, participation, registration, department, volunteer,
onboarding, or workforce assignment. The platform administrator remains
non-participating.

The browser pass exposed one presentation interaction: Page 3 inherited Page
2's name autofocus and therefore jumped past the new series section. Existing
organization forms now remove that attribute, while Page 2 and Page 4 keep
autofocus on their only required creation names.

## Database and migration state

Page 4 introduces no model change or migration. `maru_rebuild_empty` remains
migrated through organizations `0004`. Post-QA read-only verification shows:

- one active platform administrator account;
- MaruCon, slug `marucon`, lifecycle Draft, defaults `en` and `UTC`;
- zero convention series, event editions, memberships, participations,
  registrations, departments, and workforce assignments; and
- one audit event, the original organization creation.

The live Page 4 form was not submitted. The preserved `maru` and
`marucon_rehearsal` databases were not modified.

## Verification

- 79 focused Page 1–4 integration checks pass.
- 518 complete backend tests pass against PostgreSQL 17.
- Branch-aware coverage is 90.23%, above the 90% gate.
- Ruff formatting/lint pass for 258 files and strict mypy passes for 182 source
  files.
- Django local and production-shaped checks, migration drift, OpenAPI 3.1
  validation, and generated TypeScript compatibility pass.
- The preserved staff console passes generated-contract validation, typecheck,
  20 component tests, and the Vite production build with no generated diff.
- Documentation validation passes for the complete requirement, contract,
  decision, operations, module, reset, roadmap, current-state, and checkpoint
  update.
- Browser QA verified Page 3 empty-series placement and Page 4 parent context,
  one required name, optional fields, Active default, boundary explanation,
  submit/cancel actions, and one-row global navigation at desktop and 390 by
  844. Document width never exceeded viewport width, and the console had no
  warnings or errors.

## Recovery and next gate

Page 4 can be removed by switching back to
`codex/page-03-organization-record`; no database rollback is necessary. The
complete pre-reset experience remains at commit `548f15a` on
`codex/pre-reset-20260731`, and the dated temporary recovery snapshot remains
available.

The product owner should inspect and accept Page 4. Only after that response
should Page 5 define the existing Convention-series record, including
editing/deactivation, stable identity, history protection, authorization,
audit, and failure behavior.
