# Programme Operations adoption contract

- Date: 2026-08-31
- Phase: Progressive adoption and pre-production release evaluation
- Outcome: Accepted one exact, composite Programme Operations contract from
  blank setup through on-site timetable continuity without activating runtime
  behavior
- Requirements: EVT-006, EVT-007, HR-013, HR-015, PRG-008, SCH-011, SCH-012,
  OPS-009, NFR-013
- Decision: ADR 0081
- Delivery: umbrella #48, child #57

## Outcome

Maru now has one bounded contract for a Programme department to start with
purpose-specific accounts, collect and review programme proposals, create
accepted items, build one conflict-aware timetable, connect venue approval and
volunteer staffing, release audience-safe projections, and carry a usable
run-sheet and degraded pack on site.

The target `programme_operations@1` manifest adopts Applications, Programme,
Scheduling, Venues, and Workforce over shared Identity, Organizations, Events,
Authorization, Audit, Effects, and Privacy namespaces, with mandatory pinned
recovery and export continuity contracts. It
excludes attendee Participation, Registration, payments, attendance,
accreditation, and unrelated modules. The contract does not add the profile to
the executable catalog or introduce any setup, destination, authority, route,
model, migration, API, adapter, publication, or side effect.

## Decisions

- Key the manifest by exact profile code and version and pin modules,
  capabilities, destinations, writers/effects, and adapter/conflict sources.
  Later catalog changes cannot silently expand an adopted edition.
- Keep Applications authoritative for calls, proposals, private answers,
  revisions, review evidence, decisions, and target receipts. Programme begins
  at the idempotent accepted transition.
- Keep Programme authoritative for accepted items, host relationships,
  readiness, operational layers, and approved public-content versions.
- Keep Scheduling authoritative for service days, occurrences, placements,
  candidate/conflict evidence, immutable releases, and all timetable
  projections.
- Keep Venues authoritative for physical-space facts, availability, capacity,
  occupancy, and venue approval. A Programme-linked booking cannot publish a
  second public Programme schedule; unrelated bookings retain ADR 0053's
  independent lifecycle.
- Keep Workforce authoritative for Departments, Positions, Assignments,
  Availability, Shift commitments, and work history. Its Programme adapter may
  reconcile owned demand but cannot silently rewrite a person's commitment.
- Generalize profile-aware assignment evidence: any profile adopting Workforce
  while excluding attendee Participation keeps the capacity pointer null and
  creates no Participation evidence.
- Treat hosts, reviewers, and volunteers as purpose-scoped relationships. A
  personal timetable can derive from explicit host or Workforce relationships
  without manufacturing attendee Participation.
- Keep check-in, lateness/absence, Shift actual time, disputes, and Shift handover in
  issue #24. Timetable publication is neither attendance nor proof of work.

## Changed areas

- Stable product requirements and the ADR catalogs
- ADR 0081 and the architecture/module ownership map
- Programme Operations setup, workflow, information-architecture, and domain
  contracts
- Roadmap, delivery plan, backlog, production ledger, current-state handoff,
  and changelog
- Focused documentation-policy drift protection

## Verification

Authoring verification on the completed documentation graph passed:

- 19 documentation-policy tests, including the focused Programme Operations
  contract-drift assertion;
- Ruff lint for the changed Python test;
- repository documentation validation across 363 Markdown files and 212 unique
  requirement identifiers; and
- `git diff --check`.

Fresh warning-fatal Sphinx/AutoAPI generation also passed. Independent review
and a separate acceptance-criteria audit found no remaining contract or scope
issue. Clean-tree exact-commit certification and protected `PR gate`
acceptance remain separate delivery evidence and must pass before merge.

## Data, migration, and deployment notes

This child is documentation and architecture only. It changes no production
data, schema, runtime database role, profile catalog, authorization grant,
navigation, route, API, worker, provider, or deployment. Existing
`full_convention@1`, `workforce_only@1`, Venue publication, Applications, and
Workforce behavior remain unchanged.

## Known risks and incomplete work

- Current profile policy is not yet exact-version pinned across every consumer;
  activation must wait for the successor enforcement issue.
- Programme and Scheduling do not yet exist as executable module namespaces.
- A separately approved operator authority version and guided setup are needed;
  the immutable Workforce operator role must not be widened in place.
- The Applications host starter/adapter, purpose-scoped personal timetable,
  Venue publication reconciliation, staffing adapter, accessible timetable
  editor, atomic release, on-site continuity, export, and recovery acceptance
  remain ordered successor children.
- Production use remains prohibited until deployment, privacy, security,
  retention, accessibility, performance, restore/PITR, continuity, training,
  and partner-acceptance gates pass.

## Recommended next actions

1. Implement exact-version manifest enforcement and profile-safe projections.
2. Add the atomic guided Programme Operations setup and independently reviewed
   operator authority version with migration/readiness/recovery evidence.
3. Continue umbrella #48 one protected child at a time through the Programme,
   review, Scheduling, editor, staffing, release, on-site, and integrated
   acceptance outcomes.
