# Read and copy a Programme timetable

**Audience:** Programme evaluators, hosts and volunteers using synthetic data\
**Outcome:** Understand which timetable information is authoritative and how to
handle unavailable or changed output\
**Reading time:** 5 minutes

## Availability

These are dormant evaluation components, not an activated Programme module.
Normal Maru navigation does not expose them. A maintainer must deliberately run
an isolated synthetic rehearsal; do not add production routes, enable profiles,
or load real personal data to try this guide. Room/department operator run sheets
remain in [#100](https://github.com/martonpornoi/maru/issues/100).

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

## When information cannot be used

Withdrawn or invalidated Programme releases do not retain a previously approved
room/timing advertisement. The private page can still show unchanged accepted
work and known hosting state, but withholds the combined calendar until the
release is checked again. Contact the organizer through the convention's existing
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
`tests/rehearsals/personal_timetable.py` against an isolated test PostgreSQL
database, using the opt-in environment variable documented in each module.
Use the visible Finish button; the one-hour lease is a safety limit, not a
passing browser result. Keep role/state, keyboard and responsive observations
separate from [#92](https://github.com/martonpornoi/maru/issues/92)'s human gates.

See the [public page contract](../product/page-contracts/programme-released-timetable.md),
[personal page contract](../product/page-contracts/personal-programme-timetable.md),
[Scheduling module](../modules/scheduling.md), and
[ADR 0097](../architecture/decisions/0097-release-derived-programme-output-boundaries.md)
for authority, source, format and recovery boundaries.
