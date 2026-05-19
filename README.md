# maru

maru is a clean-room event operations platform for furry conventions. It is
inspired by the useful workflows in pretalx, but it uses convention-focused
language and structure from the start.

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

The project detail pages now include `Submit application` links for each
subproject. Submitted applications appear under `My Events`, split between
current applications and application history.

Users with `Admin`, `Board`, or `Event Manager` can review submitted
applications at `http://127.0.0.1:8000/review/applications/`. Approving an
application unlocks the applicant profile and creates an internal notification.
Staff can also reopen an application for applicant edits. The applicant can
edit only while the application is in the `reopened` state, and each resubmitted
edit is stored as a new version while older answers remain read-only.
Application detail pages show all stored versions for the applicant.
Notifications on `My Events` are split into unread and read sections. Users can
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
optional on import and is only visible to Admin users.

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
`My Events` page. The demo seed includes two example volunteer users and
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
```

Tokens only work for their configured export type. Public timetable exports stay
empty until the project timetable round is `public`. Volunteer shift exports
include coverage counts, but do not expose volunteer e-mails or profiles.
Signage reminder exports include active reminders within their display window,
ordered by priority and start time. Staff can create signage reminders from a
project page.

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
