# Create organization contract

- Status: Revised, implemented, and backend-verified in the unified shell;
  browser rehearsal pending
- Branch: `codex/page-02-create-organization`
- Route: `/admin/platform/organizations/new/`
- Requirements: IDN-002, IDN-011, IDN-012, EVT-005, UX-012, UX-013, UX-015,
  UX-016, AUD-001, AUD-002, PRI-001
- Decisions: ADRs 0032, 0033, 0034, and 0039

## Purpose and primary user

Let an active Maru platform administrator create a complete Draft organization
record without creating or joining a convention.

The page supports two honest paths: enter only the recognizable organization
name when nothing else is known, or capture the organization's available
public, legal, imprint, contact, and locale details in the same creation step.
Only the name is required.

## Placement and navigation

Platform administration home, Create organization, and Organization record share a persistent **Platform administration** navigation
row:

- **Organizations** is the primary link to
  `/admin/platform/organizations/`; and
- a compact adjacent **+ Add** action links to
  `/admin/platform/organizations/new/`.

The current destination uses `aria-current="page"`. The navigation remains
visible beside the content on desktop and becomes a compact horizontal block at
narrow widths. Platform administration home does not render a second competing creation button.

On success the browser redirects to `/admin/platform/organizations/`, where the
new Draft row and a one-time success confirmation are visible. The organization
name links to its Organization record.

## Information and actions

### Public identity

- **Organization name** — required, trimmed, internal whitespace normalized,
  maximum 160 characters.
- **Description** — optional public-facing summary, maximum 2,000 characters.

### Legal identity and imprint

- **Registered legal name** — optional, maximum 200 characters.
- **Legal address** — optional formatted postal address, maximum 1,000
  characters.
- **Responsible representative** — optional printable person or office label,
  maximum 200 characters; this is not an Executive Board appointment.
- **Registration authority** — optional register or authority name, maximum 200
  characters.
- **Registration identifier** — optional registry identifier, maximum 120
  characters.
- **Tax identifier** — optional jurisdiction-specific identifier, maximum 120
  characters.
- **Additional imprint text** — optional bounded legal wording not covered by
  the structured fields, maximum 5,000 characters.

These values are organization-owned C1 information and are not published by
being entered. The form warns against placing sensitive case, payment, or
identity-document data in the free-text field.

### Public contact

- **Website** — optional HTTP(S) URL.
- **Contact email** — optional general organization mailbox.
- **Contact telephone** — optional international E.164 number.

### Operating defaults

- **Primary operating country** — optional ISO-backed selection.
- **Default languages** — optional ordered ISO-backed selection; English is the
  code-owned fallback.
- **Default time zone** — optional IANA-backed selection; UTC is the code-owned
  fallback.

The page visibly states that the generated slug is code-owned and the resulting
status is Draft. It offers **Create organization** and **Cancel**.

The browser input contract is closed: only the fields listed above and the
CSRF transport field are accepted. A forged `slug`, `lifecycle`, organization
identifier, actor, timestamp, or any other undeclared key produces the
form-wide `unknown_input_field` validation error. Maru reports at most five
bounded field names and creates nothing; it never silently ignores extra
input.

## Defaults and resulting state

The command derives a lowercase ASCII slug from the name. An empty derived
slug falls back to `organization`; collisions receive `-2`, `-3`, and so on
without exceeding the 80-character limit.

The organization begins with Draft lifecycle. Omitted language and time-zone
values become `en` and `UTC`; all other optional properties remain blank.
Active is not selectable until the Executive Board governance workflow exists.

The administrator is the attributed creator in audit only. Creation produces
no membership, authority, Executive Board, participant, attendee, volunteer,
series, edition, registration, or workforce record.

## Authorization, privacy, and audit

Only an authenticated, active `platform_administrator` may load or submit the
route. Anonymous visitors are sent to Sign in. Ordinary accounts, including
Django staff accounts, receive `403` without learning whether a submitted name
or slug exists.

The service repeats authorization and model validation. The organization and
successful audit event commit atomically. Audit `changed_fields` identifies the
properties written but no legal, contact, representative, tax, address, or
imprint value is copied into audit metadata.

The intended data subject is the organization. A representative name can also
identify a person, so access remains platform/authorized-organizer only until a
separate publication action exists. Retention follows the organization legal
record and must be reviewed on closure. ADR 0034 permits deletion only while
the record is an empty Draft with no protected relationships.

## Page states

- **Initial:** all sections visible, name focused, optional values empty, English
  and UTC selected, and Draft explained.
- **Validation:** field-local messages and safe submitted values retained; no
  organization or success audit created.
- **Success:** redirect to the inventory, Draft row visible, one-time
  confirmation rendered.
- **Denied:** `403` with no tenant-name or inventory disclosure and no mutation.
- **Failure:** same form with a generic `503` alert and retry guidance; no
  partial organization or success audit survives.
- **Loading:** ordinary browser submission; no invented partial record.

## Responsive and accessibility evidence

The page uses one `h1`, programmatically labelled form sections, programmatic
field labels, associated help and error messages, visible keyboard focus, a
form-wide alert, semantic links and buttons, and text-independent meaning. The
side navigation identifies the current page. The form and navigation must fit
without horizontal overflow at 390 pixels and remain comfortably bounded on
desktop.

## Acceptance checks

- one-row **Organizations** and adjacent **+ Add** navigation on the organization setup and record surfaces;
- active platform-administrator GET and POST;
- anonymous redirect and ordinary/staff denial;
- name-only submission with code-owned defaults;
- complete-profile submission and persistence;
- URL, email, telephone, country, language, time-zone, and length validation;
- normalized name and collision-safe bounded slug;
- Draft-only lifecycle and rejection of every undeclared posted field;
- atomic audit success and rollback on database/audit failure;
- audit field names without copied sensitive values;
- no membership, authority, board, series, edition, volunteer, registration,
  participation, or workforce side effects;
- existing Draft records migrate with blank optional values;
- desktop and 390-pixel browser inspection; and
- focused plus complete quality gates and updated handoff documentation.

## Explicit non-goals

- Editing or safely deleting the already-created MaruCon record; that belongs
  to Organization record.
- Publishing imprint or contact information.
- Organization activation, suspension, closure, or transfer.
- Executive Board creation or appointment.
- Convention series or event edition creation.
- Organizer membership, access sharing, workforce, or participation.
