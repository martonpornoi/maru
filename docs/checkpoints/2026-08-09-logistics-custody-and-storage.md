# Checkpoint: Logistics storage, offers, manifests, and custody

- Date: 2026-08-09
- Phase: bounded repository milestone accepted; production rehearsal and
  repository-wide acceptance pending
- Related requirements: LOG-001 through LOG-008, AUD-001, AUD-003, PRI-001,
  VEN-002, NFR-001, NFR-002, NFR-009
- Related ADR: 0054 (Accepted)

## Outcome

Maru has a bounded `logistics` module for authenticated equipment offers,
purpose/retention-bound addresses, reusable external owner/provider profiles,
serialized assets and bulk lots, typed storage/box/container/vehicle nodes,
physical keys, loan/rental return obligations, reusable kits, labels, manifests,
Stage Tech receiving, offline reconciliation, and append-only custody events.

Current location, containment, quantity, condition, and custody derive only
from receive/pack/unpack/move/load/unload/handover/count/condition/damage/return
events. A person is never a container, keyholding grants no software access,
and the implementation does not collect continuous person or vehicle location.

## Decisions and privacy boundary

- External party records contain reusable legal/public identity only. Private
  contact/address values are purpose-coded, retention-bound, separately
  authorized, audited on read, and redacted by a bounded disposal worker.
- Offer pickup retention must cover availability and requested return. Contact
  disposal remains separate from immutable offer/ownership/custody evidence.
- Organization-global and edition-allocated catalog operations authorize at
  distinct exact targets; a platform administrator identity is not automatic
  convention authority.
- Typed containment is acyclic and tenant/edition compatible. Venue-room nodes
  require an active exact-edition venue selection.
- Keyholder and agreement intervals are half-open and exclusion-backed, so
  overlaps fail race-safely while adjacent handovers remain valid.
- Exact manifests resolve through typed resource bindings. Authenticated API
  and browser commands authorize before parsing, reject noncanonical/unknown
  inputs, repeat service authorization, and return private/no-store responses.

## Requirement status

The slice materially implements LOG-005 and LOG-008. The following
requirements remain partial and must not be reported complete:

- LOG-001: identity and value-class facts exist, but maintenance scheduling,
  history, and governed value-class workflow do not;
- LOG-002: no governed loss or tracked-subject disposal lifecycle command yet;
- LOG-003: no department demand, priority, or reservation planner;
- LOG-004: vehicles/loading windows/handovers exist, but driver, route, and
  delivery planning do not;
- LOG-006: receiving/discrepancy facts exist, but acceptance criteria and
  supplier invoice linkage do not; and
- LOG-007: append-only counts/reconciliation exist, but low-stock signals and
  wastage semantics do not.

## Changed areas

- Added `maru.logistics` models, commands, queries, exact bindings, retention,
  strict APIs, same-shell pages/forms/templates, personal offer discovery, and
  an actionable exact-manifest Stage Tech receipt workflow.
- Added a closed domain-event schema/handler and bounded contact-retention
  management command.
- Added strict input, preauthorization/no-store, scope, retention, interval,
  person-eligibility, manifest, and custody test coverage.
- Added module and operations documentation with explicit retention ownership,
  recovery, monitoring, and incomplete requirement boundaries.

## Verification status

- Migration drift is zero; static migration review certifies the frozen
  `logistics.0001 -> authorization.0016 -> logistics.0002` graph with 91
  triggers, 9 functions, 102 named schema objects, and 13 implicit uniques.
- App-local units (83 passed), Ruff, formatting, Python compilation, and the
  full Logistics source mypy pass are green. API/browser/navigation integration
  cases collect against the installed app and mounted routes.
- The final serialized acceptance matrix is green: 26 of 26 cases passed in
  49.47 seconds. It covers the complete Logistics workflows, catalog API
  parity, seven composite/tamper write-integrity cases, installed readiness,
  three navigation cases, runtime-role provisioning, and the deterministic
  demo seed. Earlier focused runs also proved exact-manifest Stage receipt
  parity and the corrected central navigation capability catalog.
- App-owned readiness is mounted in the production readiness path and fails
  closed on missing or weakened Logistics relations, constraints, triggers,
  functions, ACLs, migration recorders, or authorization fingerprints without
  reading tenant data. ADR 0054 is Accepted for this bounded architecture and
  migrated integrity boundary; these focused results are not production
  approval or completion of the broader LOG portfolio.

## Deployment and recovery notes

The intended migration order is `venues.0001` (the single owner of the shared
`btree_gist` extension), `logistics.0001` (tables), `authorization.0016`
(capabilities/resource kind/binding validator), then `logistics.0002`
(append-only/scope/current-state/binding guards). Restore validation must check
exclusions, triggers, function fingerprints, event registry, and typed
bindings. Deletion and direct current-state edits are not supported recovery
actions.

## Next actions

Run the repository-wide gate and authenticated responsive/accessibility browser
rehearsal. Rehearse deployment, runtime-role activation, restore/fix-forward,
monitoring, and operator response before production use.
