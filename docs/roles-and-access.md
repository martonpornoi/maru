# Roles And Access

maru separates login access, authority roles, participant statuses, and visible
labels.

## Login Access

`AccessGrant` remains the Google-account allowlist. An active allowlisted user
can log in, edit their profile, and browse public/user-facing pages. Login
access alone does not grant project authority.

Admin is the only role that can manage login access and account allowlist data.
Board has full project authority, but cannot add or remove login access.

## Project Roles

Project roles are configurable definitions with stable permission keys. New
projects can explicitly clone the global defaults or a previous project's
configuration; the result becomes editable project-local configuration.

Default role presets:

- Admin
- Board
- Project Lead
- Department Lead
- Registration
- Volunteer Coordinator
- Scheduler
- Security
- Fursuit Support
- Theming
- Social Media
- Host

Permissions are module-level action keys such as `project.forms.manage`,
`project.applications.review`, `project.timetable.manage`,
`project.roles.manage`, and `project.statuses.manage`. Department leads can be
given scoped authority through project role assignments and optional scope
notes.

All role definition and assignment changes are audited immediately. V1 does not
add an approval queue for role changes.

## Participant Statuses

Participant statuses are separate from authority roles, but they can grant
benefits.

Ticket levels are ordered:

1. Pending
2. Paid
3. Sponsor
4. Super Sponsor
5. Infinity

V1 models selected and verified ticket levels, but does not create invoices,
process payments, expire payment windows, handle refunds, or enforce paid-user
capacity. Normal staff can move verified ticket levels upward; only Admin can
correct a verified ticket level downward.

Fursuiter access is self-submitted and then validated. Users provide fursuit
details such as species, and Fursuit Support can approve or reject the
fursuiter status. Approved fursuiter status can grant lounge access.

## Benefits

Benefits are configurable project records. A benefit can target:

- con-space access
- check-in perks, queues, or gifts
- consent-safe exports

Ticket levels and fursuiter statuses grant benefits through status-to-benefit
rules. Public exports expose only aggregate or consent-safe status data and do
not expose private contact fields or raw authority-role maps.

## Labels

Visible wording uses stable internal label keys. Global labels provide defaults,
and projects can override them locally. This supports convention-specific
renaming without changing database identifiers or permission behavior.
