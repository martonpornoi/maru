# Architecture

## Suggested Stack

- Django backend with server-rendered admin/staff flows.
- Django REST Framework or lightweight JSON views for website/signage exports.
- PostgreSQL in production.
- Redis optional for cache and background jobs.
- Internal notification table instead of outbound email.
- Object storage or filesystem media storage for profile and fursuit pictures.

The repository starts with a small pure-Python domain layer so terminology and
rules can be tested before they are bound to Django models.

## App Boundaries

Planned Django apps:

| App | Responsibility |
| --- | --- |
| `accounts` | Google auth, allowlist, roles, profile unlock state. |
| `projects` | Projects, subprojects, YAML import, convention opening windows. |
| `forms` | Google Forms-compatible form sections, questions, application versions. |
| `reviews` | Approval workflows, reopening, staff decisions. |
| `profiles` | Personal/fursuit profiles and participation history. |
| `spaces` | Hotels, rooms, movable wall combinations, capacities, properties. |
| `timetable` | Panels, shifts, layered schedule planning, grouped/recurring events. |
| `notifications` | Internal notifications and reminder broadcasts. |
| `exports` | Website, signage, print, and token-scoped API exports. |

## Data Model Sketch

```text
AccessAccount
  email
  roles
  active

Project
  name
  slug
  timezone
  opens_at
  closes_at

Subproject
  project
  name
  kind
  visibility rules

ApplicationForm
  subproject
  sections
  fields with original Google Forms labels

Application
  form
  applicant
  status
  current_version

ApplicationVersion
  application
  answers
  submitted_at

Profile
  account
  display_name
  pictures
  handles
  bio

Hotel
  project
  name

Room
  hotel
  name
  capacity
  properties

RoomCombination
  rooms
  combined_name

TimetableItem
  project
  layer
  owner
  room_or_combination
  start/end
  grouping metadata
```

## Security Notes

- All exports are deny-by-default.
- Public website exports should use separate read-only API tokens scoped to a
  project and export type.
- Signage tokens should not expose private profile/contact data.
- Staff-only timetable layers should never be included in public exports.
- Profile images need explicit visibility state.
- Every reopen, approval, schedule change, and export token use should be
  auditable.

## Naming Direction

Avoid these pretalx terms in the main UI:

| Generic/pretalx-like | maru UI term |
| --- | --- |
| Event | Project or Panel, depending on context |
| Organiser | Staff Team |
| CfP | Applications |
| Submission | Application or Panel |
| Speaker | Host |
| Room | Room |
| Schedule | Timetable |

