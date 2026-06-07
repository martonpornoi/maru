# maru

maru is a clean-room event operations content backend for furry conventions. It
is designed as the internal source of truth for submissions, profiles,
schedules, volunteers, rooms, and public data exports that an official website
or signage system can safely fetch from. It is inspired by the useful workflows
in pretalx, but it uses convention-focused language and structure from the
start.

The product model is:

- **Project**: one convention edition, for example `Awoostria 2026`.
- **Subproject**: one application area inside a project, for example event
  submissions, dance competition volunteers, DJ applications, or fursuit support.
- **Application**: one submitted form response.
- **Panel**: an approved event application that can appear on the timetable.
- **Shift**: a volunteer staffing assignment, shown as a separate timetable layer.
- **Profile**: an approved user's public convention profile.

## Initial Scope

This repository currently contains:

- Product and architecture notes in `docs/`.
- A small tested Python domain core in `src/maru/`.
- A seeded access rule for `marton.pornoi@gmail.com`.
- A YAML project import example for conventions, hotels, rooms, forms, roles,
  and timetable rounds.

The code is intentionally not copied from pretalx. If we later reuse pretalx
code directly, we need to handle licensing and attribution explicitly.

## Development

```bash
cd /mnt/c/Users/TheMw/Desktop/pretalx/maru
uv run --extra dev python manage.py migrate
uv run --extra dev python manage.py seed_maru
uv run --extra dev python manage.py runserver 127.0.0.1:8000
```

Then open `http://127.0.0.1:8000/login/` and use
`marton.pornoi@gmail.com`.

By default, local development also enables a development email login fallback.
It enforces the Google email domain and the maru access list, but does not
contact Google. Set `MARU_DEV_LOGIN_ENABLED=0` to disable it.

Real Google OAuth is available once client credentials are configured:

```bash
export MARU_GOOGLE_OAUTH_CLIENT_ID="your-client-id"
export MARU_GOOGLE_OAUTH_CLIENT_SECRET="your-client-secret"
export MARU_GOOGLE_OAUTH_REDIRECT_URI="http://127.0.0.1:8000/oauth/google/callback/"
```

In Google Cloud, add the same redirect URI to the OAuth client. For production,
also set `MARU_DEBUG=0`, `MARU_SECRET_KEY`, `MARU_ALLOWED_HOSTS`, and a
production HTTPS redirect URI. Google authentication only proves identity;
maru still authorizes access through `AccessGrant` records and roles.
Production deployment notes are in `docs/deployment.md`.

Run tests with:

```bash
uv run --extra dev pytest -q -s tests
uv run --extra dev ruff check .
uv run --extra dev python manage.py check
```

Import or update a convention setup from YAML with:

```bash
uv run --extra dev python manage.py import_project docs/example-project.yml
```

The import currently creates or updates projects, subprojects, hotels, rooms,
room combinations, event groups, form fields, and allowlisted accounts. It does
not delete records that were removed from YAML.

Load educational demo data with:

```bash
uv run --extra dev python manage.py seed_demo
```

Then log in and open `http://127.0.0.1:8000/projects/`.

The demo seed includes several accounts so you can switch between roles with
the development login:

- `marton.pornoi@gmail.com`: Admin, Board, Event Manager
- `cooling.host@gmail.com`: approved host with a public profile and scheduled panel
- `crafts.host@gmail.com`: approved host with profile and scheduled workshop
- `neon.dj@gmail.com`: host with a submitted DJ-style application in review
- `lounge.host@gmail.com`: host with a reopened application
- `dance.helper@gmail.com`: volunteer with confirmed and claimed shifts
- `stage.runner@gmail.com`: volunteer with confirmed and claimed shifts

The Awoostria demo also includes scheduled panels, profile/fursuit image paths,
internal notifications, event group metadata, open volunteer shifts, confirmed
assignments, and claimed assignments.

The project detail pages now include `Submit application` links for each
subproject. Submitted applications appear on `My Profile`, split between current
applications and application history.

Admins, Board users, and Event Managers can manage convention forms from the
sidebar `Forms` link. In the general project selector state, the Forms page
shows every form used across all projects:

```text
http://127.0.0.1:8000/forms/
```

When a specific project is selected, the Forms page only shows forms attached
to that project:

```text
http://127.0.0.1:8000/projects/awoostria-2026/forms/
```

Project forms can be created with Google Forms-style fields, moved through
`draft`, `published`, and `closed` states, or inherited from another project as
an editable draft copy. Closed and draft forms do not accept new submissions.
Each project keeps at least one timetable-source form so approved applications
can become timetable panels.

