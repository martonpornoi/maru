# ADR 0099: Purpose-scoped Programme operator outputs

- Status: Accepted
- Date: 2026-09-13
- Issue: [#100](https://github.com/martonpornoi/maru/issues/100)

## Context

ADR 0097 delivers public and exact-person outputs, not room or Department
authority. Programme items have no Department ownership field; Applications
call ownership is not permission to infer an accepted item's operator audience.
Venues already owns responsible Departments and exact room resource bindings;
Workforce owns Department work and immutable Programme binding lineage.

## Decision

Add a dormant `scheduling.operator-release-output@1` adapter, pinned by no
current profile. The three closed purposes are one exact room, one exact
Department, and the whole edition. A room resolves through its current typed
Venue resource binding, a Department through its current exact non-retired
target, and an edition through its exact persisted target. Ordinary verified-
person policy evaluates each owner capability against that target. Department
hierarchy, planner access, context, URL parameters and public admission do not
grant additional authority. No grant, role, profile or production route is
activated by declaring these capabilities.

Independent owner capabilities are `scheduling.view_operator_output`,
`programme.view_operator_copy`, `programme.view_operator_delivery`,
`venues.view_operator_wayfinding` and `workforce.view_operator_staffing`.
Their maximum breadth is one edition; narrower exact Department/resource grants
remain possible through existing native scope/lineage policy. Each query fixes
its own fields and rechecks them before disclosure. A native Authorization
catalog migration adds these codes without grants and refuses downgrade after
retained grant or role evidence uses them.

Room membership is the exact selected room, not all rooms sharing a building
or physical combination member. Department membership is the union of its
currently responsible selected rooms and its Workforce-owned Programme-linked
occurrences, where the staffing adapter is deliberately adopted. The latter
requires independent Workforce `scope_links` authority even when detailed work
is not requested. Without that adapter the scope explicitly means rooms only.
This describes physical/work responsibility, not Programme item ownership.
The owner queries return bounded complete opaque membership with current
versions; neither may expose foreign labels, personnel, reasons or draft content.

Scheduling internally verifies the complete active canonical/native manifest,
then releases only occurrences within that currently authorized membership.
Independent owners resolve this reference themselves; a caller's reference,
filter, anonymous payload or former permission is never sufficient. Public-copy
output uses only the exact selected non-withdrawn reviewed rendition, never the
latest working or reviewed text. Placement phases and service-day geometry are
immutable release facts. Current technical, accessibility and media instructions
are separately requested fields with their current Programme revision identity,
version and observation time. Current room/venue wayfinding has its own versions.

Optional staffing is a minimized operational layer, not a personnel directory.
It returns authorized linked demand instructions, headcount and retained work
interval/state evidence from Workforce, including predecessor work relevant to
the selected occurrence. Current demand terms never replace retained accepted
intervals. Claims are not confirmations; confirmations are not proof of current
qualification, availability, physical attendance or actual work. Private people,
contacts, host availability, review/discussion and administrative rationale remain
excluded. No read edits, cancels, confirms, relocates or completes a Shift.

Unrequested delivery fields are explicitly absent, not inferred empty. An
unrequested staffing layer is distinct from an unadopted adapter, an authorized
empty collection and a requested-but-denied/unavailable layer. Requested layers
must all authorize and materialize, even when the approved selection is empty;
failure cannot silently become a complete reduced run sheet. Absent, withdrawn
or invalidated release states contain no approved timetable rows and do not
produce calendar downloads. Missing/oversized/moving evidence fails closed.

Canonical shared parent locks precede owner reads; scope membership, adopted
contracts, actor authority, source versions and the active release are checked
again before the result is returned. Sensitive reads require owner-specific
audit success. Public output is neither called nor widened. No excluded module
is queried to establish an operator relationship.

One bounded typed projection drives closed JSON, private calendar and a dormant
shared-management-shell HTML/print run sheet. The output states audience, exact
scope, requested layers, release identity/time, last checked time, owner versions
and saved-copy limitations. Calendar events are transparent room/run-of-show
context, never invitations or new personal work; work detail is not silently
turned into an attendee roster. Native print, genuine zoom and representative
screen-reader/comprehension remain #92 human acceptance, not automated proof.

## Consequences

- Department scope is explainable from existing owner facts without inventing
  item ownership or disclosing Applications proposal history.
- Fine field authority can deny a requested complete export; the interface must
  explain that state rather than secretly dropping a layer.
- Fresh owner rechecks and native history verification cost database reads but
  preserve release/source and privacy boundaries.
- Ordinary print/calendar files are not signed offline packs, reliable client
  updates or remote erasure. Change delivery, continuity, #97 logical recovery,
  guided activation and #92 integrated acceptance remain separate #48 gates.

## Alternatives considered

- Filter a planner/public dictionary: rejected; filtering grants no owner or
  field authority, and planning/public state is not operator admission.
- Infer an item's Department from its original proposal: rejected; no current
  Programme ownership contract establishes that relationship.
- Reuse latest demand intervals as accepted work: rejected; it would silently
  relocate or rewrite retained commitments.
- Expose full rosters by default: rejected; room instructions and coverage do
  not justify a general person directory or private calendars.

## Requirements affected

SCH-006/008/009/010/012, PRG-008, HR-014/015, AUD-001,
NFR-001/002/005/008/009/013. ADRs 0081/0087/0088/0093/0096/0097 remain accepted.
