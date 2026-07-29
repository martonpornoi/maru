# Guided bootstrap and localized entry checkpoint

Date: 2026-07-29  
Requirements: IDN-001, IDN-002, IDN-007, EVT-001, EVT-005, AUD-001, AUD-002,
REG-001, REG-008, REG-012, REG-021, UX-003, UX-005, UX-006, NFR-001, NFR-003  
Decision: ADR 0020

## Outcome

The first manual clean-database rehearsal no longer needs a command line after
environment/migration setup and the first superuser. Bootstrap administration
now provides a password-confirmed **First convention setup** wizard that
delegates to the same transactional one-shot workforce-bootstrap service as
the management command.

Organization and Convention Series forms explain their separate meanings and
store useful organizer/brand metadata. Organization defaults accept several
ISO 639-1 languages, pin `en (English)`, provide searchable discovery groups,
and use ISO country and IANA time-zone choices. Time-zone labels show current
January/July UTC offsets while the stable IANA identifier remains stored.

Draft registration/template sections, questions, and products are removable.
Active/published/historical records retain their immutable/versioned rules.
Attendee and emergency telephone entry now displays country initials, flag,
calling prefix, and country name and normalizes possible numbers to E.164.

Staff-assisted registration now exact-matches an active identity or explicitly
creates a previously unseen unverified account from a display name and
policy-valid temporary password. The warning is visible, inactive/raced
identities are never replaced, and the privileged account creation has its own
audit event. The ordinary active-configuration, restriction, answer,
eligibility, capacity, price, duplicate, wait-list, deadline, and payment rules
are unchanged.

## Data and migration

`organizations.0002_organizer_series_localization` adds legal/public/contact
metadata, primary country, multiple default languages, and series metadata.
It converts each legacy default locale to its lowercase two-letter base
language; reversal restores the first selected code to the legacy field.

`pycountry` supplies ISO labels and `phonenumbers` supplies calling metadata
and E.164 parsing. Neither display label is persisted as authority. The v5
synthetic fixture additively populates the new organization/series fields and
uses multiple default languages.

## Verification

- 390 backend tests passed against PostgreSQL 17.
- Branch-aware coverage passed at 90.08%.
- Focused correction coverage passed across 51 integration tests.
- Ruff format/lint and strict mypy over 172 source files passed.
- Django system check, migration drift, and OpenAPI 3.1 validation passed.
- Documentation validation passed for 96 Markdown files and 180 unique
  requirement identifiers.
- Generated Staff Console API types, TypeScript typecheck, 13 frontend tests,
  and the Vite production build passed.
- Python dependency audit reported no known vulnerabilities; the local
  non-PyPI `maru` package was the only skipped package.
- The local `maru_walkthrough` database applied organizations 0002 and passed
  Django system checks; `marucon` retained `en` and `Europe/Vienna`.

## Risks and recovery

Dropdowns reduce typing error but validation remains mandatory for APIs and
imports. Broad language-region grouping is a discovery aid rather than
geographic truth. IANA identifiers are authoritative; displayed offsets vary
with clock rules.

The temporary-password staff fallback is suitable for the current controlled
rehearsal, but a production-grade expiring invitation/password-setup delivery
flow remains. If the organization migration is reversed, only the first
default language can fit the former single-value field; added metadata is
removed by the schema rollback.

## Next actions

Apply migrations to the intended walkthrough database, restart Maru, then
retest organization/series creation, browser first-authority setup, draft
deletion, country-aware telephone entry, and missing-account staff-assisted
registration. Do not reseed a non-demo database.