Users with `Admin`, `Board`, or `Event Manager` can review submitted
applications at `http://127.0.0.1:8000/review/applications/`. Approving an
application unlocks the applicant profile and creates an internal notification.
Staff can also reopen an application for applicant edits. The applicant can
edit only while the application is in the `reopened` state, and each resubmitted
edit is stored as a new version while older answers remain read-only.
Application detail pages show all stored versions for the applicant.
Notifications on `My Profile` are split into unread and read sections. Users can
mark notifications read, and notification links point back to related
applications, review pages, or volunteer shifts when available.

Only `Admin` users can manage the account access list at
`http://127.0.0.1:8000/accounts/`. The screen shows allowed Google accounts,
roles, active status, last login, and profile unlock state. Account creations
and role/active-status changes are recorded in an audit log. Admins can filter
the access list by e-mail, active status, and role. Admins can also import and
export accounts as CSV with these columns:

```csv
email,active,roles,notes
host@gmail.com,true,Host;Volunteer,Can help with late-night panels
```

CSV imports are validated before changes are applied. If any row has an invalid
e-mail address, active value, role, duplicate e-mail, or missing required
column, the import is blocked without partial changes. The `notes` column is
optional on import and is only visible to Admin users. Import uploads first show
a validation report with created, updated, unchanged, and rejected rows; Admins
must explicitly apply a valid preview before changes are written.

Admins can manually unlock or lock a user's profile from the account list after
the user has logged in at least once. Unlocking a profile creates an internal
notification for the user and records an audit entry.

The account page also includes recent account-change audit entries. Admins can
filter those changes by target account, actor e-mail, and action.

After approval, users can edit their profile at
`http://127.0.0.1:8000/profile/edit/`.
Profile detail pages are available for approved public profiles and staff
review. Staff can inspect applicant profiles from review pages. Regular users
only see profiles that are unlocked and opted into public visibility, and
contact handles stay hidden unless the profile owner enables them.
Profiles include optional pronouns, address, phone, personal e-mail, and
convention e-mail fields. Address details are only shown to the profile owner
and staff. Each profile can also store per-convention attendee type and roles,
so someone can be a fursuiter or sponsor for one project and have different
staff/host roles for another.

Signed-in users can browse the shared user directory, social media workspace,
and statistics pages from the sidebar navigation:

```text
http://127.0.0.1:8000/accounts/users/
http://127.0.0.1:8000/social-media/
http://127.0.0.1:8000/statistics/
```

The statistics page summarizes convention profile counts by project, attendee
type, and country.

The Social Media page is a lightweight publishing workspace for public-facing
updates. Users can save drafts with text, an optional embed URL, and optional
uploaded media. Publishing can happen immediately, or it can be scheduled for a
future time. Published posts create an immutable version snapshot and queue
publication records for external channels such as Telegram, Bluesky, and X.
Those queue records make it clear what is queued versus actually sent, and they
are intentionally local placeholders until real bot/API credentials and delivery
workers are configured.

Scheduled social posts can be processed with:

```bash
uv run --extra dev python manage.py publish_scheduled_social_posts
```

The Users page displays people as square tiles that only show profile images
and names. User color rules choose one color and where it applies: the tile
edge or tile interior. Rules can target attendee types (`Attendee`, `Sponsor`,
`Super Sponsor`, `Fursuiter`) or volunteer types (`None`, `Volunteer`,
`Deputy`, `Lead`, `Board Member`). Admins and Board users can manage those
color rules from:

```text
http://127.0.0.1:8000/setup/user-colors/
```

Roles, participant statuses, access benefits, and UI labels are configurable
from Setup. General Projects mode edits global defaults, while active project
mode edits local convention settings:

```text
http://127.0.0.1:8000/setup/roles/
http://127.0.0.1:8000/setup/statuses/
http://127.0.0.1:8000/setup/labels/
http://127.0.0.1:8000/projects/awoostria-2026/setup/roles/
http://127.0.0.1:8000/projects/awoostria-2026/setup/statuses/
http://127.0.0.1:8000/projects/awoostria-2026/setup/labels/
```

The settled role/status model is documented in `docs/roles-and-access.md`.

Admins and Board users can manage hotel room data from:

```text
http://127.0.0.1:8000/hotels/
```

The Hotels page is for persistent hotel facts: room names as shown on hotel
floor plans, room capacities, equipment/property lists, room combinations, and
one or more uploaded floor layout images per hotel. Floor layout images can be
edited or removed from the hotel detail page.

Each project also has project-specific room settings at:

```text
http://127.0.0.1:8000/projects/awoostria-2026/rooms/
```

