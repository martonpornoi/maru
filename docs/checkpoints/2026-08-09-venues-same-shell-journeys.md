# Checkpoint: Venue same-shell catalog and schedule journeys

- Date: 2026-08-09
- Phase: executable same-shell completion
- Related requirements: UX-027, VEN-001, VEN-002, VEN-003, VEN-008,
  VEN-009, SCH-009, SCH-010, SAF-008, AUD-001, NFR-001, NFR-002
- Related ADRs: 0001, 0002, 0003, 0005, 0008, 0049, 0053

## Outcome

Authorized organizers can execute the existing Venue catalog and schedule
commands in the shared Maru shell. Closed forms cover reusable property
profiles, site/building/space/configuration paths, mergeable combinations,
governed media and layouts, accommodation room types and night inventory,
edition property/space selection, edition-local hard availability, operational
bookings, rescheduling, dual-control review/publication, withdrawal, and
cancellation. Pages use shared admin context and show safe conflict, capacity,
version, and independent-control errors without a second domain model.

Attendees receive an always-resolved, pinnable, searchable My schedule entry.
The cross-edition index derives exact Participation scopes before touching
published schedule labels, bounds distinct eligible editions in recent order,
and links to the minimized exact-edition schedule. Foreign edition names and
published rows cannot enter or starve that index.

## Security and privacy

- Every Venue HTML POST checks the route organization, edition, or typed space
  capability before constructing or validating a form.
- Strict UUIDs, canonical control integers, and persisted edition-zone times
  fail closed, including daylight-saving gaps and folds.
- Authenticated staff and My Maru HTML/API responses are private/no-store; the
  separate public minimized schedule API remains cacheable.
- Restricted reads and writes continue through the audited query and
  transactional command contracts.

## Verification

- Venue integration matrix: 12 passed, including malformed-input authorization
  invariance, capacity, overlap, dual control, public minimization, typed scope,
  foreign-edition non-disclosure, and bounded-prefix starvation.
- My schedule navigation/My Maru regression: 2 passed.
- Venue strict form/DST/template unit matrix: 10 passed.
- Ruff passed for Venue source and focused tests.
- Focused mypy passed for Venue forms, queries, views, URLs, and API.
- Root reverse/resolve and six-template compilation passed. Django's only
  system-check warning was the expected invitation-key W001.

## Known boundaries

This journey does not add programme ownership/adapters, guest room assignment
or fair allocation, travel/hospitality fulfilment, schedule exports, or
person/equipment/qualification conflicts. Those remain separate requirements
and must not be inferred from accommodation inventory or room bookings.
