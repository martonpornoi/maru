# ADR 0034: Organization record management

- Status: Accepted
- Date: 2026-07-31
- Supersedes: ADR 0033 only for the side-navigation layout and its deferral of
  existing-organization editing
- Requirements: IDN-002, IDN-011, IDN-012, EVT-005, UX-013, UX-014,
  UX-015, UX-016, UX-017, AUD-001, AUD-002, PRI-001

## Context

Page 2 can create a complete Draft organization, but Page 1 still renders each
inventory name as inert text and Page 2 is the only place where its profile can
be entered. The product owner also preferred the preserved administration
pattern in which one model row placed **Add** beside the model destination,
instead of giving **Organizations** and **+ Add** equal stacked rows.

The preserved Django record editor allowed organization changes but disabled
ordinary deletion. The controlled rebuild needs the useful record interaction
without restoring raw model administration or making historical tenant data
erasable.

## Decision

Page 3 is a purpose-built organization record at
`/admin/organizations/<slug>/`. Organization names on Page 1 link to it. The
shared navigation uses one row: **Organizations** is the primary destination
and a compact adjacent **+ Add** action opens Page 2. Each action has an
independent accessible name and current-page state.

An active platform administrator can update the same complete profile accepted
by Page 2. The service locks and reloads the organization, repeats platform
authorization, normalizes and validates the profile, keeps the stable slug and
lifecycle code-owned, and appends an audit event in the same transaction. The
audit lists changed field names without copying profile values. A submission
with no changes performs no write and produces no audit event.

Page 3 includes a separate danger zone for deletion. Deletion requires the
operator to enter the current organization name exactly and acknowledge that
the action is permanent. The service repeats authorization, locks and reloads
the organization, permits only Draft lifecycle, and relies on protected domain
relationships to refuse deletion if any related record exists. The delete and
its audit event are atomic. The audit retains the deleted UUID but not the
organization name or entered profile values.

Until the Executive Board workflow exists, Page 3 is platform-administrator
only. IDN-012 remains binding: the later governance page must extend property
editing to active Executive Board authority without making the platform
administrator a member, board holder, or convention participant. Activation,
other lifecycle transitions, governance, publication, series creation, and
edition creation remain separate workflows.

## Consequences

The owner-created MaruCon Draft can be completed in place and its stable URL
does not change when its public name changes. Accidental deletion is bounded to
an unused Draft and cannot cascade through convention or people history. Once
any related record exists, the organization must follow a future closure and
data-exit process instead.

The organization page remains long because it deliberately exposes the
complete profile once, grouped in the same sections as creation. This avoids a
second profile vocabulary and keeps Page 4 focused on convention series.

## Alternatives considered

- Restore Django's generic model change page: rejected because the rebuild is
  restoring reviewed purpose-built pages, not the full specialist-record tree.
- Keep two equal navigation rows: rejected after owner inspection; the compact
  add action better communicates that Add belongs to Organizations.
- Allow deletion of organizations with related records: rejected because
  cascaded tenant-history removal conflicts with Maru's retention and audit
  boundary.
- Allow lifecycle or slug changes on the record form: rejected because both
  require explicit transition and URL-migration workflows.
