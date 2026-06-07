# Integrations

This guide is for the official website, digital signage, and other read-only
consumers of maru data.

All export endpoints are token-scoped. Tokens are created in Django admin as
`ExportToken` records and are bound to one project and one export type.

## Endpoints

```text
/exports/public-timetable/<token>.json
/exports/public-profiles/<token>.json
/exports/volunteer-shifts/<token>.json
/exports/signage-reminders/<token>.json
/exports/role-status/<token>.json
```

Tokens only work for their configured export type. A wrong, inactive, or unknown
token returns `404`.

## Public Timetable

Public timetable exports stay empty until the project timetable round is
`public`.

Panel entries use this shape:

```json
{
  "type": "panel",
  "title": "Part One",
  "header_image": "/media/events/header-images/part-one.png",
  "starts_at": "2026-07-22T11:00:00+02:00",
  "ends_at": "2026-07-22T12:00:00+02:00",
  "location": "Panel Room A",
  "group": {
    "name": "Story Arc",
    "slug": "story-arc",
    "order": 1,
    "recurrence_label": "Daily"
  }
}
```

The `group` object is omitted when a panel is not grouped. Public timetable
exports include the submitted 16:9 event header image URL when one exists. They
do not include host e-mail addresses, internal scheduling warnings, or staff-only
notes.

## Public Profiles

Public profile exports are disabled per project by default. Staff must enable
`profile_exports_enabled` for the project. Only approved users with unlocked
profiles and `show_profile_publicly` enabled are exported.

Contact handles require both project-level `profile_contact_exports_enabled` and
the user's own `show_contact_handles` setting. Profile exports never include
user e-mail addresses.

## Volunteer Shifts

Volunteer shift exports are intended for website staffing displays. They expose
shift title, role, time, location, needed volunteer count, and confirmed
assignment count. They do not expose volunteer e-mail addresses or profile data.

## Signage Reminders

Signage reminder exports return active reminders whose display window contains
the current time. Consumers should poll this endpoint from signage players and
replace the displayed message list with the latest response.

## Role Status

Role/status exports are for official systems that need aggregate or
consent-safe access information. They include ticket-level counts, fursuiter
status counts, benefit counts, and public profile rows only for users with
unlocked public profiles. They do not expose e-mail addresses, private contact
fields, or raw authority-role assignments.

## Token Rotation

Admin and Board users can manage export tokens from a project page via
`Manage export tokens`. The page can create scoped tokens, rotate an existing
token, and deactivate or reactivate tokens. Raw token values are only shown
immediately after creating or rotating a token.

Use this process when a token might be exposed or when rotating credentials:

1. Create or rotate an export token from the project token page.
2. Deploy the new token to the website or signage consumer.
3. Confirm the consumer is reading successfully.
4. Deactivate old or unused tokens from the project token page.
5. Run the health check command and verify the old token is inactive.

```bash
uv run --extra dev python manage.py check_export_tokens
uv run --extra dev python manage.py check_export_tokens --project awoostria-2026
```

The health check reports project slug, token name, export type, active state,
last successful request time, and failed request count. It never prints raw token
values.

## Audit Logs

Every export request creates an `ExportAccessLog`. Successful and rejected
requests are logged with export type, status code, project/token link when
available, remote address, user agent, timestamp, and SHA-256 token hash. Raw
tokens are not stored in access logs.
