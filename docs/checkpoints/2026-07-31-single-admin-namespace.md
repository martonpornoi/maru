# Single administration namespace

- Date: 2026-07-31
- Phase: Unified `/admin/` workspace implemented; partner deployment readiness
  remains next
- Related requirements: IDN-009, EVT-004, UX-001 through UX-009, UX-011,
  UX-012, NFR-001 through NFR-003
- Related ADRs: ADR 0023, ADR 0024, ADR 0025

## Outcome

Maru now has one visible authenticated administration hierarchy:

- `/admin/` is the canonical guided setup and recurring-operations workspace;
- `/admin/records/` is the complete alphabetical Django record directory;
- existing specialist model URLs such as `/admin/identity/account/add/`
  remain unchanged;
- `/admin/registration-assist/<edition>/` is the canonical staff-assisted
  registration path; and
- `/manage/` and `/staff/` preserve their query string and redirect to
  `/admin/` instead of hosting separate interfaces.

The guarded first-leadership ceremony, edition lifecycle, access sharing,
registration work, reports, Forms, and personal administration therefore all
begin inside `/admin/`. Advanced records link back to that home and no longer
compete with it as a second console.

## Decisions

ADR 0025 partially supersedes ADR 0023's route placement while preserving its
single-product interaction model and ADR 0024's guarded bootstrap behavior.
The React console and Django records remain separate technical adapters over
the same services; only their visible namespace was consolidated.

The canonical `/admin/` workspace is available to every active authenticated
account and uses Maru capabilities. Advanced Django records remain protected
by Django staff/model permissions. Platform staff status still does not grant
convention authority, and selected-edition state remains working context
rather than authorization.

## Changed areas

- Reordered URL handling so the API-backed workspace owns exact `/admin/`,
  while Django continues to own model subpaths.
- Added the explicit, staff-protected `/admin/records/` directory.
- Converted `/manage/` and `/staff/` into query-preserving compatibility
  redirects.
- Moved staff-assisted intake and all console links into the `/admin/`
  hierarchy.
- Updated the platform home, public registration links, security-notification
  paths, login redirect, Vite proxy, Advanced-record header, and Quick start.
- Updated requirements, ADRs, setup, onboarding, module, information
  architecture, roadmap, current-state, and progress documentation.

## Verification

- `pytest --cov=maru --cov-report=term-missing`: 410 passed; 90.06%
  branch-aware coverage.
- Ruff format/lint and strict mypy: pass for 174 source files.
- Django system, production-shaped deployment, and migration-drift checks:
  pass.
- OpenAPI 3.1 generation/validation and generated TypeScript types: pass.
- Management Console: 18 tests, TypeScript typecheck, and Vite production
  build pass.
- Documentation validation: 107 Markdown files and 184 unique requirement
  identifiers.
- Browser QA confirmed:
  - `/admin/` opens the signed-in edition workspace;
  - Advanced records opens `/admin/records/`;
  - familiar model URLs remain under `/admin/<app>/<model>/`;
  - `/manage/?view=setup` becomes `/admin/?view=setup`;
  - staff-assisted intake links use `/admin/registration-assist/...`; and
  - desktop and 390-pixel layouts have no horizontal overflow or runtime
    console errors.

## Data, migration, and deployment notes

No model or database schema changed, so no migration is required. Browser QA
was read-only and did not submit the leadership ceremony or mutate convention
data. Legacy route redirects are temporary compatibility behavior and should
remain non-permanent until deployed bookmarks and external links have been
observed.

## Known risks and incomplete work

Several low-frequency builders still use Django model screens, now reachable
from the unified setup guide and Advanced records directory. They should move
to purpose-built workflows only when a real convention test identifies the
next useful workflow; duplicating command-owned behavior remains prohibited.

Production identity, provider, infrastructure, load, policy, partner approval,
and badge-layout/printing gates remain unchanged.

## Recommended next actions

1. Continue the clean-convention walkthrough entirely from `/admin/`.
2. Confirm the next confusing specialist record screen during the rehearsal
   and replace it with one capability-checked workflow.
3. Select the first partner and complete the production gates listed in
   `docs/project/CURRENT.md`.
