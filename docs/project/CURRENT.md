# Current project state

Last updated: 2026-08-01
Phase: Production consolidation M2.2 authorization scope v2 locally verified;
M2.3 exact authority-provenance hardening next
Branch: `codex/full-platform-consolidation`

## Current outcome

ADR 0037 replaced isolated-page pauses with complete executable journeys while
keeping every page contract, permission boundary, and responsive evidence
requirement. Commits `4f6cbcb` and `17b68a2` record the branch census, M0
strategy, and locally verified M1 edition spine.

ADR 0039 supersedes ADR 0030's default minimal URL configuration and clarifies
ADR 0037's single-shell decision. `maru.urls` now provides one record-oriented
`/admin/` shell using Maru's logo and the stronger pre-reset visual grammar.
Backend route, authorization, migration-drift, frontend build, deploy-shaped,
OpenAPI determinism, populated/fresh migration, local restore-drill, and
desktop/390-pixel browser smoke gates pass. The current consolidated local
backend invocation passes 876 tests in 458.05 seconds with 90.43 percent
branch coverage and no warnings. Accessibility, complete denied/error-state,
representative recovery/PITR, and owner-rehearsal gates remain.

ADR 0040 supersedes the broad ADR 0024 ceremony as the normal way to establish
first organization authority. It defines Page 8's purpose-built Executive Board
root, exact existing verified-account invitations, invitee-owned versioned
responses, at least two distinct cross-approving controllers, and one atomic
Draft-to-Active activation. The platform administrator remains actor only and
never becomes a convention subject. The working tree contains the additive
schema, commands, HTML routes, database constraints, synthetic-fixture
handoff, and core security tests. Organizations `0009`–`0011` enforce exact
governance provenance and global emergency containment. Organizations `0012`,
participation `0004`, registration `0031`, and workforce `0003` enforce
IDN-011 at the database boundary. The populated local database and demo were
reconciled through the real services; fresh tests, local restore evidence, and
bounded Page 8 read/deny audit pass. Representative recovery/PITR,
accessibility, complete visual-state, and owner evidence remain.

ADR 0041 now implements exact department and typed-resource scope without
implicit department-tree inheritance. Sealed database-resolved targets,
append-only grant and role issuance, one-way evidence-complete revocation,
bounded delegation, exact Position bindings, and the ordered authorization
`0004` → workforce `0004` → authorization `0005` integrity path are present.
The privacy-minimized readiness command separates migration-data readiness
from production readiness; production remains blocked until exact actor and
approver authority-source provenance is designed and stored. ADR 0042 makes every
repository-controlled fixture synthetic and deletes the public-roster
rehearsal implementation while retaining a fail-closed compatibility command.
ADR 0043 adds platform-only emergency containment across every organization of
one compromised controller; it is not routine Board-term management.

The canonical management routes are:

- `/admin/` — permission-filtered administration home and shared shell;
- `/admin/workspace/` — API-backed Convention work embedded in that shell;
- `/admin/platform/organizations/` — Page 1 platform organization inventory;
- `/admin/platform/organizations/new/` — Page 2 complete optional Draft
  creation;
- `/admin/platform/organizations/<organization-slug>/` — Page 3
  record/profile and protected empty-Draft deletion;
- `/admin/platform/organizations/<organization-slug>/representation/` — Page 8
  Representation & access, with separate POST-only provisioning, invitation,
  self-response, and activation actions;
- `/admin/platform/organizations/<organization-slug>/series/new/` — Page 4
  series creation;
- `/admin/platform/organizations/<organization-slug>/series/<series-slug>/` —
  Page 5 series record/profile, activity, and edition inventory;
- `/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/new/`
  — Page 6 edition creation; and
- `/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/`
  — Page 7 edition record/profile/activity, with separate POST-only `select/`
  and `clear/` working-context actions.

The reserved `platform` route segment keeps purpose-built platform pages from
colliding with Django application-label routes such as specialist
`/admin/organizations/...` records. Explicit platform routes must resolve
before `admin.site.urls`. The former Page 1–7 paths are not canonical and no
compatibility redirect is assumed.

