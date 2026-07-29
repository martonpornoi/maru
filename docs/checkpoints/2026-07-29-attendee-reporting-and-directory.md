# Attendee reporting and public-directory checkpoint

Date: 2026-07-29  
Requirements: REG-009, REG-012, REG-013, REG-016, QRY-001, QRY-004 through
QRY-008, UX-001, UX-003, UX-007 through UX-009  
Decision: ADR 0018

## Outcome

Maru now provides the missing operator and public pages behind the earlier
registration capabilities:

- Staff Console **Reports > Attendees and badges** shows the
  confirmed/checked-in population, country distribution, attendee-level
  distribution, volunteer/photo counts, filterable badge-data preview, and
  pagination.
- The filtered badge-data CSV records edition and generation metadata,
  neutralizes spreadsheet formulas, and excludes legal/contact/full-address,
  payment, arbitrary-answer, and internal-comment data.
- The public attendee HTML and JSON renditions can show a country entered
  specifically for that edition's public list and broad attendee, sponsor,
  super-sponsor, guest, and volunteer labels derived from authoritative
  entitlements/capacities.
- Labels contain readable text; semantic colors are redundant.

## Privacy and authorization

Migration `registration.0026` adds `directory_country_code` and an internal
country-reporting index. The new field is blank by default, is not copied from
address or prior-edition suggestions, is cleared with consent/restriction
withdrawal and retention minimization, and appears publicly only under consent
version 3. Older consent therefore does not silently expand.

`registration.view_attendee_reporting` is edition scoped, field bounded, deny
by default, and audited for page and export reads. Tenant/edition mismatch and
unassigned access return non-disclosing denial. The synchronous source limit is
5,000 rows; larger work awaits expiring asynchronous exports.

## Demo and operator guidance

The v5 synthetic fixture grants the report capability to each current-edition
chair and registration lead. It adds varied safe country examples and upgrades
only untouched synthetic profile defaults to the new public consent example.
The existing local migration and seed were applied successfully. Danube's
public page now demonstrates Guest, Attendee + Volunteer, and Super sponsor.

The registration runbook documents report definitions, filter/export steps,
CSV custody, badge-name fallback, privacy exclusions, and the boundary between
data preparation and physical badge fulfilment.

## Verification

- Backend: 373 tests passed against PostgreSQL.
- Focused registration/reporting/headless/demo tests: 26 passed before the
  complete run.
- Ruff formatting/lint and strict mypy over 155 source files passed.
- Django system check, migration-drift check, and OpenAPI 3.1 validation passed.
- Generated TypeScript contracts, 13 Staff Console tests, typecheck, and Vite
  production build passed.
- Documentation validation passed for 89 Markdown files and 179 unique
  requirement identifiers.
- Browser QA confirmed the populated public directory, accessible label text,
  separate countries, three representative cards, and no horizontal overflow.

## Recovery and remaining work

Rollback of migration 0026 removes only the optional public-country field and
country reporting index; the address country and immutable registration
submission remain unchanged. Before rollback, remove any client dependency on
the new profile contract and public fields.

Badge layout/versioning, printer adapters, stock custody, issue/reprint
evidence, XLSX, saved/general queries, and asynchronous expiring exports remain
future work. The repository is not production-approved until the provider,
infrastructure, load, policy, and governance gates in
`docs/project/REGISTRATION_TODO.md` are complete.
