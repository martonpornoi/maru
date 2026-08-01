# Checkpoint: Edition workspace spine implemented

- Date: 2026-08-01
- Phase: Production consolidation M1, locally verified
- Branch: `codex/production-consolidation`
- Related requirements: UX-009, UX-013, UX-019 through UX-023, EVT-001 through
  EVT-005, AUD-001, AUD-003, INT-001, NFR-001 through NFR-004, NFR-008,
  NFR-009
- Related ADRs: 0002, 0003, 0005, 0008, 0021, 0030 through 0038

## Outcome

Maru's controlled browser now forms one executable organization → convention
series → event edition journey. Pages 5–7 provide a versioned series record,
idempotent edition creation, edition record/profile, bounded activity, and
explicit working-context selection inside the same responsive administration
shell as Pages 1–4.

The first account remains an external platform administrator. Creating or
editing these records creates no membership, representation, capability grant,
participation, registration, application, department, position, shift, venue,
or workforce record.

This is an implementation/recovery checkpoint, not a release or production-
readiness statement. Repository, migration, generated-client, and visual smoke
evidence passed; owner rehearsal and external release gates remain.

## Decisions

- Convention series retain a profile-specific optimistic version because their
  current command changes only the recurring-brand profile.
- Event editions use one aggregate version across profile and lifecycle
  commands so those writers cannot overwrite each other. Lifecycle history
  keeps its own sequence.
- HTML and API mutations share organization/series/edition application
  services, transactions, audit, domain events, and outbox.
- Browser edition creation preserves a hidden UUID retry key. The API requires
  a UUID `Idempotency-Key` request header and rejects an `idempotency_key` JSON
  property.
- Pages 2–7 use closed input contracts and reject undeclared fields.
- Pages 5 and 7 show record history from allowlisted domain facts, never by
  reinterpreting security audit as a user activity feed.
- UX-020 is only provisional: current headers state truthful platform oversight
  and non-participation. Computed organization/department/person access and
  **Manage access** remain M2.

ADR 0038 records the safe delivery split discovered during implementation:
this M1 record spine precedes M2 representation, department/resource scope,
and computed access. It clarifies rather than reverses ADR 0037 and preserves
the accepted audit, authorization, outbox, working-context, and
non-participating-platform boundaries.

## Changed areas

- `maru.organizations`: series profile version, integrity trigger, update
  service/event, strict scoped GET/PUT API, and Page 5.
- `maru.events`: aggregate version, bounded date span, append-only creation
  receipt, integrity triggers, shared create/update services and events, strict
  POST/PUT API, Pages 6–7, and explicit session context actions.
- `maru.authorization`: `events.create` and `events.change_profile` capabilities
  with minimized mutation-response field ceilings.
- `maru.effects` and `maru.identity`: public bounded fact and actor-label
  queries.
- `maru.activity`: value-minimized aggregate record-history projection.
- `maru.core`: strict form/API inputs, progressive navigation, shared access/
  activity components, and responsive Page 5–7 templates.
- Product contracts, module documentation, setup, roadmap/capability ledger,
  migration/recovery runbook, and hands-on tutorial.

Generated `openapi.yaml` and TypeScript schema types are updated and regenerate
deterministically from the implemented API.

## Verification recorded at this checkpoint

- Complete PostgreSQL suite: 666 passed with one known Django 6 URL-scheme
  transition warning.
- Coverage: 90.17 percent, meeting the 90-percent repository gate.
- Late hardening suites: 103 API/query/serializer tests and 41
  workforce/authorization/edition tests passed.
- Page 4 publication-failure suite: 24 passed.
- Migration/integrity-focused tests: 15 passed.
- Activity-query-focused tests: 3 passed.
- Ruff format/lint, strict mypy across 191 source files, Django system check,
  migration-drift check, production-shaped `check --deploy`, and
  `git diff --check`: passed.
- A local upgrade rehearsal first exposed an archived-edition trigger/backfill
  ordering failure; events `0006` was corrected. Upgrades then succeeded on
  both the default `maru` database and the empty `maru_rebuild_empty` database.
- OpenAPI generation and validation passed; a second generation left
  `openapi.yaml` and the generated TypeScript schema byte-for-byte stable.
- Staff Console type checking, 20 Vitest tests, and its production build passed.
- `python scripts/validate_docs.py`: passed for 152 Markdown files and 195
  unique requirement identifiers.
- The current Pages 5–7 journey was exercised live, including creating a Draft
  edition and selecting/clearing its context. Desktop at 1280 pixels and narrow
  layout after reload at 390 pixels were coherent, with no horizontal overflow.
  Static focus order was reviewed and Pages 1–7 now expose a skip link.
- Automated axe analysis was unavailable, keypress automation did not reliably
  prove a complete keyboard traversal, and not every blocked/error/stale state
  received visual evidence. Those remain explicit release gates.

## Data, migration, and deployment notes

Organizations `0005`–`0007` add and guard series profile versions and fence
destructive downgrade while a series exists. Events `0006`–`0009` add/backfill
edition aggregate versions, add creation receipts and the 31-day constraint,
guard stable scope/slug, separate command types, version movement, editable
lifecycle, receipt scope/immutability, and lowercase SHA-256 request digests,
and fence destructive downgrade while an edition or receipt exists.

Deployment requires a maintenance window with every old writer stopped. The
events migration aborts if historical editions exceed 31 days; such rows need
an approved data-recovery correction, never silent truncation. It also aborts
when historical language/currency collections exceed their new bounds or a
currency is outside the pinned ISO allowlist. After any new
M1 write, old code and migration reversal are unsafe because they discard or
misunderstand canonical version/receipt semantics. Keep compatible code and
fix forward. See
`docs/operations/edition-workspace-migration-and-recovery.md`.

No production data was added by this checkpoint. Tests and tutorial examples
use synthetic values.

## Known risks and incomplete work

- Owner rehearsal, automated accessibility analysis, reliable keyboard
  traversal, and visual blocked/error/stale-state coverage remain incomplete.
- The current access summary is static and platform-only; it must not be
  presented as full effective access.
- M2 organization representation, activation, department/resource scope,
  invitations, hierarchy, and cross-domain Activity remain absent.
- Programme, venue, timetable, applications, logistics, documents, and live
  communications remain later milestones.
- All external infrastructure, recovery, load, accessibility, security, and
  partner governance gates remain mandatory before production personal data.

## Recommended next actions

1. Rehearse `docs/operations/maru-hands-on-tutorial.md` with the product owner
   and record any usability findings.
2. Complete automated accessibility, reliable keyboard, and remaining visual
   state evidence before making a release claim.
3. Begin M2 with organization representation/activation and authorization
   scope v2 before mounting department-owned mutations.