Navigation progressively reveals only the selected organization, series, and
edition. The shell has one collapsible sidebar for platform pages,
Convention work, and permission-filtered specialist records; embedded pages do
not add a second global menu or workspace selector. Unmounted domains do not
appear as placeholders. The same Maru logo, record-oriented modules, form
language, viewport-aligned sidebar, and stacked narrow layout continue across
Pages 1–8. Current desktop and 390-pixel smoke evidence covers Pages 3, 7, 8,
Convention work, platform administration, and a scoped non-staff Board
controller without horizontal overflow or browser console warnings.
The custom sidebar preserves Django `nav_sidebar.js`'s `#nav-filter` contract:
it renders exactly one filter and keeps it hidden when no Specialist records
are available. The `/admin/logout/` and `/admin/password_change/` controls
resolve to their real account handlers before Django AdminSite's staff-only
wrapper, so scoped non-staff accounts retain self-service without gaining
Specialist record access. The focused unified-routing regression passes nine
tests. In live browser evidence, a Board controller's logout reached
`/accounts/login/`, removed the logged-in banner, and produced zero new console
warnings or errors. A platform-administrator reload showed one searchable
`#nav-filter`, Specialist records and Platform administration exactly once
each, the correct `demo.admin` account, and zero new console warnings or errors.

Every active account may enter the Maru shell. Active scoped non-staff accounts
see only current organization/edition work derived from effective grants or
role assignments, plus their own open governance invitations. Specialist model
records remain separately protected by Django staff/model permissions. The
edition selector shows platform administrators all editions and ordinary
accounts only current authorized scope; invalid delegation ancestry, future,
expired, revoked, foreign, and stale selections are excluded.

Pages 1–2 remain active-platform-administrator setup. Pages 3–7 use exact
organization/edition capabilities, with backend coverage for scoped Board
controllers. Page 8 defines bounded access for platform oversight, an exact organization-scoped
representation manager, and an invitee's own open appointment. The platform account remains
ineligible as organization member, representation holder, participant,
registrant, volunteer, onboarding subject, or workforce assignee. The current
Pages 3–8 authority explanation is only the first M2 slice, not computed
department/resource/field access or the
complete **Manage access** workflow.

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

## M2.1 representation implementation and residual scope

Page 8 is contracted at
`/admin/platform/organizations/<organization-slug>/representation/`. Its four
closed forms accept only a 1–240 character reason; exact account email plus
reason; positive expected invitation version plus `accept|decline`; or positive
representation version, exact case-sensitive organization name, and reason.
Every scope, actor, role, state, lifecycle, timestamp, and evidence identifier
is server-owned.

The implemented initial lifecycle is `absent -> Provisioning -> Active` for the
fixed representation and `Invited -> Accepted -> Active` or `Declined` for an
appointment. Invitation grants no capability. Activation rechecks every
controller under locks, requires at least two distinct accepted eligible people
and no open invitation, creates the reserved immutable root-role version and
non-self cross-approved organization assignments, and activates memberships,
appointments, representation, and organization together. Successful changes
use minimized security audit plus
`organizations.representation.changed.v1`/transactional outbox evidence.

The additive migrations, database constraints, tenant/principal non-disclosure,
strict forms, replay/stale behavior, cross-approval, rollback, platform
exclusion, synthetic demo handoff, bounded sensitive-read/denial audit, and
100-row directory ceiling have backend evidence. The populated upgrade through
organizations `0012` and the other IDN-011 module guards, focused fresh
migration tests, the populated local restore drill through `0009`, and
responsive smoke pass. Fifty-eight combined representation/migration/readiness
tests, five emergency-focused tests, and a 71-test adjacent IDN-011 batch pass.
The current readiness/core focus passes 10 tests and the representation/
platform matrix passes 126 tests, including the readiness-parity and
concurrency hardening used by the final consolidated run.

The emergency path may end open terms globally, revoke sessions and root
authority, deactivate the person, and suspend a Board that loses quorum.
Routine expiry, replacement, voluntary ending, planned suspension/reactivation,
quorum recovery, invitation delivery, implemented department/resource scope,
and complete effective access remain later M2 work. Invitees can discover their
own open appointments at `/admin/invitations/`.

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

The former `GET|POST /api/v1/management/convention-bootstrap` operation and
its Quick Start/browser ceremony are not mounted or present in the current
OpenAPI/client. Only the operator `bootstrap_convention` command and underlying
service remain recovery evidence for an approved legacy reconciliation.

## Decisions and documentation

- ADR 0037 remains the governing production-consolidation decision. ADR 0038
  records the safe split between the completed M1 record spine and M2
  governance/scoped access. ADR 0039 replaces ADR 0030's default minimal shell
  with the unified `/admin/` shell and reserved `/admin/platform/` route space.
  ADR 0040 defines the explicit first Executive Board lifecycle and supersedes
  ADR 0024's broad ceremony as the normal authority path. ADR 0041 defines
  exact department/resource scope v2. ADR 0042 makes educational fixtures
  synthetic-only. ADR 0043 defines global emergency controller containment.
