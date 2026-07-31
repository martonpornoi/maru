# Page 2 contract: Create organization

- Status: Implemented and verified; owner inspection pending
- Branch: `codex/page-02-create-organization`
- Route: `/admin/organizations/new/`
- Requirements: IDN-002, IDN-011, IDN-012, UX-013, UX-015, AUD-001,
  AUD-002
- Decision: ADR 0032

## Purpose and primary user

Let an active Maru platform administrator create the tenant record that later
pages will complete with accountable governance and convention setup.

The page answers one question: "What is this organization called?" It does not
ask the operator to complete legal identity, imprint, contacts, locale,
governance, series, edition, or convention staffing prematurely.

## Placement and navigation

Page 1 exposes a visible **Create organization** action in the organization
inventory. Page 2 stays within the same minimal Maru administration shell and
provides a clear **Back to organizations** path.

On success the browser redirects to `/admin/`, where the new Draft row and a
one-time success confirmation are visible. Page 3 will later make organization
rows navigable; Page 2 must not link to a record page that does not exist.

## Information and actions

The form contains one editable field:

- **Organization name** — required, trimmed, internal whitespace normalized,
  maximum 160 characters.

The page explains that Maru generates the URL slug and creates a Draft record.
It offers **Create organization** and **Cancel**. Submission creates no other
domain record.

## Defaults and resulting state

The command derives a lowercase ASCII slug from the name. An empty derived
slug falls back to `organization`; collisions receive `-2`, `-3`, and so on
without exceeding the 80-character limit.

The organization begins with:

- lifecycle `draft`;
- default language `en`;
- default time zone `UTC`; and
- blank optional legal name, description, website, contact, and country.

The administrator is the attributed creator in audit only. It does not become
a member, authority holder, participant, attendee, volunteer, or staff member.
Page 2 deliberately creates no Executive Board. IDN-012 and ADR 0032 require
the later governance workflow to provision or backfill that representation
before activation and to reserve organization-property editing for the active
Executive Board and platform administration.

## Authorization and data boundary

Only an authenticated, active `platform_administrator` may load or submit the
route. Anonymous visitors are sent to Sign in. Ordinary accounts, including
accounts with Django staff status, receive `403` without learning whether a
submitted name or slug already exists.

The creation service repeats the authorization check so a caller cannot bypass
the view. The organization and successful audit event are committed atomically.

## Page states

- **Initial:** empty name field, concise explanation, enabled create and cancel
  actions.
- **Validation:** field-local message, submitted safe value retained, no
  organization or success audit created.
- **Success:** redirect to the populated inventory, Draft row visible, one-time
  confirmation rendered.
- **Denied:** `403` with no tenant-name or inventory disclosure and no mutation.
- **Failure:** same form with a generic `503` alert and retry guidance; no
  partial organization or success audit survives.
- **Loading:** ordinary browser form submission; the server never renders an
  invented partial record.

## Responsive and accessibility evidence

The page uses one `h1`, a programmatic label, an associated error message,
visible keyboard focus, an alert for form-wide failure, semantic links and
buttons, and text-independent visual meaning. The single-column form must fit
without horizontal overflow at 390 pixels and remain comfortably bounded on
desktop.

## Acceptance checks

- active platform administrator GET and POST;
- anonymous redirect and ordinary/staff account denial;
- one-field required and maximum-length validation;
- name normalization and collision-safe slug generation;
- draft lifecycle and code-owned defaults;
- atomic audit success and rollback on audit/database failure;
- no membership, authority, participation, board, series, edition, volunteer,
  registration, or workforce side effects;
- Page 1 navigation and one-time success feedback;
- desktop and supported narrow browser inspection; and
- focused plus complete quality gates and updated handoff documentation.

## Explicit non-goals

- Organization record or property editing;
- legal profile, imprint, address, registration identifiers, or publication;
- organization activation, suspension, closure, transfer, or deletion;
- Executive Board creation or appointment;
- convention series or event edition creation; and
- organizer membership, access sharing, workforce, or participation.
