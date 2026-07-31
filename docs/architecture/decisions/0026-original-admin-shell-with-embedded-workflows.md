# ADR 0026: Original administration shell with embedded workflows

- Status: Accepted
- Date: 2026-07-31
- Supersedes: ADR 0025 shell placement and compatibility redirects
- Extends: ADR 0023 unified product and ADR 0024 guarded workflows
- Requirements: IDN-009, EVT-004, UX-001 through UX-009, UX-011, UX-012,
  NFR-001 through NFR-003

## Context

ADR 0025 placed the React Management Console at `/admin/` and moved Django's
alphabetical index to `/admin/records/`. Although both surfaces shared one URL
namespace, operators still encountered two global navigation systems and the
original administration home was no longer the page they expected at
`/admin/`.

Clean-convention testing established a clearer expectation: the existing
Django administration shell should remain the stable home, and safe recurring
workflows should appear inside it. The useful API and command boundaries do
not require a second application shell.

## Decision

Use the original Django administration index and navigation as Maru's single
global administration shell.

- `/admin/` renders the original permission-filtered Django administration
  index, enhanced with Quick start and Convention work cards.
- One collapsible administration sidebar contains Convention work and
  specialist record links on the index, workflow pages, and model pages.
- API-backed Today, People, My registration, Registration, Reports & badges,
  Setup guide, Security history, and Manage access workflows are embedded at
  `/admin/workspace/` inside the Django administration base template.
- The embedded React application does not render its own sidebar, mobile
  navigation, or second brand shell. Its header is limited to edition context,
  account actions, and contextual access controls.
- Existing model routes such as `/admin/identity/account/add/` remain
  unchanged. There is no separate `/admin/records/` directory route.
- `/manage/` and `/staff/` are removed instead of redirected, so they cannot
  become alternate entry points or preserve a second information
  architecture.
- Staff-assisted intake has one canonical route at
  `/admin/registration-assist/<edition>/`.

The shell is not an authorization system. Any active authenticated account may
reach the administration home and embedded workflows, where Maru's scoped
capability checks determine available data and actions. Django model pages
continue to require Django staff/model permission. Selected edition state is
working context, never proof of authority.

## Consequences

Operators see one header, one menu, one edition-oriented working area, and one
stable administration home. Purpose-built workflows can replace specialist
model forms incrementally without moving users to another console.

The internal frontend source and static directories retain their historical
`staff-console` name; this is an implementation label, not a user-facing
surface. Bookmarks to removed `/manage/`, `/staff/`, or `/admin/records/`
routes must be updated rather than silently redirected.

The Django index is deliberately available to active non-staff accounts, but
its model directory remains permission-filtered. Direct model URLs retain
Django's staff boundary, and API calls retain tenant-, edition-, capability-,
and field-level checks.

## Alternatives considered

- Keep the React shell at `/admin/` and Django records at `/admin/records/`:
  rejected because it replaced the familiar administration home and still
  presented two navigation systems.
- Redirect `/manage/` and `/staff/` to `/admin/`: rejected because redirects
  keep obsolete entry points alive and make route ownership harder to
  understand.
- Reimplement all API-backed workflows as Django model forms: rejected because
  lifecycle commands, scoped authorization, audit, and transactional services
  must remain the single behavior boundary.
- Allow React to keep its own sidebar inside the Django shell: rejected because
  nested global menus duplicate destinations and create unclear hierarchy,
  especially on narrow screens.
