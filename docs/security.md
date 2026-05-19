# Security Model

## Authentication

Only Google authentication is allowed. The application should reject non-Google
email addresses even if a provider misconfiguration lets them through.

Allowed domains:

- `gmail.com`
- `googlemail.com`

If the convention later uses Google Workspace domains, they should be added
explicitly to configuration.

## Authorization

Authorization is role-based with project/subproject scoping.

Global full-control roles:

- Admin
- Board

Operational roles:

- Event Manager
- Security
- Fursuit Support
- Themeing
- Host
- Volunteer
- Registered User

The initial seed account is:

```yaml
accounts:
  - email: marton.pornoi@gmail.com
    roles: [Admin, Board, Event Manager]
```

## Notifications

maru should not send email notifications. Notifications are internal records
with optional signage/display broadcast rules.

## Export API Rules

Exports to the official website and hotel signage must be:

- Token scoped.
- Read-only.
- Project scoped.
- Logged.
- Explicit about whether profiles, pictures, handles, or volunteer names are
  included.

## Data Protection

Private contact fields such as Telegram, Discord, email, and internal review
notes must not leak to public timetable or signage exports.

