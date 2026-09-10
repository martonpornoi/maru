# Programme staffing native workflow and focused browser rehearsal

- Date: 2026-09-10 (Europe/Budapest).
- Branch: `codex/programme-staffing`; previous local checkpoint `e04d2c8`.
- Child: [#88](https://github.com/martonpornoi/maru/issues/88), parent #48.
- Local implementation evidence only; no PR, full certification or merge.

## Outcome

The existing dormant timetable component now has requirement create/revise/retire,
fixed-ceiling requirement/binding history, minimized coverage and deliberate work
create/link/reconcile/successor preview/apply controls. Strict typed native forms
retain exact selected identities, versions, reason and retry key. Current labels
come from independently authorized, bounded and audited Workforce choice queries,
not a personnel-bearing overview. Preview grants no mutation authority; apply
requires both owners and explicit impact confirmation. No Shift lifecycle action,
Programme route/profile activation or unrelated-module write is introduced.

## Automated evidence

- Nine real PostgreSQL native HTTP cases passed in **48.50s**: requirement lifecycle
  and replay/history; draft preview/apply/replay; link/reconcile/explicit successor;
  missing confirmation; moved source; read-only denial; CSRF/base-admission denial;
  successful commit followed by unavailable reload and exact retry recovery.
- Six PostgreSQL choice-query cases and 33 form unit cases passed together in
  **19.68s**. Forty-two form/dispatch unit cases passed in **0.40s**; 137 existing
  view/selection cases passed in **1.38s**.
- Full unit run passed **4,244 cases in 21.37s**, with two pre-existing Django
  URLField warnings. Five later template-focus regressions passed in **0.34s**.
- Focused Ruff, strict Mypy for six production files and semantic docstrings for
  four new production files passed. These are development checks, not certification.

## Browser evidence

The opt-in `tests/rehearsals/programme_staffing.py` used the owned disposable #88
PostgreSQL database, sealed future policies and ordinary sessions for pre-created
synthetic planner, view-only, manage-only and restricted-Workforce accounts.
Anonymous and executable-profile denial were also exercised. It is not a
password-login, Programme-only or provisioned-runtime rehearsal.

Two in-app browser leases ended through their visible Finish control; pytest
confirmed cleanup. Ports 63911 and 56732 are no longer serving. Temporary tabs
were closed and viewport overrides reset; no reminder or watcher was created.

- Planner: exact draft and occurrence selection, staffing discovery, requirement
  revision, invalid headcount with retained reason, correction/save, complete
  fixed-version history, exact impact preview, explicit apply and draft coverage.
- Keyboard: error summary focus, native Space confirmation and Enter apply.
  A discovered defect focused the unrelated selected-item heading; templates now
  choose staffing overview, form, error or impact exactly once. Five regression
  cases and a fresh browser lease verified the correction and post-save focus.
- Read-only: current work/coverage and impact preview, with no requirement edit
  or apply action. Restricted Workforce: withheld binding/coverage, null counts,
  no demand reference. Manage-only, anonymous and current-profile: generic denial
  with no private item/work context.
- Coverage and impact pages: no horizontal page overflow at **320, 390, 768, 958,
  1024, 1280 and 1920 CSS pixels**. One H1/main verified on coverage. Narrow form
  and intermediate-width overview screenshots were visually inspected.
- Automated WCAG-tag analysis of the impact preview: **zero violations**, with
  one rule requiring manual review. This is not complete accessibility acceptance.
  Corrected application-console inspection returned no warnings/errors. Expected
  400/403 responses and a fixture-only favicon 404 are not product crash evidence.

## Remaining acceptance

#87 retains genuine 200% zoom, enabled reduced motion and controlled native
discard acceptance; they were not silently waived or inferred from widths. Broad
screen-reader/representative-human and runtime acceptance also remain separate.
Complete #88's remaining issue-level races and own-person/no-Participation proof,
then run exact-head certification and protected delivery. The production Shift
route handoff belongs to the later canonical host activation; this dormant panel
identifies the exact work and explains the existing independently authorized
Shift planning continuation without mounting another route.
