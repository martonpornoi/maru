# Current project state

Last updated: 2026-08-01
Phase: Production consolidation M1; edition workspace spine implemented and
locally verified, owner rehearsal pending
Branch: `codex/production-consolidation`

## Current outcome

ADR 0037 replaced isolated-page pauses with complete executable journeys while
keeping every page contract, permission boundary, and responsive evidence
requirement. Commit `4f6cbcb` records the branch census and M0 strategy. The
current working tree implements M1 Pages 5–7 on top of accepted Pages 1–4.

The default `maru.baseline_urls` browser now mounts:

- `/accounts/login/` and POST-only `/accounts/logout/`;
- `/admin/` — Page 1 platform organization inventory;
- `/admin/organizations/new/` — Page 2 complete optional Draft creation;
- `/admin/organizations/<organization-slug>/` — Page 3 record/profile and
  protected empty-Draft deletion;
- `/admin/organizations/<organization-slug>/series/new/` — Page 4 series
  creation;
- `/admin/organizations/<organization-slug>/series/<series-slug>/` — Page 5
  series record/profile, activity, and edition inventory;
- `/admin/organizations/<organization-slug>/series/<series-slug>/editions/new/`
  — Page 6 edition creation; and
- `/admin/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/`
  — Page 7 edition record/profile/activity, with separate POST-only `select/`
  and `clear/` working-context actions.

Navigation progressively reveals only the selected organization, series, and
edition. Unmounted domains do not appear as placeholders. The same Maru logo,
record-oriented modules, form language, viewport-aligned sidebar, and stacked
narrow layout continue across Pages 1–7.

Every mounted page currently requires an active platform administrator. That
account is attributed in evidence but remains ineligible as organization
member, representation holder, participant, registrant, volunteer, onboarding
subject, or workforce assignee. The access summary truthfully labels this as
platform oversight. It is a static/provisional UX-020 slice: computed Executive
Board/department/person access and **Manage access** remain M2.

## M1 behavior

### Convention series

Page 5 and the new scoped series GET/PUT APIs maintain the complete recurring-
brand profile. Changed saves lock the exact organization-owned series, compare
`profile_version`, write actual fields only, advance the version once, and
commit minimized audit plus registered domain event/outbox evidence. Unchanged
saves advance nothing. PostgreSQL keeps organization/slug stable and enforces
version movement.

### Event editions

Pages 6–7 and the edition POST/PUT APIs share application services. Creation
requires exact organization/series scope, an Active series beneath a non-
Closed organization, bounded name/dates/IANA zone/languages/ISO currencies,
and a UUID retry key. The browser preserves a hidden key; API clients use the
required `Idempotency-Key` request header, not a JSON property. A same-payload
retry reuses the first edition; changed-payload reuse conflicts.

Creation atomically writes one Draft edition, append-only scoped receipt,
value-minimized audit event, `events.edition.created.v1`, and outbox delivery.
It creates no registration configuration, application, programme item, venue,
department, shift, access grant, or people relationship.

Every EventEdition profile or lifecycle change uses one `aggregate_version`.
Draft/Preparing profile updates and lifecycle transitions are separate commands
and each changed command advances it exactly once. PostgreSQL prevents stable-scope/
slug mutation, combined profile/lifecycle writes, version skips, profile edits
outside Draft/Preparing, over-31-day ranges, and receipt mutation/scope
mismatch. `lifecycle_version` remains the separate transition-history sequence.

Edition creation redirects to Page 7 but does not silently select it. Explicit
session selection is display/query context only and grants no authority.

### Strict inputs and activity

Pages 2–7 reject every undeclared input rather than ignoring forged scope,
slug, lifecycle, version, actor, or timestamp fields. APIs do the same for new
series/edition boundaries. The page contracts contain NFR-009 tables for type,
format, bounds, null/blank meaning, normalization, classification, writer,
lifecycle, retention, and error behavior.

Pages 5 and 7 render bounded, value-minimized record activity from allowlisted
domain facts and safe identity labels. They do not expose entered values,
emails, raw actor IDs, or security audit internals. This is record history, not
M2's future cross-domain access-aware Activity workspace.

## API and module state

New M1 API operations are:

- `GET /api/v1/organizations/{organization_id}/series`;
- `GET|PUT /api/v1/organizations/{organization_id}/series/{series_id}`;
- `POST /api/v1/organizations/{organization_id}/editions`; and
- `PUT /api/v1/organizations/{organization_id}/editions/{edition_id}` beside
  the existing edition GET/list/lifecycle endpoints.

HTML and API mutations call the same domain services. Edition mutation response
projections are bounded by capability field ceilings; the platform-only series
mutation uses its fixed documented serializer. RFC 9457-style failures use
stable codes and `application/problem+json`. OpenAPI validation and a
deterministic TypeScript client regeneration passed for the resulting schema.

`maru.activity` owns record-history presentation. It consumes public bounded
queries from `maru.effects` and `maru.identity` rather than importing their
private model implementations. `AuditEvent` remains separate control evidence.

## Decisions and documentation

- ADR 0037 remains the governing production-consolidation decision. ADR 0038
  records the safe split between the completed M1 record spine and M2
  governance/scoped access; it does not change ADR 0037's intended outcome.
