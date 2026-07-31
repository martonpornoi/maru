# Page 3 contract: Organization record

- Status: Implemented and verified; owner inspection pending
- Branch: `codex/page-03-organization-record`
- Route: `/admin/organizations/<slug>/`
- Requirements: IDN-002, IDN-011, IDN-012, EVT-005, UX-013, UX-014,
  UX-016, UX-017, AUD-001, AUD-002, PRI-001
- Decision: ADR 0034

## Purpose and primary user

Let an active Maru platform administrator inspect and maintain one existing
organization's complete profile. The page also provides a tightly bounded way
to remove an accidentally created organization before any convention or
governance record belongs to it.

This is an organization record, not a convention dashboard. The administrator
is an attributed platform operator and does not become an organization member,
Executive Board holder, participant, registrant, or volunteer.

## Placement and navigation

Page 1 inventory names link to the corresponding Page 3 record. Page 1,
Page 2, and Page 3 share one **Platform administration** navigation row:

- **Organizations** is the primary inventory link; and
- a compact adjacent **+ Add** action links to Page 2.

The inventory link is current on Page 1 and Page 3. The add action is current
only on Page 2. The actions remain individually focusable and labelled. At
narrow widths the row remains one coherent group rather than becoming two
stacked menu destinations.

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

Only an authenticated, active `platform_administrator` may load or submit
Page 3 during the controlled rebuild. Authorization runs before record lookup,
so denied accounts do not learn whether a slug exists. The update and delete
services repeat authorization and use row locks.

Successful changed updates and successful deletion are atomic with their audit
events. Audit identifies changed fields or the deleted record but excludes the
entered legal, contact, address, representative, tax, and imprint values.
Database or audit failure leaves the prior record intact.

When Executive Board governance is implemented, active Executive Board
authority must be added to profile editing per IDN-012. That extension is not a
reason to create placeholder membership or authority in Page 3.

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
instructions are associated with the input. Desktop and 390-pixel layouts must
have no horizontal overflow.

## Acceptance checks

- one-row **Organizations** plus adjacent **+ Add** navigation on all three
  pages, with correct current action;
- linked inventory names and an authorized populated record;
- anonymous redirect, ordinary/staff denial before lookup, and authorized 404;
- complete-profile population, validation, normalization, and changed-field
  audit without copied values;
- stable slug and lifecycle despite crafted POST values;
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
