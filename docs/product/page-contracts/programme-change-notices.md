# Programme change notices

- Status: Accepted dormant component contract; #104 implementation in progress.
- Requirements: OPS-009, SCH-010/012, AUD-001, PRI-001/008, UX-007/008/029,
  NFR-001/002/013; ADR 0102.
- Organizer route: `/admin/programme/changes/<organization_id>/<edition_id>/`.
- Personal route: `/my/<organization_id>/<edition_id>/programme-changes/`.
- Both remain synthetic-installable only. #108 owns integrated navigation and
  profile promotion; current production routes/manifests remain unchanged.

## Purpose and authority

The coordinator previews one exact affected occurrence and owner relationship,
prepares a reasoned package, obtains independent approval or rejection, and
records a deliberate manual handoff. The genuine recipient sees only their own
approved package and can acknowledge that exact change. Preparation, review,
manual handoff and acknowledgement are separately labelled facts. There is no
delivery provider in this workflow: no button claims successful delivery.

Use the existing Administration and My Maru shells, one H1/main, scope and Access
explanation. Read authority precedes parsing private input. Every command has
independent current capability, source, relationship and version checks. Neither
an action button nor a hidden digest grants authority. The personal form accepts
no other person or private explanation. Organizer reasons never enter personal
output or its form state.

## Workflow and discovery

Provide a bounded retained-notice inventory for an exact edition, optionally
narrowed to one release. Personal discovery filters the authenticated recipient
in the database before inspecting notice records, and only approved records are
eligible. Each displayed package independently recomposes current purpose and
source. Stale or no-longer-authorized packages are omitted, without hidden counts
or identifiers; the inventory explicitly is not a delivery-completeness report.
An oversized inventory fails closed and asks for an exact release filter. No
partial first-page list is advertised as complete, and no recipient directory is
created. Each detail and action authorizes again.

Preparation accepts exact release/occurrence and host/work relationship or
operator scope references, with an explicit operator account only for operator
purposes. The bounded component exposes labelled reference controls; #108 must
connect these to authorized owning-task selections rather than require ordinary
department users to discover database identifiers. A preview is non-mutating and
shows before/after phases, required host presence where applicable, changed
fields, source state and exact references. Opaque room/copy references are not
invented human labels. Current timetable links resolve separately authorized
owner output; they never restore suppressed historical details.

Only a matching displayed preview may be prepared. The command recollects that
preview before saving. An independent reviewer approves or rejects the exact
package with rationale. Approved packages expose a manual handoff action and a
recipient-only acknowledgement link. Opening/copying the package records neither
handoff nor acknowledgement. Rejection is terminal, and correction requires a
new package. Acknowledgement may precede manual handoff. Work intervals,
attendance and timetable approval never change through this surface.

## States, interaction and recovery

- Empty: no currently viewable packages, not proof that every recipient was
  notified. Read-only users can inspect but cannot gain command authority.
- Validation: field-linked errors and safe entered values; no command ran.
- Success: redirect to a fresh authorized detail; no resubmission on refresh.
- Stale/conflicting: 409, no old package/action controls; refresh and explicitly
  preview the latest source. Never silently update a submitted digest/version.
- Rejected: visible terminal state, no handoff or acknowledgement controls.
- Denied/foreign: uniform 404 without record details. Malformed input: 400.
- Unavailable/overflow/audit failure: 503, no cached or partial private content.
  Retry keeps the original idempotency key for the exact same intent.
- No provider route: explicit manual-only state, never queued/delivered/failed
  provider fiction. Missing acknowledgement remains visible as missing.

Use native forms, labelled fields, normal links, visible focus and wrapping
cards; no dragging, custom animation or modal is required. CSRF, closed action
input, field and response bounds, HTML escaping, private/no-store responses,
same-origin form policy and nonce-bound shared-shell script apply. Safe validation
errors do not echo raw arbitrary request keys. Errors have an accessible summary.
Refresh/discard loses only unsaved input; immutable saved evidence is retained.

## Acceptance

Maintain owner-authorized ordinary, denied, foreign, stale, retry, rollback,
concurrent-decision, native integrity and recovery cases. Run non-database form,
transport, disclosure and rendering tests under ADR 0100; maintained PostgreSQL
cases remain explicitly unexecuted #102 debt. Rehearse synthetic role/state and
responsive keyboard behavior without enabling production routes. Genuine zoom,
screen-reader and human comprehension belong to #92/#48, not a fabricated pass.
