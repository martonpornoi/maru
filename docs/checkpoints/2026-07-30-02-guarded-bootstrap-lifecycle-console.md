# Guarded first-authority and edition lifecycle console

- Date: 2026-07-30
- Phase: Unified Management Console implemented; partner deployment readiness
  remains next
- Related requirements: IDN-004, IDN-005, EVT-004, AUD-001, UX-001, UX-003,
  UX-005 through UX-008, UX-011, UX-012, NFR-001 through NFR-003
- Related ADRs: ADR 0022, ADR 0023, ADR 0024

## Outcome

An eligible workspace-less superuser can now establish the first accountable
convention leadership through `/manage/` without using PowerShell. The
successful ceremony refreshes the newly created workspace and takes the
controller to the Setup guide, where an authorized organizer can move the
edition from Draft to Preparing and through later valid lifecycle states.

The existing `bootstrap_convention` command remains available as an operator
and recovery fallback. The former persistent Django-admin bootstrap form was
not restored.

## Decisions

ADR 0024 partially supersedes ADR 0022's command-only first-authority
experience. Initial authority is a purpose-built, one-time Management Console
ceremony rather than an editable authority record.

The ceremony is active-superuser-only and requires a matching eligible
organization and non-closed edition, a distinct active Chair account, a
permanent reason, exact organizer-slug confirmation, and the current
controller password. Account-directory reads and denied attempts are audited;
the shared bootstrap service remains atomic, audited, and fail-closed on
repetition.

Edition lifecycle controls remain capability-derived and call the existing
locked transition service. Every transition requires a reason. Cancellation
and archival require an additional terminal-action acknowledgement.
Registration activation and sales windows remain separate decisions.

## Changed areas

- Added the versioned convention-bootstrap workspace and creation API.
- Added first-authority eligibility and edition-transition capability to the
  authenticated context projection.
- Reused and concurrency-hardened the existing workforce bootstrap service.
- Added responsive Quick Start, completion, and lifecycle panels to the
  Management Console.
- Regenerated OpenAPI, TypeScript schema, and production console assets.
- Updated setup, onboarding, workforce, events, console, requirements,
  architecture, roadmap, and current-state documentation.

## Verification

- `pytest --cov=maru --cov-report=term-missing`: 408 passed; 90.06% branch-aware
  coverage.
- Ruff format/lint and strict mypy: pass for 174 source files.
- Django system, production-shaped deployment, and migration-drift checks:
  pass.
- OpenAPI 3.1 generation/validation and generated TypeScript types: pass.
- Management Console: 18 tests, TypeScript typecheck, and Vite production
  build pass.
- Documentation validation: 105 Markdown files and 184 unique requirement
  identifiers.
- Browser QA at desktop and 390-pixel responsive width confirmed the eligible
  Quick Start against the clean walkthrough database. No horizontal overflow
  or runtime console error was present.
- No schema migration is required.

## Data, migration, and deployment notes

The browser QA deliberately did not submit the live ceremony. The local
walkthrough database therefore still has no convention authority and remains
ready for the maintainer to test the workflow. No database schema changed.

The ceremony does not make the local identity path production-approved.
Production still needs the independent identity, infrastructure, policy,
provider, load, and partner gates recorded in `docs/project/CURRENT.md`.

## Known risks and incomplete work

The platform has no concrete production payment provider, infrastructure
certification, partner approval, or badge layout/batch-printing workflow.
First-authority password confirmation is appropriate for the current owned
identity path, but a future external identity provider needs a deliberate
step-up-authentication design.

## Recommended next actions

1. Complete the browser ceremony using the clean convention onboarding
   walkthrough and confirm the Draft-to-Preparing transition.
2. Continue the walkthrough through registration, assisted volunteer intake,
   NDA/media review, position activation, and privilege verification.
3. Select the first partner and complete the production gates listed in
   `docs/project/CURRENT.md`.
