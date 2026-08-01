# Unified shell and representation backend verification

- Date: 2026-08-01
- Branch: `codex/full-platform-consolidation`
- Requirements: IDN-002, IDN-004, IDN-005, IDN-009, IDN-011, IDN-012,
  UX-009, UX-012, UX-013, UX-019, UX-020, UX-024, AUD-001, AUD-005, NFR-001,
  NFR-002, NFR-003, NFR-008, NFR-009
- Decisions: ADRs 0031, 0037, 0038, 0039, 0040

## Outcome

The current working tree now has one default `/admin/` management shell and an
implemented initial Executive Board handoff:

- `maru.urls` is the default resolver;
- Pages 1–8 use collision-safe `/admin/platform/organizations/...` routes
  before `admin.site.urls` and share the Django administration shell;
- active scoped accounts may use authorized Maru pages and Convention work
  without Django `is_staff`, while specialist model records remain separately
  staff/model-permission gated;
- the edition selector includes every edition for a platform administrator and
  only current authorized scope for an ordinary account, rejecting invalid
  delegation ancestry, future, expired, revoked, foreign, and stale choices;
- Page 8 provisions one fixed Executive Board, invites exact existing verified
  people, lets each person answer only their own versioned appointment, and
  activates at least two cross-approving controllers with the Draft
  organization in one transaction;
- the platform administrator remains actor only and cannot become a convention
  subject; and
- `seed_demo_data` establishes two active synthetic controllers per demo
  organization by exercising the real representation services.

Organization, convention-series, membership, representation, and appointment
specialist records are inspection-only. Their purpose-built commands remain the
mutation boundary.

The former Quick Start/first-authority web ceremony and
`GET|POST /api/v1/management/convention-bootstrap` are not mounted and are
absent from the current OpenAPI/client. Only the `bootstrap_convention`
operator command and its underlying service remain recovery evidence for an
explicitly approved legacy reconciliation.

## Verification performed

- A 709-test backend run completed with one stale administration-home
  expectation. The exact test passed after the **Manage access** link was
  restored.
- A focused 147-test shell/Page 8 batch initially exposed two stale
  presentation expectations. Both exact tests passed after correction.
- Focused coverage includes route collisions, anonymous/inactive/platform/
  scoped-nonstaff/staff separation, specialist-record gating, selector scope,
  Board access to Pages 3–7, Page 8 platform/manager/self boundaries, strict
  input, stale/replay behavior, two-controller cross-approval, platform
  exclusion, PostgreSQL constraints, rollback, and unrelated-side-effect
  absence.
- Ruff, mypy, Django system check, and migration-drift checks passed.
- Staff Console type checking, 19 Vitest tests, and the production build passed.

These results are deliberately not described as a clean full-suite or release
result: the complete backend suite was not rerun in one invocation after the
corrected assertions, and no current coverage measurement was recorded.

## Open gates

- rerun the complete backend suite clean and record coverage;
- apply organizations migration `0008` to fresh and populated live rehearsal
  databases, inspect legacy non-Draft/reserved-role conflicts, and rehearse
  fix-forward recovery;
- complete sensitive appointment-directory read and privileged-denial audit
  coverage;
- run current desktop and 390-pixel browser journeys, error/denied/stale states,
  keyboard traversal, and automated accessibility analysis;
- rehearse the hands-on tutorial with the owner; and
- retain every external infrastructure, privacy, legal, security, load,
  accessibility, recovery, and go-live gate in the production ledger.

## Resume point

Start with the clean full-suite/coverage gate, then the live representation
migration rehearsal, then browser/accessibility evidence. Do not extend
governance into departments or ongoing Board-term mutation until these gates
are recorded. Do not infer people from real rosters or remount the retired
bootstrap web/API path.

## Additional verification recorded before checkpoint commit

The remaining local gates were advanced after the initial checkpoint text:

- an isolated complete backend invocation passed 710 tests in 220.71 seconds;
- four added representation-boundary cases passed inside the 21-test focused
  file, and combined exact branch coverage reached 90.03 percent against the
  90-percent repository gate;
- the deploy-shaped settings check, migration-drift check, and deterministic
  validated OpenAPI regeneration passed;
- organizations `0008` applied to the populated local database; the synthetic
  demo reconciled two active Executive Boards and reset 80 synthetic passwords,
  while its second run made no creations or password resets; and
- desktop and 390-pixel in-app browser smoke passed for the unified shell,
  Pages 3, 7, and 8, Convention work, and a scoped non-staff Board controller,
  with no horizontal overflow or console warnings.

Fresh restored-database/fix-forward rehearsal, complete sensitive-read and
denial audit, keyboard and automated accessibility testing, the full visual
error/denied/stale matrix, and owner tutorial rehearsal remain open. The next
code milestone is authorization scope v2; department-owned writes remain
blocked until that boundary is implemented and tested.

## Final local verification addendum

Later M2.1 hardening closes the local suite, clean-database, restore, deploy,
dependency, and scoped-sidebar items that were still open in the historical
sections above:

- the final consolidated backend invocation passes 792 tests in 329.21
  seconds with 90.01 percent coverage and no warnings;
- a separate behavior run passes the same 792 tests in 291.86 seconds;
- nine focused unified-routing tests pass after the custom sidebar preserved
  Django `nav_sidebar.js`'s required `#nav-filter` DOM contract and scoped
  non-staff logout/password-change routes were placed before AdminSite's
  staff-only wrapper;
- a live Board logout reaches `/accounts/login/`, removes the logged-in banner,
  and produces zero new console warnings or errors; the hidden `#nav-filter`
  fallback remains when no Specialist records are available;
- a live platform-administrator reload shows one searchable `#nav-filter`,
  Specialist records and Platform administration exactly once each, the
  correct `demo.admin` account, and zero new console warnings or errors;
- fresh database `maru_consolidated_demo` applies all 106 migrations and
  contains 80 synthetic accounts, two organizations, and six editions;
- its readiness result is 16/16 with zero blockers;
- the restore drill into `maru_restore_drill_m21` passes and cleanup removes
  the drill database;
- `pip-audit` and the production `pnpm audit` report no known vulnerabilities;
  and
- the production-shaped deploy check is clean.

This addendum supersedes only the earlier pending local evidence statements.
Representative deployment restore/PITR and full fix-forward evidence,
automated accessibility and keyboard traversal, the complete visual error/
denied/stale matrix, owner rehearsal, and external production approvals remain
open.
