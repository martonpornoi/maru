# Page 3 contract: Organization record

- Status: Implemented and responsive-smoke verified for platform oversight and
  scoped Executive Board authority; accessibility/state/owner evidence pending
- Branch: `codex/page-03-organization-record`
- Route: `/admin/platform/organizations/<slug>/`
- Requirements: IDN-002, IDN-004, IDN-011, IDN-012, EVT-005, UX-012 through
  UX-014, UX-016, UX-017, UX-019, UX-024, AUD-001, AUD-002, PRI-001
- Decisions: ADR 0034, ADR 0036, ADR 0039, ADR 0040

## Purpose and primary user

Let explicit platform oversight or an active Executive Board assignment with
`organizations.view_basic` inspect one existing organization's complete
profile; change requires `organizations.change_profile`. The page also gives
only the platform administrator a tightly bounded way to remove an accidentally
created organization before any convention or governance record belongs to it.

This is an organization record, not a convention dashboard. The administrator
is an attributed platform operator and does not become an organization member,
Executive Board holder, participant, registrant, or volunteer.

## Placement and navigation

Page 1 inventory names link to the corresponding Page 3 record. Every page
keeps the global **Organizations** destination and its adjacent compact
**+ Add** action. After an organization is selected, Page 3 also shows a
section named for that organization with:

- **Organization record**, current on Page 3; and
- **Convention series** with an adjacent **+ Add** action linking to Page 4.

The scoped series destination anchors the Page 3 section rather than opening a
global list. A Closed organization omits the unavailable add action. Actions
remain individually focusable and labelled. The desktop menu begins at normal
page padding rather than inside a centered grid; at narrow widths it stacks
above the record without horizontal overflow.

## Information and edit action

The record heading shows the current organization name, immutable slug, and
Draft lifecycle. The editable form uses Page 2's complete sections and rules:

- public identity: name and description;
- legal identity and imprint: registered name, legal address, representative,
  registration authority and identifier, tax identifier, and additional text;
- public contact: website, email, and E.164 telephone; and
- operating defaults: primary country, ordered default languages, and IANA
  time zone.

Only name is required. Saving normalizes the name and validates the complete
model. Slug and lifecycle are displayed but never accepted as posted fields.
A changed profile redirects back to the record with a one-time confirmation.
An unchanged valid submission performs no database or audit write and reports
that there was nothing to update.

Both browser forms use closed input contracts. The profile form accepts only
the Page 2 profile fields plus CSRF. The deletion form accepts only
`confirmation_name`, `acknowledge`, and CSRF. Forged `slug`, `lifecycle`,
organization identifiers, version values, actor/timestamp fields, or any other
undeclared key fail with `unknown_input_field`; they are not discarded and no
mutation is attempted.

## Delete action

The danger zone is a separate POST form and never shares the profile-update
button. It requires:

- exact, case-sensitive entry of the current organization name; and
- acknowledgement that deletion is permanent.

Deletion succeeds only while the organization is Draft and has no related
domain records. Any convention series, edition, membership, grant, role,
participation, registration, workforce, communication, restriction, payment,
or other protected relationship refuses deletion. Success returns to Page 1
with a one-time confirmation. The organization UUID remains in audit evidence;
its name and profile values are not copied into the event.

Active, suspended, or closed organizations cannot use deletion even if empty.
They require a future reasoned closure and data-exit workflow.

## Authorization, privacy, and audit

The M1 adapter allowed only an authenticated, active
`platform_administrator`. ADR 0040 adds exact organization-scoped Board view and
change capabilities; the current backend matrix verifies both. Authorization
runs before record lookup, so denied accounts do not learn whether a slug
exists. The update and delete services repeat authorization and use row locks;
protected empty-Draft deletion remains platform-only.

Successful changed updates and successful deletion are atomic with their audit
events. Audit identifies changed fields or the deleted record but excludes the
entered legal, contact, address, representative, tax, and imprint values.
Database or audit failure leaves the prior record intact.

ADR 0040 and Page 8 define how active Executive Board authority is established.
The shared profile service and Page 3 adapter accept exact organization-scoped
`organizations.change_profile` authority. Scoped non-staff, unrelated staff,
wrong-tenant, inactive, and platform paths are covered without creating
placeholder membership or authority in Page 3.

## Page states

- **Initial:** current values are populated, slug and Draft status are visible,
  and both forms explain their boundary.
- **Validation:** field-local update errors or delete-confirmation errors retain
  safe input and do not mutate the record.
- **Update success:** redirect to the same record and show a one-time message.
- **Delete success:** redirect to the inventory and show a one-time message.
- **Denied:** `403` before record lookup and with no tenant disclosure.
- **Not found:** an authorized administrator receives `404` for an unknown
  slug.
- **Failure:** a generic `503` alert supports retry; no partial update, delete,
  or success audit survives.
- **Loading:** ordinary server rendering; no invented partial record.

## Responsive and accessibility evidence

The page uses one `h1`, labelled profile sections, field-local errors, visible
focus, status text independent of color, and separately labelled update and
delete forms. The danger action is not the default action. Exact confirmation
instructions are associated with the input. Local desktop and 390-pixel smoke
has no horizontal overflow or console warning. Complete keyboard/automated-
accessibility, denied/error states, and owner-led form rehearsal remain release
evidence.

## Acceptance checks

- global **Organizations** plus adjacent **+ Add**, selected-organization
  record and series destinations, and exactly one correct current action;
- linked inventory names and an authorized populated record;
- anonymous redirect, ordinary/staff denial before lookup, and authorized 404;
- complete-profile population, validation, normalization, and changed-field
  audit without copied values;
- stable slug and lifecycle, with crafted or otherwise undeclared POST fields
  rejected before mutation;
- unchanged save without write or audit;
- exact-name and acknowledgement delete validation;
- delete restricted to empty Draft organizations;
- protected refusal for every representative relationship family;
- atomic update/delete rollback on audit or database failure;
- no membership, authority, participation, registration, or workforce side
  effects;
- desktop and 390-pixel browser inspection without modifying or deleting the
  owner's MaruCon record; and
- focused and complete quality gates plus handoff documentation.

## Explicit non-goals

- Organization lifecycle transitions or slug migration.
- Executive Board provisioning or appointment.
- Publishing imprint or contact information.
- Convention series or event edition creation.
- Deleting an organization that has ever accumulated protected records.