- `docs/project/PRODUCTION_CONSOLIDATION.md` is the crash-safe capability ledger
  and milestone checklist.
- `docs/checkpoints/2026-08-01-unified-admin-shell-migration-start.md` is the
  append-only M1.1 start checkpoint; it is not a completion record.
- `docs/checkpoints/2026-08-01-m2-representation-lifecycle-start.md` is the
  append-only M2.1 contract/start checkpoint; it records no runtime
  verification.
- `docs/checkpoints/2026-08-01-unified-shell-and-representation-backend-verified.md`
  records the consolidated backend/frontend evidence plus the later local
  migration, browser, coverage, deploy, and OpenAPI gates; representative
  recovery/PITR, accessibility, complete visual states, and owner rehearsal
  remain open.
- `docs/checkpoints/2026-08-01-idn011-database-subject-boundary.md` records the
  database-level non-participating platform invariant and focused evidence.
- `docs/checkpoints/2026-08-01-m21-integrity-recovery-and-subject-boundary.md`
  records the consolidated local migration, restore, audit, fixture, final
  backend/coverage evidence, and residual external release boundary.
- Page contracts 05–07 define the M1 behavior and explicit field tables;
  contract 08 defines the backend-verified initial representation handoff, and contracts
  02–04 document closed HTML input.
- The module index includes Activity and updated organization/events/effects/
  identity/core/authorization/audit boundaries.
- The hands-on tutorial covers the implemented organization → representation
  → series → edition exercise with synthetic accounts and explicitly retains
  the owner-led rehearsal gate.
- The edition, Executive Board, and IDN-011 migration/recovery runbooks require
  a maintenance window, compatible writers, and fix-forward recovery.

## Verification status

The committed M1 edition spine was locally verified, but those results predate
the active default-shell and route migration. They remain evidence for the
domain and Page 5–7 implementation, not a production-readiness statement and
not verification of ADR 0039:

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

Historical shell/initial-representation evidence for ADRs 0039 and 0040 is:

- the 709-test backend run completed with one stale administration-home
  assertion; after restoring **Manage access**, that exact assertion passed;
- a focused 147-test route/Page 8 batch initially exposed two stale
  presentation expectations, and both exact tests passed after correction;
- focused tests cover route collisions, anonymous/inactive/platform/scoped-
  nonstaff/staff separation, specialist-record gating, edition-selector scope,
  Pages 3–8 Board authority, own invitations, two-controller activation,
  platform exclusion, strict input, stale/replay behavior, database constraints,
  and atomic rollback;
- Ruff, mypy, Django system check, and migration-drift checks pass;
- Staff Console type checking, 19 Vitest tests, and production build pass; and
- the current OpenAPI/client no longer exposes the retired convention-bootstrap
  management API.
- the pre-hardening isolated complete backend invocation passed 710 tests; four later
  representation-boundary tests passed in their 21-test focused file and moved
  exact branch coverage from 89.98 to 90.03 percent, above the 90-percent gate;
- the deploy-shaped Django check, migration-drift check, and deterministic
  OpenAPI validation pass; and
- the populated local database applied organizations `0008`, reconciled two
  synthetic Executive Boards, reset all 80 synthetic account passwords, and
  then produced an idempotent second seed with no creations or password resets.

Current post-hardening evidence is:

- the final consolidated backend invocation passes 792 tests in 329.21
  seconds, reaches 90.01 percent coverage, and emits no warnings;
- a separate behavior run passes the same 792 tests in 291.86 seconds;
- the ordered migration-contamination regression passes 26 tests;
- 24 focused HTTPS tests pass with warnings promoted to errors;
- the focused readiness/core invocation passes 10 tests;
- the focused representation/platform matrix passes 126 tests;
- the focused unified-routing regression passes 9 tests, including scoped
  non-staff account-control routing ahead of AdminSite's staff-only wrapper;
- 58 combined representation/migration/readiness tests and five focused
  emergency-containment tests pass;
- 71 adjacent IDN-011 organization/participation/registration/workforce tests
  pass, including database-bypass and concurrent reclassification boundaries;
- organizations `0009`–`0012`, participation `0004`, registration `0031`, and
  workforce `0003` apply to the populated local database;
- the fresh `maru_consolidated_demo` database applies all 106 migrations,
  contains 80 synthetic accounts, two organizations, and six editions, and
  reports readiness 16/16 with zero blockers;
