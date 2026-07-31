# ADR 0025: Single administration namespace

- Status: Superseded by ADR 0026
- Date: 2026-07-31
- Partially supersedes: ADR 0023 route placement
- Extends: ADR 0024 guarded first-authority ceremony
- Requirements: IDN-009, EVT-004, UX-001 through UX-009, UX-011, UX-012,
  NFR-001 through NFR-003

## Context

ADR 0023 removed the conceptual staff-versus-admin split but retained two
prominent URLs: `/manage/` for guided and recurring workflows and `/admin/`
for specialist Django records. Clean-convention testing showed that this still
looks like two products. An operator creating an organization or account in
`/admin/` reasonably expects the next setup action to remain inside that
namespace rather than moving to a newly discovered `/manage/` page.

The safe API-backed workflows and the specialist Django records remain
different implementation surfaces. The problem is their visible route
hierarchy, not the service or authorization boundaries.

## Decision

Use `/admin/` as Maru's single canonical authenticated planning, setup, and
operations entry point.

- The React Management Console is served at `/admin/` for any active
  authenticated account.
- The complete permission-filtered Django record directory is available at
  `/admin/records/`.
- Existing model routes remain stable, including paths such as
  `/admin/identity/account/add/`; the directory move does not relocate model
  records.
- Guided setup links, first-authority bootstrap, edition lifecycle, access
  sharing, registration operations, reports, and personal administration all
  remain in the canonical `/admin/` workspace.
- `/manage/` and `/staff/` are compatibility redirects that preserve their
  query string and never host a separate interface.
- `/admin/registration-assist/<edition>/` is the canonical staff-assisted
  intake path; former assisted-intake paths remain compatibility aliases.
- The Advanced records header links back to `/admin/`, and its explicit
  directory link points to `/admin/records/`.

The route consolidation does not merge authorization systems. `/admin/` uses
Maru capability decisions and remains available to active non-Django-staff
accounts. Django record pages retain Django staff/model permission checks.
Platform staff status still does not grant convention authority, and the
selected edition remains working context rather than authorization.

## Consequences

Operators can begin with organization, series, edition, and account records,
complete the guarded leadership ceremony, configure registration, and operate
the convention without leaving the `/admin/` hierarchy. Bookmarks and older
documentation using `/manage/` or `/staff/` continue to reach the correct
workspace through redirects.

The Django namespace still resolves its historical `admin:index` URL to
`/admin/`, which is now the canonical workspace. Code and tests that need the
alphabetical record directory must use the explicit `advanced-records` route.
Model URLs and Django admin reverse names remain unchanged.

The internal frontend source and static bundle retain their historical
`staff-console` names; renaming build paths would add deployment churn without
improving the user-facing experience.

## Alternatives considered

- Put the first-authority form directly on Django's model index while keeping
  other workflows at `/manage/`: rejected because it would preserve two
  products and duplicate the safe workflow shell.
- Move all Django model URLs below `/admin/records/`: rejected because it would
  break existing bookmarks, documentation, and reverse-generated links without
  a product benefit.
- Permit every active account into ordinary Django admin: rejected because
  Django model permissions are not a replacement for Maru's tenant- and
  edition-scoped capability system.
- Remove Django records immediately: rejected because several low-frequency
  configuration screens do not yet have purpose-built builders.
