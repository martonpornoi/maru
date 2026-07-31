# Controlled reset and page-by-page rebuild

Status: Page 1 accepted; Page 2 Create organization implemented with
verification and owner inspection pending
Last updated: 2026-07-31

This ledger preserves the current Maru implementation while the product
experience is reconsidered from a deliberately small baseline. It is the
resume point if the desktop app or development process stops.

## Why this reset exists

The current implementation contains substantial tested domain behavior, but
the administration experience has been reorganized several times and no
longer gives the product owner confidence that each page has one clear place
and purpose. Further navigation patches would compound that uncertainty.

The reset therefore separates two concerns:

1. preserve the current source, documents, requirements, tasks, tests, and Git
   history as recoverable evidence; and
2. decide what "empty" means before changing or deleting the working tree.

## Recovery snapshot

Target:
`C:\Users\TheMw\AppData\Local\Temp\Maru-reset-snapshot-20260731-171759`

The snapshot must contain:

- a copy of the repository-owned working tree, including modified and
  untracked source, documents, tasks, tests, migrations, and built assets;
- a Git bundle containing all committed refs and history;
- a binary-safe patch of tracked working-tree changes;
- a machine-readable Git status and snapshot inventory; and
- checksums for the recovery artifacts and copied repository files.

Regenerable environments and caches (`.venv`, dependency caches,
`node_modules`, bytecode, coverage, and tool caches) are excluded from the
working-tree copy. The existing PostgreSQL databases are retained in place and
are not dropped, flushed, or treated as part of an empty baseline.

## Reset checklist

### Preservation

- [x] Copy repository-owned working files to the dated temporary directory.
- [x] Create and verify the Git history bundle.
- [x] Export tracked dirty changes as a binary-safe patch.
- [x] Record untracked files, exclusions, source HEAD, branch, and repository
  status.
- [x] Hash the copied files and recovery artifacts.
- [x] Confirm the original working tree and databases were not modified by the
  snapshot operation.

Verified snapshot inventory:

- source branch: `main`;
- source HEAD: `ca37acb7f612a450a98585c3b4d5c8d4a2807de8`;
- copied repository-owned files: 651;
- copied size: about 9.1 MB;
- complete Git bundle: verified by `git bundle verify`; and
- `maru` and `marucon_rehearsal`: retained unchanged in PostgreSQL.

### Baseline decision

- [x] Choose **empty experience** or **empty codebase**:
  - Empty experience: retain the tested Django/domain/security foundation but
    expose only sign-in and one minimal administration home. Reintroduce pages
    one at a time. This is the recommended baseline.
  - Empty codebase: create a new minimal Django project and re-earn every
    domain behavior, migration, permission, and operational guarantee from the
    preserved evidence.
- [x] Define the only routes and records visible in the baseline.
- [x] Decide whether the rebuild happens in this working tree, a new branch,
  or a sibling worktree.
- [x] Define a new empty PostgreSQL database name; do not reuse or erase
  `maru` or `marucon_rehearsal`.
- [x] Add a superseding ADR before changing the accepted UI architecture.

Selected baseline:

- experience: empty experience over the preserved backend;
- branch: `codex/page-by-page-rebuild`;
- database: `maru_rebuild_empty`;
- unauthenticated page: `/accounts/login/`;
- authenticated page: `/admin/` for active staff accounts;
- `/`: redirect to `/admin/`;
- retained non-page contracts: health, build, schema, and versioned APIs; and
- architecture: ADR 0030 and UX-013.

### Baseline delivery

- [x] Preserve the complete pre-reset state as commit `548f15a` on
  `codex/pre-reset-20260731`.
- [x] Create and switch to `codex/page-by-page-rebuild`.
- [x] Add UX-013 and superseding ADR 0030 before changing routes.
- [x] Make `maru.baseline_urls` the default browser surface.
- [x] Implement only focused Sign in and the staff-only empty administration
  home.
- [x] Leave previous HTML pages unmounted while retaining health and versioned
  APIs.
- [x] Create `maru_rebuild_empty`, migrate it, and create only the first
  administrator.
- [x] Confirm zero organization, series, edition, registration, department,
  and position records.
- [x] Inspect desktop and 390-pixel layouts with no horizontal overflow.
- [x] Run the complete backend, schema, frontend-preservation, migration, and
  documentation quality gates.
- [x] Update `CURRENT.md` and add the append-only baseline checkpoint.
- [x] Obtain product-owner acceptance before designing the next page.

