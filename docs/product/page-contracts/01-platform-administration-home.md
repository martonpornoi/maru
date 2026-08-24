# Platform administration home contract

- Status: Implemented in the task-oriented responsive shell and focused-test
  verified; complete browser/accessibility/state-matrix/owner evidence pending
- Branch: `codex/page-01-platform-home`
- Route: `/admin/platform/organizations/`
- Requirements: IDN-011, UX-005 through UX-008, UX-012 through UX-014,
  UX-019, UX-027, UX-029
- Decisions: ADR 0031, ADR 0039, ADR 0049, ADR 0055

## Purpose and primary user

Give an active Maru platform administrator one trustworthy view of the
organizations configured in this installation. It answers only: "Which
organizers exist in Maru?"

It is not a convention dashboard. The administrator is a platform operator,
not a member or participant of any listed convention.

## Placement and navigation

`/admin/` remains the canonical authenticated shell home. Platform administration home lives in the
reserved `/admin/platform/` route space so it cannot collide with Django
application-label routes. Under ADRs 0049 and 0055, Platform administration home participates in one
permission-filtered registry shared by the authenticated shell. The default
home and **Platform administration** group prioritize the durable
**Organizations** destination and current setup work instead of presenting
every creation command and technical model as an equal choice.

The organization-creation route belongs to Create organization. **Add organization** is a
contextual action beside the inventory and is discoverable through the
search-only **Actions** group; it is not pinnable or a permanent equal-weight
sidebar row. Authorized technical records remain searchable behind the
collapsed **Specialist records** disclosure and the home-page specialist
gateway. Every render resolves and authorizes each item again. This registry is
not a convention selector, setup strip, second shell, or link to preserved
pages. Sign out remains in the existing header. Each inventory organization
name links to its purpose-built Organization record; the inventory itself remains
read-only.

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

- **Empty:** zero organizations, a direct explanation, and the contextual
  Create organization **Add organization** primary action.
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

At 1,100 CSS pixels and below the shell uses the Maru-owned closed-by-default
drawer; wider layouts retain the persistent sidebar. The compact context
control and inventory must not force page-level horizontal scrolling. Local
desktop and 390-pixel smoke is historical evidence, while focused source and
integration coverage now exercises the responsive shell and task navigation.
Authenticated rendered checks at 320, 390, 768, 958, 1,024, 1,280, and 1,920
pixels plus 200 percent zoom, complete keyboard/automated-accessibility checks,
all failure states, and owner-led rehearsal remain release evidence.

## Acceptance checks

- explicit account classification and migration of existing superusers;
- platform-only access, with ordinary staff denied;
- no convention relationship created by a page read;
- model-level rejection when a platform administrator is selected as a
  convention subject;
- empty, populated, and database-failure behavior;
- the complete responsive width/zoom matrix with no page-level overflow or
  runtime errors;
- one searchable, permission-filtered registry with one durable
  **Organizations** destination, a contextual/search-only non-pinnable
  **Add organization** action, one correct current destination, stable
  reauthorized pin keys, and linked organization names;
- one collapsed/searchable **Specialist records** gateway rather than a full
  model directory on the home page;
- focused and complete automated quality gates; and
- updated current state, module documentation, and append-only checkpoint.

The owner accepted Platform administration home before Create organization implementation began.
