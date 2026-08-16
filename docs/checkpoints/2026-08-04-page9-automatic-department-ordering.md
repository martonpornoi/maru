# Page 9 automatic Department ordering

Date: 2026-08-04
Status: implemented and focused-verified
Requirements: HR-011, UX-025, AUD-001, NFR-001, NFR-002, and NFR-009
Decision: ADR 0048

## Outcome

The Page 9 browser no longer asks organizers to enter or interpret a numeric
Department display order. Department creation and parent changes append after
the persisted siblings at the selected level. An edit that keeps the same
parent preserves a unique current placement; if the edited Department shares
its position with a sibling, that save assigns the edited row the nearest
following free sibling position.

Automatic placement is calculated inside the shared structure command after
the edition structure and Department rows are locked. It therefore retains
optimistic concurrency, idempotent creation, one aggregate-version step, and
the existing minimized audit/event/outbox evidence. The API contract is not
weakened or made nullable: strict integration clients still submit the bounded
integer `display_order` when they deliberately control presentation order.

Existing duplicate or sparse ranks are not silently rewritten during a read.
Their projection remains deterministic, and saving an affected Department
through the browser repairs that row. No schema migration or current-dataset
mutation was required.

## Verification

- Ruff: affected workforce command, forms, views, unit tests, and Page 9 HTML
  tests pass.
- Page 9 HTML mutation/form focus: 108 passed; the only failure in the combined
  109-case run is an unrelated pre-existing shared canonical-UUID contract
  mismatch from the in-progress Page 10/core working tree.
- Applicable form focus excluding that known mismatch: 21 passed.
- Structure command and strict mutation API focus: 60 passed.
- Authenticated live browser: Aurora Tails 2027 → Maid Café shows Events as the
  selected parent, displays the automatic-placement explanation, and contains
  no Display order field. The check used GET only and preserved the dataset.

## Recovery and compatibility

This change adds no migration. Rollback is a coordinated code rollback of the
form, templates, browser adapters, command behavior, tests, and ADR; existing
integer ranks remain valid throughout. API callers and built-in template
ordering are unchanged.

## Smallest next action

Continue the menu walkthrough. If organizers later need deliberate manual
reordering, design an audited move-before/move-after or drag interaction rather
than exposing the raw numeric rank again.