- the current restore drill into `maru_restore_drill_m21` passes and the drill
  database is removed afterward;
- Page 8 manager reads and privileged denials append value-minimized evidence,
  filter tenant scope before ordering, cap the directory at 100 rows, and fail
  closed if read-audit persistence fails; and
- `pip-audit` and the production `pnpm audit` report no known dependency
  vulnerabilities;
- the production-shaped deploy check is clean; and
- documentation validation passes for 165 Markdown files and 195 unique
  requirement identifiers.

Current scope-v2 evidence is:

- 157 initial focused migration, database-integrity, exact-policy, authority-command,
  live resource-binding, readiness, representation, platform-boundary, and
  workforce tests pass on an isolated PostgreSQL database;
- the migration suite covers additive schema, reproducible Position backfill,
  reverse behavior before scoped writes, the durable first-write downgrade
  fence, raw/bulk bypass attempts, hierarchy/reporting cycles, and exact
  position-assignment evidence;
- `ensure_workforce_position_binding` locks and re-reads every Position created
  through the specialist record or preserved bootstrap, then establishes the
  same deterministic immutable binding used by migration backfill; and
- a 57-test ordered historical-migration matrix restores authorization `0005`,
  workforce `0004`, and organizations `0012` before current-model use;
- 44 additional fail-closed runtime tests cover binding lifecycle, malformed
  scope evidence, target tampering, delegation ancestry, stale target locks,
  transactional rechecks, and readiness catalog categories;
- the definitive repository-wide run passes all 876 tests in 458.05 seconds,
  reaches 90.43 percent branch coverage, and emits no warnings; and
- Ruff formatting/lint, strict mypy across 199 source files, Django local and
  deploy-shaped checks, migration drift, documentation validation for 167
  Markdown files/195 requirement identifiers, OpenAPI validation and generated
  client stability, Staff Console typecheck/19 tests/production build, and
  whitespace checks pass.

The populated synthetic `maru_consolidated_demo` database applied
authorization `0004`, workforce `0004`, and authorization `0005` in dependency
order. Both scope-v2 and representation readiness report zero blockers;
scope-v2 reports `status: ready` and truthfully retains `production_status:
blocked` for authority-source provenance. Current migration leaves, system
check, and drift check pass. Live browser smoke then verified the platform
administrator shell, an ordinary Board controller's organization and
representation access, exact foreign-organization 403 denial, and no desktop
horizontal overflow. The platform administrator session is left open at
`/admin/` for continued review.

Historical-migration test modules now use a shared finalizer that migrates
every Django app back to the migration graph's current on-disk leaf in a
`finally` path. A regression starts from the historical workspace target and
asserts that all current leaves and the IDN-011 subject triggers are restored,
preventing ordered tests from contaminating the final suite schema.

Desktop and 390-pixel in-app browser smoke passed for the unified shell,
organization record, representation page, edition record, and Convention work.
The smoke also exercised an ordinary Board controller: scoped pages were
editable, foreign/specialist records were absent, and the platform account was
kept outside every convention relationship. No horizontal overflow or browser
console warnings were observed. A final Board-admin reload additionally showed
exactly one hidden `#nav-filter` and no Specialist records; its logout reached
`/accounts/login/`, removed the logged-in banner, and produced no new console
warning or error. A final platform-administrator reload showed one searchable
`#nav-filter`, Specialist records and Platform administration exactly once
each, the correct `demo.admin` account, and no new console warning or error.
Representative deployment/PITR and full fix-forward rehearsal,
keyboard/automated accessibility, complete error/denied/stale visual states,
and owner tutorial rehearsal remain open.

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

Organizations `0008` adds representation records; `0009`–`0011` add immutable
governance provenance, exact active-authority validation, platform-principal
guards, emergency containment, and downgrade fences. Organizations `0012`,
participation `0004`, registration `0031`, and workforce `0003` install IDN-011
subject guards that lock identity rows and reject later platform
reclassification at commit while a convention relationship remains.

These are stopped-writer migrations. The privacy-minimized readiness command
must report zero blockers, and each module's count-only preflight must pass.
They create no inferred controller, replacement person, or deletion. After the
first governed write, do not run an old writer or reverse only part of the
authority/subject boundary; fix forward with compatible code or restore the
whole database to a mutually consistent point. Failed activation or emergency
containment must leave no partial membership, role, session, identity,
representation, organization-lifecycle, audit, event, or outbox change. The
local evidence is not representative deployment backup/PITR certification.