### Page 1: Platform administration home

- Branch: `codex/page-01-platform-home`
- Route: `/admin/`
- Contract:
  [`../product/page-contracts/01-platform-administration-home.md`](../product/page-contracts/01-platform-administration-home.md)
- Requirements: IDN-011, UX-013, UX-014
- Decision: ADR 0031

Checklist:

- [x] Agree that the Maru administrator is platform authority and not a
  convention participant.
- [x] Define the page purpose, placement, information, authorization, states,
  responsive behavior, tests, and non-goals before delivery.
- [x] Add an explicit platform-administrator account classification rather than
  relying on account creation order.
- [x] Reject platform administrators as convention membership, authority,
  participation, registration, volunteer, onboarding, and workforce subjects.
- [x] Replace the empty `/admin/` home with the read-only organization
  inventory.
- [x] Implement empty, populated, denied, and safe database-failure states.
- [x] Apply migration `identity.0010` to `maru_rebuild_empty` and verify the
  existing first administrator classification.
- [ ] Obtain supported 390-pixel visual evidence with no horizontal overflow;
  do not bypass the in-app browser URL security policy.
- [x] Inspect the 1280-pixel desktop layout with no horizontal overflow or
  browser runtime warnings; supported 390-pixel evidence remains pending after
  the in-app browser rejected the temporary narrow-frame method.
- [x] Run the complete backend, schema, frontend-preservation, migration, and
  documentation quality gates.
- [x] Update `CURRENT.md` and add the append-only Page 1 checkpoint.
- [x] Obtain product-owner acceptance before beginning Page 2.

### Page 2: Create organization

- Branch: `codex/page-02-create-organization`
- Route: `/admin/organizations/new/`
- Contract:
  [`../product/page-contracts/02-create-organization.md`](../product/page-contracts/02-create-organization.md)
- Requirements: IDN-002, IDN-011, IDN-012, UX-013, UX-015, AUD-001,
  AUD-002
- Decision: ADR 0032

Checklist:

- [x] Agree that only the recognizable organization name is necessary at
  creation time.
- [x] Record the future Executive Board invariant and property-editing boundary
  without creating placeholder governance in Page 2.
- [x] Add the name-only form and platform-administrator-only route.
- [x] Normalize the name and generate an 80-character-bounded,
  collision-safe slug with a non-ASCII fallback.
- [x] Create Draft with code-owned English and UTC defaults and blank optional
  properties.
- [x] Commit the organization and its successful audit evidence atomically.
- [x] Prove no membership, authority, board, series, edition, participation,
  registration, or workforce side effects.
- [x] Apply `organizations.0003` to `maru_rebuild_empty` without touching the
  preserved databases.
- [x] Inspect the desktop and 390-pixel Page 2 layouts with no horizontal
  overflow or browser runtime warning/error.
- [x] Run the complete backend, schema, frontend-preservation, migration, and
  documentation quality gates.
- [x] Update `CURRENT.md` and add the append-only Page 2 checkpoint.
- [ ] Obtain product-owner acceptance before beginning Page 3.

### Page-by-page contract

No second page starts until the current page has an agreed contract and has
been inspected in the running application. For every page, record:

- its single purpose and primary user;
- where it belongs in navigation and why;
- the minimum information shown;
- allowed actions and exact authorization boundary;
- empty, loading, success, validation, denied, and failure states;
- desktop and narrow layout evidence;
- automated behavior, permission, and tenant-isolation tests; and
- affected requirements, ADRs, module docs, and operator guidance.

Accepted initial sequence after the baseline decision:

1. Sign in.
2. Empty administration home.
3. Platform administration home (Page 1; implemented on its dedicated branch).
4. Create organization (Page 2).
5. Organization record (Page 3).
6. Create convention series (Page 4).
7. Convention-series record (Page 5).
8. Create event edition (Page 6).
9. Edition home (Page 7).
10. Establish first human convention authority (Page 8).
11. Person/account record.
12. Organization structure.
13. Registration template and edition form.
14. Attendee self-registration.

Pages 1 and 2 have been approved for implementation. The later order records
the agreed journey but does not pre-approve a Page 3 contract or
implementation.

## Resume point

The recovery snapshot and durable pre-reset branch remain available. Page 2 is
implemented on its dedicated branch and `maru_rebuild_empty` is migrated
through `organizations.0003`. Resume by completing any unchecked Page 2 gates,
then obtain owner acceptance. Do not design or implement Page 3 before that
response.
