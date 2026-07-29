# Checkpoint: Project foundation

- Date: 2026-07-26
- Phase: Product and architecture foundation
- Related requirements: All baseline requirements
- Related ADRs: ADR 0001, ADR 0002

## Outcome

The empty repository now has a durable product and architecture contract for
Maru. The platform will use Python, Django, Django REST Framework, and
PostgreSQL as a modular monolith with separate clients.

The requirements explicitly cover multi-convention operation, event-edition
archives, historical participation, activity and audit, internal messaging,
external announcements, HR onboarding, scheduling, queries, exports, and a
task-oriented administration experience.

## Decisions

- Event editions are the project-like operational unit.
- Platform accounts do not give organizers implicit cross-tenant visibility.
- Historical participation is modeled explicitly and archived read-only by
  default.
- Django admin is a bootstrap tool, not the final staff console.
- External communication networks are delivery adapters, not sources of truth.
- Current-state and append-only checkpoints are mandatory project artifacts.

## Changed areas

- Root project introduction and working instructions
- Baseline product requirements
- Architecture overview and module map
- Two accepted ADRs
- Testing and documentation standards
- Roadmap and current handoff
- Checkpoint process

## Verification

The documentation was reviewed for consistent terminology, requirement
traceability, and relative-link structure. No application runtime exists yet.

## Data, migration, and deployment notes

No application data, migrations, dependencies, or deployments exist.

## Known risks and incomplete work

- Department workflows have not yet been validated with real operators.
- Identity, permission storage, providers, frontend, jobs, and offline
  protocols remain open decisions.
- The module map is deliberately broader than the initial implementation scope.

## Recommended next actions

1. Run structured workflow discovery.
2. Produce a data classification and retention matrix.
3. Produce a threat model and permission matrix.
4. Select and model the first registration vertical slice.
