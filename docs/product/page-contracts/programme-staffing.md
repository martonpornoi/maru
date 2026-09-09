# Programme staffing

- Status: Accepted continuation contract; native implementation and focused
  synthetic rehearsal complete locally, issue-level certification pending.
- Child: [Staffing #88](https://github.com/martonpornoi/maru/issues/88).
- Parent: [Programme Operations #48](https://github.com/martonpornoi/maru/issues/48).
- Requirements: HR-009, HR-014, HR-015, SCH-003, SCH-007, SCH-009, SCH-010,
  SCH-012, UX-005 through UX-008, UX-019, UX-020, UX-027, UX-029, AUD-001
  and NFR-013.
- Decisions: ADRs 0078, 0081, 0088, 0092 and 0093.
- Intended canonical home: **Timetable planning**, selected item/occurrence,
  **Staffing** continuation, inside the existing edition-scoped Programme route.
  This child mounts no production route or navigation destination.

## Purpose and ownership

A Programme planner defines the work needed for an occurrence, deliberately
requests Workforce demand, understands coverage and changed-source impact, and
recovers without rewriting a volunteer's accepted work. The preceding task is
private timetable placement; independent approval/release and on-site run sheets
remain subsequent tasks, not executable-looking links until accepted.

Programme owns requirement terms and history. Scheduling owns the explicitly
selected candidate/occurrence/placement. Workforce owns demand and commitments.
The existing [Shift planning and My shifts](shift-planning-and-my-shifts.md)
journey remains the only open/claim/confirm/lock/reopen/cancel/complete lifecycle.
Neither a Programme requirement nor a private placement is accepted work or a
published timetable. Requirements may be recorded before a placement exists;
binding requires an exact current source, never the last alternative edited.

## Authority and information layers

Keep the [shared shell](00-management-experience-shell.md), one page H1 and one
`main`, exact edition context, purpose statement and computed Access disclosure.
Resolve scope before parsing private inputs or loading labels. Controls do not
grant authority; every continuation and command reauthorizes independently.

- Current requirements require Programme `staffing_requirements`; editing needs
  the separate Programme staffing-management capability.
- Requirement history requires `staffing_history`, not merely current terms.
- Binding source/work preview independently requires Programme, Scheduling and
  Workforce read authority. Applying it additionally needs Programme staffing
  management and Workforce Shift management. Read-only users cannot apply.
- Current binding metadata excludes private actor/rationale columns. Binding
  history requires Programme history and Workforce work-field authority and
  shows only the explicitly selected fixed-ceiling historical purpose.
- Coverage independently requires Workforce demand, coverage and suitability
  fields. It contains no volunteer names, private reasons or complete calendars.
  Missing authority is **Withheld**, never zero volunteers. Work instructions
  appear only in the explicitly authorized requirement or work-impact purpose.

Position choices use an independently authorized Workforce owner projection;
opaque identifiers or a selected context cannot authorize labels. The UI must
not substitute a personnel-bearing organizer overview for minimized coverage.

## Native requirement workflow

Select the exact item and occurrence before editing. Show retained needs as
labelled cards with work title, reporting place, explicit work interval in the
edition zone, headcount, break/rest, version and active/retired state. No silent
truncation may masquerade as the complete set.

Creation/revision uses ordinary labelled fields for Position, title, reporting
place, briefing, optional supervision note, start/end, headcount, break and rest,
plus required reason. Preparation/teardown work is explicit; audience-facing
timing or Programme title is never silently copied into accepted instructions.
Local times reject nonexistent/ambiguous minutes unless explicitly disambiguated.
Retirement requires deliberate confirmation and explains that it preserves
history and does not cancel Workforce work. Retired needs cannot be edited.

## Deliberate work request and recovery

Show the selected alternative and source versions beside the requested action.
Never select another candidate or follow a newer revision on the user's behalf.
Available actions are **Create draft work**, **Link identical draft work**,
**Reconcile uncommitted draft**, and **Create separate successor**.

Preview is the default submission and creates no demand or commitment. It
compares exact work terms, highlights changed fields and shows aggregate retained
decisions and active claims/confirmations affected by explicit cancellation.
The apply control is a separate deliberate step with a Workforce-visible reason,
affirmative impact confirmation, exact preview digest and original retry key.
The digest proves neither human review nor present authority; apply resolves again.

Linking requires identical uncommitted draft work. Reconciliation requires no
retained commitments and cannot replace an immutable Position. A successor
retains its predecessor, explicitly cancels nonterminal work through Workforce,
and creates a new draft with no transferred claims, confirmations or lock.
The user must understand these consequences before applying. The existing Shift
journey separately opens work and obtains new personal decisions.

Coverage labels distinguish unrequested, draft, open gap, awaiting confirmation,
covered, review required, locked underfill, completed, cancelled, stale, withheld
and unavailable. Claims are not confirmations; accepted underfill is not complete
coverage. Source/work-term drift yields null counts, while an ordinary open/lock
version increment does not by itself invalidate unchanged bound work.

## Failure, history and accessibility

Preserve safe entered values and the retry key for the same intent after
validation or recoverable failure. Stale impact requires deliberate fresh review;
never silently replace versions or reapply. An uncertain post-command reload
does not mean nothing changed: explain exact retry/history recovery.

Keep empty, populated, denied, read-only, malformed, stale, dependency-failure,
overflow and success states distinct. Missing scope/field authority withholds
the affected private context. Audit failure cannot release sensitive results.
History pages have an explicit inclusive ceiling and exclusive cursor; later
edits do not silently extend them. No browser storage, URL-carried private input,
autosave, offline write queue or background mutation is introduced.

Use native labels, fieldsets, buttons, status text, visible focus and linked
errors. Preserve selection and return focus after preview/apply/recovery; warn
before discarding pending input. Narrow cards preserve reading order without
page-level horizontal overflow. Verify keyboard operation and 320, 390, 768,
958, 1024, 1280 and 1920 CSS pixels, real 200% zoom, reduced motion and automated
accessibility. Record unperformed representative screen-reader/human and runtime
acceptance honestly; #87 remains mandatory before activation.

## Evidence and exclusions

Use strict form/adapter tests plus real PostgreSQL source, permission, lifecycle,
retry, race, rollback and history tests. Browser rehearsal uses only an isolated
synthetic fixture and does not activate a profile. Certification and protected
exact-head acceptance remain required before #88 closes.

This continuation creates no Participation, attendee Registration, payment,
attendance, private-calendar sharing or unrelated module side effects. Combined
published personal timetables, release/outputs, on-site continuity and guided
activation remain later #48 work. Issues #22, #23, #24 and #42 stay independent.
