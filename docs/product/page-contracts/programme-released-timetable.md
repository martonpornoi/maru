# Released Programme timetable

- Status: Accepted dormant component contract; #99 implementation in progress.
- Parent: [Programme Operations #48](https://github.com/martonpornoi/maru/issues/48).
- Requirements: SCH-006, SCH-008, SCH-010, SCH-012, UX-007, UX-008, UX-013,
  UX-029, NFR-001, NFR-002, NFR-013.
- Decision: [ADR 0097](../../architecture/decisions/0097-release-derived-programme-output-boundaries.md).
- Dormant public route: `/programme/<organization_id>/<edition_id>/timetable/`.
  It is not included in the production URL configuration or current navigation.

## Audience and task

A signed-out reader can read the complete approved Programme, narrow the visible
list by service day and room, and obtain a complete JSON/calendar or print-friendly
copy. No login, planner grant or attendee Participation is inferred. The exact
edition must independently admit the public-release adapter; current profiles
do not. An isolated synthetic fixture is not runtime/profile acceptance.

The page has one H1 and one main landmark, a short purpose statement, and an
Access disclosure explaining public reviewed fields versus private host/work
layers. It is not a second administration shell or a path into Registration.
This public component has no private actor selector, edit action, confirmation,
check-in, host-name publication, or personal-work toggle.

## Source and representation

All normal rows come from `load_public_programme_timetable`. Each shows reviewed
title, summary and content note, current room/venue wayfinding and approved
effective start/end with date and UTC offset in the edition time zone. Private
day labels, host identities, review evidence, staffing and delivery layers never
reach the DOM. Dates identify the exact selected service-day window, including
overnight days; browser local time does not reinterpret approved instants.

Release sequence, publication time, last checked time and exact release identity
remain inspectable. The release state, zone and check time remain immediately
visible; secondary publication and saved-copy details use a native disclosure
so provenance does not bury the programme. Print retains those details even
when the screen disclosure was closed. Current wayfinding has explicit owner-version meaning; print
retains the source identity and date. A filtered list reports its displayed and
complete counts. Format downloads are always the complete newly checked release,
not an unlabeled subset or a reuse of earlier browser content. JSON and calendar
use the same closed public projection and bounds. Ordinary print/download is a
point-in-time copy, not signed offline continuity or a promise of remote erasure.

## States and recovery

- Available: complete readable list, service-day/room filters, clear reset and
  complete JSON/calendar/print-friendly links.
- No matching filter: explicitly zero displayed entries, original scope/count,
  reset link; never claim that the released programme itself is empty.
- Absent: no timetable published, no entries or download controls.
- Withdrawn: previous release is no longer being served; no retained entries or
  download controls and no automatic fallback.
- Invalidated: released information needs review before it can be used; no room
  or copy is advertised as currently approved.
- Denied/foreign/unadopted: uniform not-available page and HTTP 404, without
  organization, edition, person or release existence details.
- Malformed, duplicate, unknown or overlong query input: generic HTTP 400 with
  a clean reload link, without echoing raw inputs. Day/room choices must belong
  to the complete authorized projection.
- Missing/moving/oversized owner or format evidence: HTTP 503 with retry
  guidance and no partial timetable. Unavailable calendar requests return an
  explanatory non-calendar HTTP 409, not a misleading empty import file.
- POST and other mutations: not supported. Reading never changes a release,
  creates an account or alters accepted work.

Every request rechecks its own authority and sources. Responses are no-store;
format MIME types and nosniff prevent JSON/calendar being interpreted as HTML.
Untrusted content is autoescaped in HTML and format-escaped in downloads.

## Keyboard, responsive and print behavior

Use ordinary labelled selects, a submit button, links and a native disclosure.
There is no pointer-only action, modal, animation, client storage or JavaScript
requirement. Readable cards wrap long text instead of requiring horizontal
page scrolling. Focus remains visible and controls meet comfortable touch sizes.
Print removes navigation/filter controls but retains source/freshness meaning,
room names, times and reviewed information. A print-friendly page is ordinary
HTML; invoking the browser's print dialog remains a user action.

Exercise 320, 390, 768, 958, 1,024, 1,280 and 1,920 CSS pixels, keyboard traversal,
long text, empty/filter/failure states, downloads and format non-disclosure.
Real 200% zoom, representative screen-reader and human on-site comprehension
remain tracked under #92 when unavailable unattended. Automation is evidence
for the synthetic component, not a substitute for those human gates.

## Continuations and remaining layers

Private personal host/work views belong to #99, not toggles on this public payload.
Independently authorized room/department operational layers are retained in
native #48 child #100 and follow #99's protected merge; they are not waived.
Later guided activation provides authorized discovery; until then no current
menu advertises an executable Programme journey. Detailed change delivery,
acknowledgement, on-site packs, #97 logical recovery and integrated acceptance
remain separate #48 gates. CURRENT records actual verification and delivery.
