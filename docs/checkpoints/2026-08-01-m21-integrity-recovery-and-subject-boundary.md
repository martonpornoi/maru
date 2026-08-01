# M2.1 integrity, recovery, and convention-subject boundary

- Date: 2026-08-01
- Branch: `codex/full-platform-consolidation`
- Phase: Production consolidation M2.1 hardening
- Requirements: IDN-002, IDN-004, IDN-005, IDN-011, IDN-012, UX-013,
  UX-020, UX-024, AUD-001, AUD-005, NFR-001 through NFR-004, NFR-008,
  NFR-009
- Decisions: ADRs 0039 through 0043

## Outcome

The unified `/admin/` shell and initial Executive Board handoff now have a
stronger local integrity and recovery boundary:

- organizations `0009` freezes governance identity and provenance, validates
  exact active Board authority/evidence, and fences destructive downgrade;
- organizations `0010` rejects platform direct-grant and role principals and
  completes active membership/appointment provenance;
- organizations `0011` enforces ADR 0043's global emergency controller
  containment, quorum-loss suspension, evidence, and downgrade boundary;
- organizations `0012`, participation `0004`, registration `0031`, and
  workforce `0003` enforce IDN-011 for every covered convention-subject
  relationship below the ORM; and
- Page 8 manager reads and privileged denials append value-minimized audit
  evidence after exact-tenant filtering, with deterministic ordering, a
  100-row ceiling, bounded returned count, and fail-closed audit persistence.

Platform accounts remain permitted as attributed actors and provenance. They
cannot be members, appointees, grant or role principals, participants,
registrants, attendee-profile/fursuit owners, volunteers, onboarding subjects,
or workforce assignees.

## Decisions recorded

- ADR 0039 keeps Pages 1–8, Convention work, and specialist records inside one
  collision-safe management shell.
- ADR 0040 remains the normal two-controller organization-activation path.
- ADR 0041 accepts exact department and typed-resource authorization scope with
  no implicit hierarchy inheritance. Its runtime implementation remains next.
- ADR 0042 makes repository examples synthetic-only. The former public-roster
  rehearsal implementation is deleted; its compatibility command fails before
  password validation, file/network access, or database mutation.
- ADR 0043 permits only a reasoned platform emergency command to close one
  person's open Board relationships globally, revoke sessions and authority,
  deactivate the account, and suspend Boards that lose quorum. It is not a
  routine term-management workflow.

## Verification recorded

- 58 combined representation, migration, and readiness tests pass.
- Five emergency-containment focused tests pass.
- A 71-test adjacent IDN-011 organization/participation/registration/workforce
  batch passes, including direct/bulk database bypass and concurrent account-
  kind reclassification boundaries.
- The populated local database applies organizations through `0012` plus
  participation `0004`, registration `0031`, and workforce `0003`.
- Fresh PostgreSQL migration tests pass. The earlier empty-database migration
  and populated local restore drill applied all 100 migrations through
  organizations `0009`, reconciled bounded table counts, and removed the
  isolated drill database.
- The readiness command reports deterministic, privacy-minimized blocker
  counts and bounded organization slugs at the recorded `0009` boundary.
- Desktop and 390-pixel shell/Page 3/Page 7/Page 8/Convention work smoke passes
  without horizontal overflow or browser console warnings.
- Nine focused unified-routing tests pass. The `/admin/logout/` and
  `/admin/password_change/` handlers resolve before AdminSite's staff-only URL
  wrapper, preserving scoped non-staff account self-service without exposing
  Specialist records.
- A live Board logout reached `/accounts/login/`, removed the logged-in banner,
  and produced zero new console warnings or errors. The hidden `#nav-filter`
  fallback remains when no Specialist records are available.
- A live platform-administrator reload showed one searchable `#nav-filter`,
  Specialist records and Platform administration exactly once each, the
  correct `demo.admin` account, and zero new console warnings or errors.
- `pip-audit` and the production `pnpm audit` report no known dependency
  vulnerabilities at this checkpoint.
- The production-shaped deploy check is clean.
- Documentation validation passes for 165 Markdown files and 195 unique
  requirement identifiers; the documentation diff has no whitespace errors.
- The focused readiness/core invocation passes 10 tests.
- The focused representation/platform matrix passes 126 tests, including the
  current concurrency and lock-order hardening.
- The HTTPS warning-as-error focus passes 24 tests.
- The ordered migration-contamination regression passes 26 tests.
- The final consolidated backend invocation passes 792 tests in 329.21
  seconds, reaches 90.01 percent coverage, and emits no warnings.
- A separate behavior run passes the same 792 tests in 291.86 seconds.
- The fresh `maru_consolidated_demo` database applies all 106 migrations,
  contains 80 synthetic accounts, two organizations, and six editions, and
  reports readiness 16/16 with zero blockers.
- The current restore drill into `maru_restore_drill_m21` passes and cleanup
  removes the drill database afterward.

Historical-migration test modules use a shared `finally` fixture that restores
every Django app to the migration graph's current on-disk leaf. The regression
also proves that a historical workspace target returns to all current leaves
with the IDN-011 subject triggers installed. This prevents an earlier migration
test from leaving the schema below current guards for later tests.

The green local backend and coverage gate does not certify representative
deployment restore/PITR, accessibility, complete visual states, owner
rehearsal, or production approval.

## Recovery boundary

All current governance and IDN-011 migrations require stopped writers. They do
not infer controllers, invent replacement people, reclassify accounts, delete
relationships, or waive blockers. A non-zero count or governance mismatch
requires an approved reconciliation on a restored copy.

After a governed or subject write relies on the new guards, retain compatible
code and fix forward. Reverse only inside an approved maintenance window when
the relevant downgrade fence proves no later evidence exists. Otherwise
restore the whole database to a mutually consistent point under an explicit
data-loss decision.

The local empty/restore evidence is repository rehearsal, not representative
deployment backup or point-in-time recovery certification.

## Known risks and incomplete work

- Representative deployment restore/PITR, old-writer/fix-forward rehearsal,
  named operators, and release approvals remain external gates.
- Complete keyboard traversal, automated accessibility analysis, the full
  error/denied/stale visual matrix, and the owner-led tutorial remain open.
- Routine appointment expiry, replacement, voluntary ending, planned
  suspension/reactivation, quorum recovery, and invitation delivery remain
  absent.
- ADR 0041 department/resource persistence, trusted targets, migrations,
  effective-access explanation, and contextual assignment editor remain next.

## Smallest sensible next actions

1. Implement ADR 0041 before mounting any department-owned mutation.
2. Rehearse all migrations against a representative restored database with
   backup/PITR and fix-forward evidence.
3. Complete keyboard/accessibility/state-matrix checks, then run the tutorial
   with the owner using only synthetic data.
