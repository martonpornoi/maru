# Page 1 contract: Platform administration home

- Status: Implemented, verified, and accepted
- Branch: `codex/page-01-platform-home`
- Route: `/admin/`
- Requirements: IDN-011, UX-005 through UX-008, UX-013, UX-014
- Decision: ADR 0031

## Purpose and primary user

Give an active Maru platform administrator one trustworthy view of the
organizations configured in this installation. It answers only: "Which
organizers exist in Maru?"

It is not a convention dashboard. The administrator is a platform operator,
not a member or participant of any listed convention.

## Placement and navigation

`/admin/` remains the canonical authenticated home. ADR 0034 refines the
focused **Platform administration** side navigation shared with Pages 2 and 3.
One row contains the primary **Organizations** inventory link and a compact
adjacent **+ Add** action; it is not a convention selector, setup strip, second
shell, or link to preserved pages. Sign out remains in the existing header.

The organization-creation route belongs to Page 2. **+ Add** exposes it as a
stable administration action. Each inventory organization name links to its
purpose-built Page 3 record; the inventory itself remains read-only.

## Information and actions

The page shows:

- the signed-in platform administrator;
- a Platform administration heading;
- an explanation that platform access does not create participation;
- organization name, slug, lifecycle, series count, and edition count; and
- a separate account-boundary explanation.

It performs no mutations. It does not show organization membership, convention
staff, attendees, registration, finance, safety, or other edition-owned data.

## Authorization and data boundary

Only an authenticated, active `platform_administrator` account may load the
page. Anonymous visitors are sent to Sign in. Ordinary accounts, including
accounts with `is_staff=True`, receive `403`.

The global organization query is justified by platform scope and returns C1
inventory only. Loading it creates no membership, capability grant, role
assignment, participation, registration, volunteer application, or workforce
assignment. Restricted records remain governed by SAF-004.

## Page states

- **Empty:** zero organizations, a direct explanation, and the persistent
  Page 2 **+ Add** navigation item.
- **Populated:** stable alphabetical rows with lifecycle and related counts.
- **Loading:** the page is server-rendered atomically; partial stale rows or a
  decorative indefinite loading state are not rendered.
- **Success:** complete inventory and truthful count.
- **Denied:** `403` without leaking whether organizations exist.
- **Failure:** safe read-only `503`, retry guidance, and no mutation; the server
  logs the exception without exposing it in HTML.

## Responsive and accessibility evidence

The page uses one `h1`, labelled sections, a real table with caption and row
headers, a live error alert, visible keyboard focus, semantic text independent
of color, and the existing labelled POST-only Sign out action. At narrow width,
table rows become labelled record blocks without horizontal overflow.

Browser evidence must cover the empty live database at desktop and 390 pixels.
Automated populated-state coverage proves that counts and record labels remain
usable before Page 2 creates live records.

## Acceptance checks

- explicit account classification and migration of existing superusers;
- platform-only access, with ordinary staff denied;
- no convention relationship created by a page read;
- model-level rejection when a platform administrator is selected as a
  convention subject;
- empty, populated, and database-failure behavior;
- desktop and narrow browser inspection with no overflow or runtime errors;
- one-row shared navigation with correct current-action state and linked
  organization names;
- focused and complete automated quality gates; and
- updated current state, module documentation, and append-only checkpoint.

The owner accepted Page 1 before Page 2 implementation began.
