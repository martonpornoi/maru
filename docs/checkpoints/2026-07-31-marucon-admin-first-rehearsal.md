# Marucon admin-first educational rehearsal

Date: 2026-07-31
Status: Complete

## Outcome

Maru now supports an administrator-led, local/test-only convention rehearsal
through the original Django administration shell. Convention work is embedded
under `/admin/workspace/`, uses the compact record-oriented visual language of
Specialist records, and no longer carries a second global navigation or the
large Quick Start strip. Setup guidance and the guarded first-authority
ceremony remain in Setup guide.

The implemented scenario creates:

- the deterministic `admin` account as the first registered account and
  platform superuser;
- Marucon Organizers, the Marucon series, and Marucon 2031;
- a distinct public-handle Chair;
- nested Executive Board, Helper Board, department, and subdepartment
  structures;
- positions with several holders and people with several department roles;
- a reviewed registration template inherited into an active edition
  configuration;
- public, staff-only, and shared question/extension boundaries; and
- restricted Infinity admission derived from authoritative eligibility rather
  than an attendee-editable checkbox.

## Public roster and data boundary

The retired local importer read a public volunteer directory only after
explicit operator acknowledgement. It accepted public handles, department
names/descriptions, and role labels. It excluded recruiting headings, images,
and contact data, and
uses `.invalid` email addresses. Checked-in tests use a synthetic miniature
instead of live personal data.

The isolated `marucon_rehearsal` database is retained for education and
permission review. Its final state is:

- 207 accounts: the first-account administrator plus 206 roster accounts;
- 1 organization, 1 convention series, and 1 edition;
- 23 departments, 92 positions, and 245 assignments; and
- 2 registration configurations: the selected template and inherited active
  edition version.

All 207 accounts accept the documented local-only shared rehearsal password.
The pre-existing ordinary `maru` database was not reset or used to claim a
first-account scenario.

## Durable decisions

- ADR 0027 aligns embedded Convention work with Specialist records and removes
  duplicate global setup chrome.
- ADR 0028 adds case-insensitively unique login handles, bounded local roster
  import, and a minimized scoped hierarchy projection.
- ADR 0029 adds reviewed edition-owned profile extension definitions and
  append-only value revisions while preserving immutable submissions and
  authoritative benefits.
- Imported position labels do not grant system authority. The rehearsal uses
  ordinary bootstrap, appointment, approval, and scoped-capability services.
- Selected edition remains working context, never authorization.

## Verification

- Fresh migrations through identity `0009` and registration `0030` apply
  against PostgreSQL 17; migration drift reports no changes.
- 431 backend tests pass with 90.10% branch-aware coverage.
- Ruff format/lint pass and strict mypy passes for 178 source files.
- Django system and production-shaped deployment checks pass.
- OpenAPI 3.1 validation, generated TypeScript API types, 20 frontend tests,
  TypeScript compilation, and the Vite production build pass.
- Documentation validation passes for 115 Markdown files and 186 unique
  requirement identifiers.
- Browser QA covers the shared admin shell, real nested hierarchy, handle
  login, attendee/staff question minimization, restricted Infinity admission,
  responsive layout evidence, and absence of horizontal overflow.
- A direct database check confirms that `admin` is the first account and a
  superuser, and that every rehearsal account accepts the shared password.

## Known limits and next action

The separate hierarchy projection is intentionally minimized and read-only;
low-frequency structure setup remains available through permission-filtered
Specialist records and domain services. Workforce shifts, qualifications,
assignment replacement/ending, programme, timetable, badge layout/printing,
and production infrastructure/governance gates remain future work. The suite
also retains Django's 6.0 transition warning for the URL-field default scheme;
the HTTPS-default compatibility choice should be tested before that upgrade.

Use the retained role accounts for education and permission/usability review.
Convert findings into stable requirements before building a richer hierarchy
editor or adding the next domain module. See
`docs/operations/marucon-admin-rehearsal.md` for credentials, startup,
inspection, and safe cleanup instructions.
