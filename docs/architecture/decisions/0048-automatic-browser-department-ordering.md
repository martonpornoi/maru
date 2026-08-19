# ADR 0048: Automatic browser Department ordering

- Status: Accepted
- Date: 2026-08-04
- Clarifies: ADR 0045
- Requirements: HR-011, UX-025, AUD-001, NFR-001, NFR-002, and NFR-009

## Context

ADR 0045 made `display_order` an editable bounded Department property for both
HTML and API clients. In the record-oriented administration workflow this
exposed an implementation rank without explaining the resulting hierarchy.
The browser defaulted every new Department to zero, so siblings could receive
the same value. A user could then change one number without seeing an apparent
move when the existing deterministic name tie-break already produced that
order.

Maru still needs stable deliberate ordering for immutable built-in templates
and future timetable or structure integrations. Existing editions may also
contain equal or sparse ranks. Rewriting every sibling as a side effect of a
read would violate the audited command boundary, while an uncoordinated browser
calculation could assign the same rank during concurrent requests.

## Decision

The browser Department create and update forms no longer render or accept
`display_order`. It is server-owned in this workflow:

- creation appends after the persisted siblings under the selected parent;
- reparenting appends after the persisted siblings under the new parent;
- an edit that keeps the same parent preserves the current rank when no sibling
  shares it; and
- when the edited Department has a duplicate sibling rank, that save uses the
  nearest following free rank and therefore repairs the collision without
  moving it past unrelated later siblings.

The command service calculates automatic placement only after locking the
edition structure aggregate and its Departments. Creation and reparenting use
the next rank after the maximum sibling rank, with a bounded unused-rank
fallback if the maximum allowed value is already occupied. Duplicate repair
uses the nearest following gap, then a bounded earlier gap only if necessary.
Optimistic concurrency, one-version advancement, audit, event, outbox, and
idempotent creation rules remain unchanged.

Existing equal ranks are not rewritten on GET or by an unrecorded bulk repair.
The projection remains deterministic through its name and stable-identifier
tie-break until an affected Department is saved through the browser. A later
explicit normalization command may be added if deployment evidence shows it is
needed.

Strict API clients continue to submit an integer from zero through 65,535.
This preserves the accepted integration contract and deliberate template or
planner ordering. Passing no rank is an internal browser-service instruction,
not a new nullable API field.

## Consequences

- Organizers choose hierarchy and content instead of maintaining unexplained
  numeric ranks.
- New browser-created siblings do not all default to zero.
- Editing one of the existing duplicate siblings repairs that record without a
  hidden multi-record mutation.
- Concurrent browser commands cannot calculate placement outside the aggregate
  lock.
- API consumers retain full ordering control and can still create duplicate
  ranks; the deterministic projection and browser repair behavior make those
  states safe and explainable.
- A future drag, move-before, or move-after experience can be introduced as an
  explicit audited ordering command without returning the raw rank field to the
  ordinary editor.

## Alternatives considered

### Sort every Department alphabetically and remove stored order

Rejected. It would discard template and integration intent and make renaming a
silent structural reorder.

### Renumber every sibling whenever one Department changes

Rejected. A one-record edit would mutate unrelated Departments and require
broader version/evidence semantics without a demonstrated product need.

### Normalize ordering during structure reads

Rejected. GET projections must remain read-only, cache-safe, and free of hidden
administrative mutations.

### Keep the numeric browser field and validate uniqueness

Rejected. Uniqueness would prevent collisions but would not make numeric rank
maintenance understandable or necessary for ordinary administration.
