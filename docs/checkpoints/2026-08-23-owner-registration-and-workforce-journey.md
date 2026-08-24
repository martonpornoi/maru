# Checkpoint: Owner Registration and Workforce journey

- Date: 2026-08-23
- Phase: Production consolidation and management-experience recovery
- Related requirements: HR-007 through HR-011, REG-007, REG-009, REG-021,
  SCH-001, SCH-005, UX-007, UX-020, and UX-029
- Related ADRs: 0019, 0028, 0039, 0045, 0049, and 0055

## Outcome

The fictional non-staff MaruCon Convention Chair can now move coherently from
the attendee-first **Registration desk** into one owner-safe **Workforce** task.
The embedded client and Django host converge on the same selected edition, so
the owner no longer sees `All foundation data` around records from MaruCon
2026 or a second client-side workspace selector.

Blocking person, attendee, and access drawers share one accessible modal
interaction. The attendee rehearsal now enters the dialog, exposes its purpose
through a heading, contains focus, closes on Escape or the backdrop, isolates
and scroll-locks the background, and returns focus to the exact attendee.

Workforce consumes the existing strict exact-edition structure projection and
presents one dependent sequence:

```text
Structure -> Positions -> Assignments -> Availability -> Shifts
```

Departments, Position purpose/reporting/state, approved headcount, vacancies,
and minimized active holders are truthful current reads. **Open structure**
continues to canonical Page 9a.1. Availability and Shifts are each labelled
**Not available yet** and have no controls. The view states that availability
will be person-owned and that shifts still need demand, claim, confirmation,
overlap, completion, and locking semantics. No Position is presented as a
shift and no assignment is treated as availability.

## Decisions

- Reuse the existing version-fenced, bounded, audited Workforce structure GET;
  do not create a second projection or Department writer.
- Make Workforce a durable task and Registration's single team-operations
  handoff. Keep canonical Department management at Page 9a.1.
- Do not send non-staff owners into Django Position or PositionAssignment model
  pages. Independently authorized Django staff may use clearly labelled
  temporary links until Page 9b exists.
- Give unimplemented availability and shifts an honest place in their owning
  journey without adding fake data, disabled controls, models, permissions, or
  schedule authority.
- No ADR or migration is needed. The work applies accepted shell, access,
  structure, and task-navigation decisions without changing domain semantics.

## Verification

- Staff Console TypeScript check: passed.
- Staff Console Vitest: 28 passed, including host-context synchronization,
  person/attendee modal focus and Escape return, the populated Workforce
  sequence, non-staff specialist-link exclusion, non-disclosing `403`,
  oversized-structure suppression, and axe scans of Registration and Workforce.
- Production Vite build: passed; generated Django-host assets refreshed.
- Expanded Django Workforce projection/Page 9a.1 plus shell, navigation, host,
  responsive, and page-access tests: 65 passed in 63.39 seconds.
- Authenticated Chrome rehearsal as
  `marucon.convention-chair@demo.maru.invalid`: MaruCon 2026 context converged,
  Registration and Workforce each rendered one H1 and one `main`, the
  390-CSS-pixel pages had no horizontal overflow, attendee dialog semantics and
  keyboard focus return passed, staff-only Workforce links were absent, all
  five stages were visible, and **Open structure** reached exact Page 9a.1.
- Ruff format/check, mypy across 354 source files, migration drift, repository
  whitespace, documentation policy, and warning-fatal Sphinx/AutoAPI checks:
  passed. The local Django check reports only the expected fail-closed
  invitation-encryption warning.

## Data, migration, and deployment notes

No model, migration, persisted data, capability, audit event, outbox message,
or domain writer was added. The local browser used fictional seeded data on a
disposable development database. This evidence is not deployment, recovery,
authority-cutover, or production-data approval.

## Known limits and next work

- The complete UX-029 width/zoom, representative screen-reader, failure/empty,
  and mutation-role matrix remains open.
- Page 9b must provide a purpose-built Position and assignment mutation journey
  with template/role pinning, headcount, reporting, opportunity state,
  onboarding prerequisites, dual approval, and recovery.
- Availability and Shifts remain unimplemented until accepted
  HR-009/SCH-001/SCH-005 transactional, privacy, authorization, audit, and
  recovery contracts exist.
- Venues and Logistics are the next existing operational areas suited to the
  same task-first treatment after the Workforce mutation boundary is chosen.