- `docs/project/PRODUCTION_CONSOLIDATION.md` is the crash-safe capability ledger
  and milestone checklist.
- Page contracts 05–07 define the mounted behavior and explicit field tables;
  contracts 02–04 now document closed HTML input.
- The module index includes Activity and updated organization/events/effects/
  identity/core/authorization/audit boundaries.
- The hands-on tutorial covers the complete organization → series → edition
  exercise.
- The migration/recovery runbook requires a maintenance window and forward fix
  after any new M1 write.

## Verification status

M1 is locally verified but is not a production-readiness statement:

- the complete PostgreSQL suite passed: 666 tests, with one known Django 6
  URL-scheme transition warning;
- coverage passed the repository gate at 90.17 percent;
- Ruff formatting and lint, strict mypy across 191 source files, Django system
  check, migration-drift check, and `git diff --check` passed;
- production-shaped `check --deploy` passed with verification-only settings;
- OpenAPI generation/validation was deterministic, and generated TypeScript
  types remained byte-for-byte stable;
- Staff Console type checking, 20 Vitest tests, and the production Vite build
  passed;
- late hardening suites passed 103 API/query/serializer tests and 41
  workforce/authorization/edition tests; Page 4 passed 24 focused tests;
  migration/integrity passed 15; and activity queries passed 3;
- upgrades succeeded on both the existing local `maru` database and a fresh
  `maru_rebuild_empty` database after correcting the archived-row backfill
  order exposed by rehearsal;
- documentation validation passed for 152 Markdown files and 195 unique
  requirement identifiers; and
- the live Page 5–7 browser journey passed at a 1280-pixel desktop width and
  after reload at 390 pixels with no horizontal overflow. Static focus order
  was reviewed and a skip link is present on Pages 1–7.

Automated axe scanning was unavailable, browser automation could not reliably
prove a complete keyboard traversal, and not every blocked/error/stale state
was visually exercised. Those accessibility and state-matrix checks remain
release gates; they are not hidden behind the successful visual smoke.

## Migration and recovery boundary

Organizations `0005`–`0007` add series profile versions, their integrity
trigger, and a populated-workspace downgrade fence. Events `0006`–`0009`
add/backfill aggregate versions, add append-only creation receipts and the
31-day span/lowercase-digest constraints, install edition/receipt triggers, and
fence destructive downgrade while editions or receipts exist.

This is a maintenance-window deployment. Old writers do not advance the new
versions and are incompatible with the new guards. Preflight must find zero
historical editions longer than 31 days, oversized language/currency
collections, or unsupported pinned ISO currencies. Once any new M1 write
occurs, do not roll back to old code or reverse these migrations; retain
compatible code and fix forward. The complete procedure is in
`docs/operations/edition-workspace-migration-and-recovery.md`.

## Known limits and production gates

- Owner tutorial rehearsal is unfinished.
- Executive Board representation/activation, convention-owned access,
  department/resource scope, computed effective-access explanations, and
  invitations remain M2.
- Programme, typed applications, venues/mergeable spaces, three-phase
  timetable/layers, shifts, storage/logistics, governed documents, and team/
  on-site communications remain absent current modules.
- Registration, workforce, accreditation, communications, privacy, and other
  substantial backend capabilities remain preserved/unmounted or API-only;
  passing backend tests does not make their browser journeys current.
- Payment provider, SMTP, object storage/malware scanning, worker supervision,
  telemetry/alerts, secrets, printers/scanners, backup/PITR restore evidence,
  representative load, accessibility/security review, and partner legal/
  privacy/finance/safeguarding/operations approval remain external gates.
- Maru must not receive production personal data or be described as production-
  approved until repository and deployment/governance gates pass.

## Smallest sensible next actions

1. Ask the owner to rehearse the hands-on tutorial and record any usability
   findings without weakening the accepted boundaries.
2. Complete automated accessibility analysis, a reliable keyboard traversal,
   and the visual blocked/error/stale-state matrix before any release claim.
3. Start M2 with organization representation and the activation invariant,
   then Awoostria-shaped synthetic departments and authorization scope v2.
4. Replace the provisional access summary with computed effective access before
   mounting department-owned mutations.
5. Deliver the next differentiating vertical: panel application → accepted
   private programme item → reusable/mergeable venue selection → three-phase
   layered timetable → immutable release/API projection.

## Resume instructions

Read `AGENTS.md`, this file, `PRODUCTION_CONSOLIDATION.md`, ADRs 0037–0038, the Page
5–7 contracts, `docs/modules/activity.md`, organization/events/authorization/
audit/effects module docs, and the M1 migration runbook. Run
`git status --short --branch` and continue with owner rehearsal or M2. Preserve
user changes and the non-participating platform boundary.

Do not trust selected-edition state as authority; expose Django Groups as a
second role system; accept undeclared input; put the API idempotency key in JSON;
show raw UUIDs as primary labels; use audit as a universal user activity feed;
mutate edition profile and lifecycle together; bypass aggregate versions or
database guards; reverse M1 after new writes; or mount aspirational domains as
placeholders.
