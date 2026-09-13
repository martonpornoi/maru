# Read and copy a Programme timetable

**Audience:** Programme evaluators, operators, hosts and volunteers using synthetic data\
**Outcome:** Understand which timetable information is authoritative and how to
handle unavailable or changed output\
**Reading time:** 5 minutes

## Availability

These are dormant evaluation components, not an activated Programme module.
Normal Maru navigation does not expose them. A maintainer must deliberately run
an isolated synthetic rehearsal; do not add production routes, enable profiles,
or load real personal data to try this guide. Operator run sheets are a separate
private purpose, never an expanded public or personal timetable.

## Public timetable

1. Open the public timetable through the synthetic rehearsal's visible link.
   No account or attendee registration is required in this admitted fixture.
2. Check the release state, edition time zone and last-checked time. Dates include
   their UTC offsets; they are not silently converted to your computer's zone.
3. Read reviewed titles, summaries and content notes with approved event times
   and current room/venue wayfinding. Private host, reviewer and staffing details
   are not part of this page.
4. Choose a service day or room to narrow the list. The count distinguishes the
   visible subset from the complete timetable. Reset returns to the full list.
5. Use a complete JSON/calendar download or print-friendly view. A new request
   checks the release again. Downloads are not filtered copies of the current
   list, and a print-friendly page does not itself open the browser print dialog.

## My hosting and work timetable

Sign in as the synthetic owner through the rehearsal menu. The shared My Maru
page combines only that person's independently authorized adopted layers:

- **Approved required host presence** is when that host must be present. The
  surrounding preparation/delivery/teardown window is context, not an assignment
  to work every phase. Briefing comes from the own host invitation.
- **Claim — not confirmed** is tentative work, not an accepted assignment.
- **Confirmed work** retains its Workforce interval. Programme output cannot
  silently move it. Current location and instructions have their own version;
  they are not an immutable accepted location.
- **Removed/completed work records** are retained history, not current staffing
  promises or evidence of actual attendance.
- **Hosting without an approved time** retains invitations and purpose history
  separately; it does not invent a schedule commitment.

An unadopted module is labelled differently from an adopted module with no own
records. Edition names are shown only when actual own records justify that
context. The Access disclosure explains exact-self visibility. Source details
identify release, placement, work and owner versions; print retains those details.
There is no other-person selector or suitable-unclaimed-work list on this page.

## Room, Department and edition run sheets

1. Continue as the synthetic operator and open the explicitly granted purpose:
   one room, one Department, or the whole edition. A room grant cannot open the
   edition sheet. Department scope means its current rooms plus adopted linked
   work, including retained predecessors; it does not mean ownership of Programme
   items or every child Department. A Department with no room can still have work.
2. Check the scope, release state, edition time zone and source details. Each
   approved card distinguishes preparation, delivery and teardown. These are
   run-of-show context, not a volunteer assignment to work the whole interval.
3. Start with reviewed copy and wayfinding only. Select technical, accessibility,
   media or staffing layers only for the task at hand, then choose **Show requested
   run sheet**. Each selected layer needs its own authority; requesting a denied
   layer fails the complete request rather than quietly omitting it.
4. Read current Programme instructions and room names with their own versions.
   They are not frozen approval facts. The title and approved timing still refer
   to the exact immutable release; newer drafts do not replace them.
5. With staffing selected, distinguish current demand terms from retained work
   intervals and state counts. A predecessor marked cancelled/removed is history;
   a claim is not confirmed work, and confirmation is not attendance or renewed
   qualification/availability. This sheet intentionally contains no person roster
   or private contacts. Reconcile people through an independently authorized
   Workforce workflow, not by guessing from counts.
6. Choose the print-friendly view, JSON or private calendar to copy the same
   selected layers after a fresh check. The transparent calendar covers room
   preparation through teardown; it is not an invitation or personal shift.

Keep exported private information within its authorized operational audience.
The print view preserves scope, source versions and saved-copy warnings; opening
it does not automatically start printing. A Department sheet with staffing not
adopted is explicitly rooms-only, not evidence that no volunteer work exists.

## When information cannot be used

Withdrawn or invalidated Programme releases do not retain a previously approved
room/timing advertisement. The private page can still show unchanged accepted
work and known hosting state, but withholds the combined calendar until the
release is checked again. Operator sheets contain no approved rows while the
release is absent, withdrawn or invalidated; their calendar is unavailable.
Contact the organizer through the convention's existing
channel; this component does not send change notices or record acknowledgement.

For a temporary source failure, reload; Maru does not silently serve an earlier
or partial timetable. A not-available address reveals no hidden tenant or record.
If options are invalid, reload the clean address and choose a supported format.

Every file or printout is a point-in-time copy. Keep private files secure and
recheck online before relying on them. Imported calendars may keep earlier
entries even with stable IDs; remote erasure, automatic updating and signed
offline freshness are not guaranteed. On-site continuity, logical restore and
human acceptance remain separate [#48](https://github.com/martonpornoi/maru/issues/48)
gates. No output creates attendance, payments or attendee relationships.

## Rehearsal and technical contracts

Maintainers can explicitly run `tests/rehearsals/programme_outputs.py` or
`tests/rehearsals/personal_timetable.py`, or
`tests/rehearsals/programme_operator.py` against an isolated test PostgreSQL
database, using the opt-in environment variable documented in each module.
Use the visible Finish button; the one-hour lease is a safety limit, not a
passing browser result. Keep role/state, keyboard and responsive observations
separate from [#92](https://github.com/martonpornoi/maru/issues/92)'s human gates.

See the [public page contract](../product/page-contracts/programme-released-timetable.md),
[personal page contract](../product/page-contracts/personal-programme-timetable.md),
[operator page contract](../product/page-contracts/programme-operator-run-sheets.md),
[Scheduling module](../modules/scheduling.md), and
[ADR 0097](../architecture/decisions/0097-release-derived-programme-output-boundaries.md)
with [ADR 0099](../architecture/decisions/0099-purpose-scoped-programme-operator-outputs.md)
for authority, source, format and recovery boundaries.
