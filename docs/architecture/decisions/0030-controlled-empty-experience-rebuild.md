# ADR 0030: Controlled empty-experience rebuild

- Status: Accepted
- Date: 2026-07-31
- Supersedes: ADR 0026 and ADR 0027 for the currently mounted browser
  experience
- Requirements: UX-001, UX-005 through UX-008, UX-010, UX-013, NFR-001
  through NFR-003, NFR-008

## Context

The repository has a substantial tested Django/domain/API foundation, but the
administration experience was reorganized repeatedly through ADRs 0022 through
0027. Moving workflows, menus, setup guidance, Django records, and an embedded
React application into successive shells did not produce a product experience
the owner considered coherent. Continuing to restyle or rearrange the same set
of pages would make their purpose and ownership harder to evaluate.

The owner chose an empty-experience reset rather than an empty-codebase reset.
Existing data models, migrations, authorization, audit, APIs, services, and
tests remain valuable. Existing browser pages must no longer imply that their
information architecture is accepted.

## Decision

Make a deliberately minimal URL configuration the default Maru experience.

- `/` redirects to `/admin/`.
- `/accounts/login/` is the only unauthenticated HTML page.
- `/admin/` is the only authenticated HTML page and requires an active staff
  account. It shows identity, sign-out, one plain empty-state message, and no
  setup, convention, edition, record, recent-action, or workflow navigation.
- `/accounts/logout/` remains a POST action rather than a content page.
- Previous Django model administration, Convention work, public registration,
  attendee directory, account-recovery HTML, guardian, and volunteer pages are
  not mounted by the default URL configuration and therefore return 404.
- Health, build, schema, and versioned API routes remain mounted so backend
  behavior and security boundaries remain executable and testable. Local APIs
  use JSON rather than adding browsable-API HTML pages.
- The preserved URL configuration and frontend source remain in the repository
  as recovery evidence during the rebuild, but are not the default product
  experience and must not be described as current.

Development and production use the empty-experience URL configuration.
Automated legacy/backend tests may select the preserved URL configuration while
the corresponding services are being carried forward. Dedicated baseline
tests prove the actual default routes and permission boundary.

Reintroduce browser pages one at a time. Each page requires the contract in
UX-013 and the reset ledger before implementation begins. Merely linking a
preserved page or mounting the former administration site is not a rebuild.

Use a new empty PostgreSQL database for the baseline. The database contains
only migrated schema and the first platform administrator. Existing `maru` and
`marucon_rehearsal` databases remain recovery/reference data and are not reset.

## Consequences

The running application becomes intentionally sparse and easy to reason about.
The backend remains available for incremental page work without prematurely
recreating navigation. Previous UI tests remain useful as preserved behavior
evidence, while new tests define what is actually mounted.

For a time, the repository contains more implemented backend behavior than the
browser exposes. Documentation must say this plainly. The preserved URL
configuration is temporary migration scaffolding and must not become an
undocumented alternate product surface.

The empty administration home is not a dashboard, setup wizard, record
directory, or promise about the final shell. Its only purpose is to prove
authentication and provide a stable place from which the first approved page
can later be introduced.

## Alternatives considered

- Continue refining the ADR 0026/0027 shell: rejected because the owner no
  longer trusted the accumulated information architecture.
- Delete the backend and create a new Django project: rejected because it
  would discard tested tenancy, authorization, audit, registration, privacy,
  payment, workforce, and recovery behavior unrelated to page placement.
- Keep old pages mounted but remove their links: rejected because guessed URLs
  would still expose an experience that has not been approved.
- Reset the existing databases: rejected because an empty baseline can use a
  new database without destroying evidence or rehearsal data.