Those settings are local to the convention project. Staff first choose which
reusable hotel records the project uses, then can rename a room for one event,
block a room for that event, and add multiple opening windows for different
days. Timetable placement rejects panels and volunteer shifts outside the
configured room opening windows.

Approved event applications create panels. Hosts can place their own panels in
the private placement round at a project timetable URL, for example:

```text
http://127.0.0.1:8000/projects/awoostria-2026/timetable/
```

Staff can switch timetable rounds from that page. The current rounds are:

- `private_placement`
- `host_negotiation`
- `public`

The timetable warns about overlapping panels placed in the same room.
For regular users, timetable host names are privacy-filtered profile labels.
Host e-mail addresses are only shown to staff.
Panels can also be assigned to event groups in Django admin. Grouped panels can
carry an order number and a recurrence label such as `Daily` or `Day 2 repeat`.
When a group requires order, the timetable warns staff if placed panels are out
of sequence. Staff can edit a panel's group, order, and recurrence metadata from
review pages or the timetable. Staff can create, edit, and inspect event groups
from the project page. Event group detail pages list assigned panels, placements,
recurrence labels, and ordering warnings.

The printable timetable is available at:

```text
http://127.0.0.1:8000/projects/awoostria-2026/timetable/print/
```

It renders visible panels in chronological order and includes volunteer shifts
for staff users only. Regular users get the same panel visibility as the normal
timetable and do not see staff-only volunteer layers.

Staff can also create volunteer shifts from the timetable page. Volunteer
shifts are shown in a separate timetable layer and can be placed into normal
rooms or room combinations.

Volunteer shifts include a needed-volunteers count. Staff can assign registered
users from the timetable, and assigned shifts appear under each user's
`My Profile` page. The demo seed includes example volunteer users and
pre-assigned shifts:

- `dance.helper@gmail.com`
- `stage.runner@gmail.com`

Users with the `Volunteer` role can browse and claim scheduled volunteer shifts
from a project page, or directly at:

```text
http://127.0.0.1:8000/projects/awoostria-2026/volunteer-shifts/
```

The list links to a dedicated shift detail page with role, time, room, notes,
lock state, staffing, and the user's own assignment status. Claiming is done
from that detail page and is blocked when a shift is full or overlaps with one
of the user's existing assigned shifts. Volunteers do not see other volunteers'
assignments on that page.

Staff can manage claims from the shift assignment page linked from the
timetable. Assignments can be `claimed`, `confirmed`, or `removed`; removed
assignments free capacity but remain visible to the affected user. Staff can
also lock a shift once coverage is final, which blocks further self-service
claims.

Token-scoped JSON exports are available for website integrations. Create an
`ExportToken` in Django admin, then use the token with one of these endpoints:

```text
http://127.0.0.1:8000/exports/public-timetable/<token>.json
http://127.0.0.1:8000/exports/public-profiles/<token>.json
http://127.0.0.1:8000/exports/volunteer-shifts/<token>.json
http://127.0.0.1:8000/exports/signage-reminders/<token>.json
http://127.0.0.1:8000/exports/role-status/<token>.json
```

Tokens only work for their configured export type. Public timetable exports stay
empty until the project timetable round is `public`. Volunteer shift exports
include coverage counts, but do not expose volunteer e-mails or profiles.
Signage reminder exports include active reminders within their display window,
ordered by priority and start time. Staff can create signage reminders from a
project page. Role/status exports include aggregate and consent-safe
participant status and benefit data without private contact fields.

Public timetable entries include safe grouped-event metadata when available:
group name, group slug, panel order inside the group, and recurrence label.
Internal scheduling warnings, staff notes, and host e-mail addresses are not
included in the public timetable JSON.

Public profile exports are disabled per project by default. Enable
`profile_exports_enabled` on a project to expose only approved users who
unlocked their profile and opted into public profile visibility. Contact handles
require both the project-level `profile_contact_exports_enabled` switch and the
user's own `show_contact_handles` consent. Profile exports do not include user
e-mail addresses.

Every export request creates an audit log entry in Django admin. Successful and
rejected requests are logged with export type, status code, remote address, user
agent, timestamp, and project/token links when available. Raw token values are
not stored in access logs; a SHA-256 token hash is stored instead.

Detailed integration and token rotation notes are in `docs/integrations.md`.
Staff can run a token health check with:

```bash
uv run --extra dev python manage.py check_export_tokens
```

## Design Priorities

- Google-only authentication.
- Allowlisted users with assigned roles.
- Internal notifications only, no email notifications.
- Google Forms-compatible field labels for easier imports.
- Project YAML import for fast convention setup.
- Multi-round timetable visibility.
- Public/export APIs for the official website and signage.
- Printable and layered timetable views.
- Convention-friendly profile pages and participation history.
