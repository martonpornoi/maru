# Programme staffing and Shift connections

Date: 2026-09-15
Parent: #108 under #48; partial delivery, both remain incomplete.
Base: protected PR #132, `0ccd7866aa3965f527b3d8a28fcf5a2e4eebcb27`.

## Outcome and boundaries

Current Programme staffing cards can open their exact already-bound Workforce
Shift through the existing real slug route. Full independent organizer permission,
including holder display labels, is required; minimized coverage grants are not
enough. Events owns a coherent exact-chain route-metadata projection. No private
owner models or personnel inventories are imported/read by the new navigation.
No successor is inferred and historical bindings receive no current-work shortcut.

The canonical planner decorates copies of the cards while preserving original
owner facts for final lineage checking. Changed optional destinations are removed
without losing original input, versions, retry keys or command results.
Organizer Shift list/detail and validation/conflict responses receive independently
admitted Programme links with final lazy-render checks. Rendering never dispatches
a command twice. All existing Shift commands, read audits and personal pages remain
unchanged. No schema, migration, profile, production route, grant or CI change.

Requirements: HR-009, HR-014, HR-015, SCH-003, SCH-007, SCH-009, SCH-010, SCH-012,
UX-005 through UX-008, UX-019, UX-020, UX-027, UX-029, AUD-001, NFR-013.
Existing ADRs 0078, 0081, 0093 and 0100 remain authoritative; no new ADR is needed.
Owning staffing, Shift, Events, Scheduling and Workforce contracts are updated.
Rollback is ordinary code reversion; there is no new stored state or schema.

## Local iteration evidence

- 83 focused navigation/response/template checks passed in 1.68s.
- Full database-free suite: 7,624 passed in 45.36s, with three existing URLField
  deprecation warnings. A preceding attempt stopped at 6,923 passing tests on
  an empty staffing-panel fallback error; the production template was repaired,
  then focused and full tests passed. No acceptance result is omitted or reused.
- Frontend: all 93 tests passed, including the new bound-Shift link dirty guard.
- Ruff, static types for all six changed/new source modules, NumPy docstrings
  and whitespace checks passed during iteration.
- Exact-commit canonical and hosted acceptance remain pending at this checkpoint.
  Iteration evidence is not a receipt or native database certification.

## Synthetic browser observation and limits

One loopback-only fixture, with database connections explicitly forbidden, reused
the actual canonical timetable and native organizer Shift view/template code.
Owner projections, policy responses and source reads were explicitly substituted;
no persistence, native grants, lifecycle mutation or real coverage was certified.
Only synthetic convention, stage-support requirement, binding and draft work
were shown. The fixture and its created browser tab were stopped/closed afterward.

At a 1,280 CSS-pixel viewport, observed staffing card -> exact bound Shift ->
timetable planning return, with the fixed Programme continuations and explicit
fresh-selection guidance. The Shift page had one H1 and one main; inspected
Shift and planner document width was 1,265 pixels, with no page-level overflow.
The coverage-only synthetic role retained the staffing card and exact-reference
guidance but had no bound-Shift link. This tests optional disclosure composition,
not native denial enforcement. No direct-denial, screen-reader, full responsive,
200% zoom, reduced-motion or representative human acceptance is claimed.

## Retained final gates

The existing native scenario
`test_workforce_shifts.py::test_browser_and_api_keep_personal_and_organizer_shift_views_separate`
now checks current-profile absence of Programme links, native full-Shift exact
slug destination, and absence for the genuine person without organizer authority.
It was maintained but NOT collected or run under ADR 0100. #102 still owes that
execution plus integrated current-binding/successor movement, profile/field
revocation, audited owner reads and exact-commit complete native evidence.

#92 retains human keyboard/dirty-discard/return, narrow/zoom, reduced-motion and
assistive-technology checks; #109 retains real-owner end-to-end isolated proof.
#97 recovery and final profile promotion remain separate. Next independent #108
increment: task-focused #104 notice connections, then #107 continuity connections
and the remaining Applications selections/setup work. No parent is completed by
this bounded increment.
