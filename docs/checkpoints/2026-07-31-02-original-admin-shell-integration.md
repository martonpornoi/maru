# Original administration shell integration checkpoint

Date: 2026-07-31  
Requirements: UX-001 through UX-012, IDN-009, EVT-004  
Decision: ADR 0026

## Outcome

The original Django `/admin/` index and navigation are again Maru's one
administration home. API-backed convention workflows are embedded at
`/admin/workspace/` inside the same header, breadcrumb, Quick start, and
collapsible sidebar.

The sidebar has two clear sections:

- Convention work: Today, People, My registration, Registration, Reports &
  badges, Setup guide, Security history, and Manage access; and
- Specialist records: the existing permission-filtered Django application and
  model directory.

The embedded React application omits its former global sidebar and mobile
navigation. It retains only edition context, account actions, contextual access
management, and the active workflow. Existing model URLs remain unchanged.
`/manage/`, `/staff/`, and `/admin/records/` return 404 rather than redirecting
or hosting alternate menus. Staff-assisted intake has one canonical
`/admin/registration-assist/<edition>/` path.

Active authenticated non-staff accounts may reach the administration home and
embedded workflows, but see no specialist records without Django model
permissions. Direct model pages retain Django's staff boundary, and all
workflow data/actions retain Maru capability, tenant, edition, and field
authorization.

## Usability details

- The original administration home includes Convention work cards above its
  complete, descriptively color-grouped alphabetical directory.
- Quick start remains available throughout administration.
- Convention work and Specialist records are independently collapsible in the
  single sidebar.
- The React bundle's generic element styles are scoped to its root so they do
  not restyle the surrounding Django menu or header.
- Accounts without a display name receive readable `Signed-in account` and
  `Good afternoon, there` fallbacks.
- Below 768 pixels, the administration sidebar becomes an off-canvas panel
  with a persistent bottom-left toggle instead of disappearing.

## Verification

- Ruff format and lint pass for the repository.
- Strict mypy passes for 174 source files.
- 412 PostgreSQL-backed backend tests pass.
- Branch-aware coverage is 90.07%, above the required 90% gate.
- 19 frontend tests, TypeScript typecheck, generated API types, and the Vite
  production build pass.
- Django system check, production-shaped deployment check, migration drift
  check, OpenAPI 3.1 validation, and documentation validation pass.
- Browser QA verifies one `Administration` navigation and zero nested React
  navigation elements on `/admin/` and `/admin/workspace/`.
- Desktop and 390-pixel layouts have no horizontal overflow. The mobile menu
  opens and closes, the event-hero contrast is correct, and browser logs contain
  no errors or warnings.

No database migration is required. The change is recovered by deploying the
previous application/static bundle; no stored data is transformed.