Authorization `0004`, workforce `0004`, and authorization `0005` are a second
stopped-writer sequence. The count-only `check_scope_v2_readiness` preflight
must report zero migration blockers. The sequence preserves broad historical
grants, installs exact containment and immutable issuance/revocation guards,
backfills deterministic Position bindings, and records a durable fence after
the first scoped write. Once fenced, use compatible writers and fix forward or
restore the entire database to one pre-write recovery point; do not reverse an
individual module. The complete operator procedure is in
`docs/operations/authorization-scope-v2-migration-and-recovery.md`.

## Known limits and production gates

- The unified shell is implemented and backend-tested; current desktop/
  responsive browser smoke, deploy-shaped settings, and local migration/
  restore evidence pass. The current consolidated local backend gate passes 876
  tests with 90.43 percent branch coverage and no warnings. Automated accessibility
  and complete visual-state coverage remain incomplete.
- Owner tutorial rehearsal is unfinished.
- Executive Board provisioning, exact invitation, self-response, initial
  activation, bounded read/denial audit, database subject guards, and emergency
  containment are implemented and focused-tested. The focused readiness/core
  and representation/platform matrices pass. Representative restore/PITR,
  accessibility, complete visual states, and owner rehearsal are open. Routine
  expiry, replacement, ending, planned suspension/reactivation, invitation
  delivery, authority-source provenance, and complete effective-access
  explanations remain later M2. Exact department/resource scope exists below
  the UI, but a contextual editor and computed explanation are not mounted.
- Programme, typed applications, venues/mergeable spaces, three-phase
  timetable/layers, shifts, storage/logistics, governed documents, and team/
  on-site communications remain absent current modules.
- Registration, workforce, accreditation, communications, privacy, and other
  substantial backend capabilities remain preserved, remounting, partial, or
  API-only; route reachability and passing backend tests do not make their
  browser journeys current.
- Payment provider, SMTP, object storage/malware scanning, worker supervision,
  telemetry/alerts, secrets, printers/scanners, backup/PITR restore evidence,
  representative load, accessibility/security review, and partner legal/
  privacy/finance/safeguarding/operations approval remain external gates.
- Maru must not receive production personal data or be described as production-
  approved until repository and deployment/governance gates pass.

## Smallest sensible next actions

1. Record and implement exact actor/approver authority-source provenance for
   root grant and role issuance; keep production readiness blocked until it is
   queryable and enforced.
2. Add the Awoostria-shaped synthetic department template, mounted hierarchy/
   position workflow, and computed effective-access explanation on top of the
   exact scope boundary.
3. Rehearse every current migration against a representative restored database
   with reserved-role/non-Draft preflight, full fix-forward, and backup/PITR
   evidence.
4. Run automated accessibility, reliable keyboard traversal, and the complete
   blocked/error/stale-state matrix before owner rehearsal.
5. Deliver the next differentiating vertical: panel application → accepted
   private programme item → reusable/mergeable venue selection → three-phase
   layered timetable → immutable release/API projection.

## Resume instructions

Read `AGENTS.md`, this file, `PRODUCTION_CONSOLIDATION.md`, ADRs 0037–0043, the
Page 1–8 contracts, `docs/modules/core.md`, `docs/modules/staff-console.md`,
`docs/modules/activity.md`, organization/events/authorization/audit/effects
module docs, and the M1 migration runbook. Run `git status --short --branch`
and continue with the first unchecked M2 provenance/hierarchy item. Do not treat backend
evidence as proof
of browser or deployment readiness. Preserve
concurrent changes and the non-participating platform boundary.

Do not trust selected-edition state or route placement as authority; do not let
purpose-built platform routes collide with or fall through to Django app-label
resolution; create a second global menu; expose Django Groups as a second role system;
accept undeclared input; put the API idempotency key in JSON; show raw UUIDs as
primary labels; use audit as a universal user activity feed; mutate edition
profile and lifecycle together; bypass aggregate versions or database guards;
reverse M1 after new writes; or mount aspirational domains as placeholders.
Do not remount Quick Start or
`/api/v1/management/convention-bootstrap`; the operator command/service are
recovery evidence only.
Do not restore `seed_marucon_rehearsal` or its removed public-roster scenario;
all repository fixtures, screenshots, and tutorials must remain synthetic.
For Page 8, do not infer a controller, reveal candidate accounts, accept on
another person's behalf, allow self-approval, activate with a pending
invitation or stale aggregate version, reuse the reserved root bundle, or
reverse representation tables after authority evidence exists. Do not use the
emergency containment command as routine term management or leave a one-person
Board active after quorum loss.
