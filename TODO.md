# maru TODO

Last updated: 2026-05-18

## Done

- Created clean-room `maru` repository under `Desktop/pretalx/maru`.
- Added product, architecture, security, and YAML import notes in `docs/`.
- Added Django project baseline with SQLite development setup.
- Added development login placeholder that enforces Gmail/Googlemail and the
  internal access list.
- Seeded `marton.pornoi@gmail.com` with `Admin`, `Board`, and `Event Manager`.
- Added `My Events` page with archived participation placeholder.
- Added project setup models:
  - Project
  - Subproject
  - Hotel
  - Room
  - RoomCombination
  - FormField
- Added repeatable YAML import command:

  ```bash
  uv run --extra dev python manage.py import_project docs/example-project.yml
  ```

- Added tests for domain rules, login/access, YAML parsing, and project import.
- Added educational demo fixtures for several furry convention setups.
- Added `seed_demo` command.
- Added project list/detail pages for browsing imported demo data.
- Added first application submission flow:
  - submit an imported subproject form
  - store answers by original Google Forms label
  - show submitted applications in `My Events`
  - show read-only application detail pages
- Added staff review flow:
  - review queue for `Admin`, `Board`, and `Event Manager`
  - approve/reject actions
  - profile unlock on first approval
  - internal notifications on approval/rejection
- Added profile editing after approval:
  - display name
  - profile picture
  - fursuit picture
  - fursuit name
  - Telegram handle
  - Discord handle
  - short bio
  - basic public/export privacy flags
- Added first timetable foundation:
  - project timetable round, defaulting to `private_placement`
  - panels created from approved event applications
  - room or room-combination placement
  - host placement page for own panels
  - staff visibility for all panels
- Added timetable round controls and negotiation visibility:
  - staff can switch between `private_placement`, `host_negotiation`, and `public`
  - private placement shows hosts only their own panels
  - host negotiation shows all panels to approved hosts with limited detail
  - public round shows all panels to logged-in users
  - overlapping panels in the same room show a conflict warning
- Added volunteer shift timetable layer:
  - staff can create volunteer shifts
  - staff can place shifts into rooms or room combinations
  - shifts render separately from panels on the timetable
  - shift overlaps in the same room show conflict warnings
- Added volunteer assignment workflow:
  - shifts have a needed-volunteers count
  - staff can assign registered users to volunteer shifts
  - assigned users receive internal notifications
  - assigned shifts show under `My Events`
  - seeded demo data includes example volunteer users, shifts, and assignments
- Added volunteer self-service claiming:
  - approved volunteers can browse scheduled shifts with open capacity
  - volunteers can claim open shifts themselves
  - full shifts cannot be claimed
  - overlapping assigned shifts cannot be claimed
  - claimed shifts reuse the existing `My Events` volunteer shift list
- Added staff confirmation and claim management:
  - assignments can be `claimed`, `confirmed`, or `removed`
  - staff can confirm volunteer claims
  - staff can remove assignments while keeping a visible record
  - removed assignments free shift capacity
  - staff can lock or reopen shifts
  - locked shifts cannot be claimed
  - assignment status appears under `My Events`
- Added clearer volunteer shift detail pages:
  - each scheduled volunteer shift has a dedicated detail page
  - detail pages show role, staffing, lock state, time, room, and notes
  - volunteers claim shifts from the detail page
  - volunteers see only their own assignment status
  - staff can see assignment lists and jump to staff management
- Added timetable print view:
  - project timetables have a printable route
  - entries render in chronological order
  - print view includes panels according to the active timetable round
  - staff print view includes volunteer shifts
  - regular print views exclude staff-only volunteer layers
  - print-focused CSS hides navigation and print controls
- Added token-scoped public exports:
  - export tokens are scoped to a project and export type
  - public timetable JSON export requires a matching active token
  - public timetable export stays empty until the timetable round is `public`
  - volunteer shift JSON export exposes shift coverage counts
  - volunteer shift export does not expose volunteer e-mails or profiles
  - inactive or wrong-type tokens return 404
- Added signage reminder broadcast API:
  - signage reminders are scoped to a project
  - staff can create reminders with start/end display windows
  - signage JSON export requires a matching active token
  - export only includes active reminders inside their display window
  - reminders sort by priority, then start time
  - signage remains separate from internal notifications
- Added export audit logging:
  - export hits create access log entries
  - successful and rejected token requests are logged
  - logs record export type, status code, project/token link when available,
    remote address, user agent, and timestamp
  - raw token values are not stored; logs keep a SHA-256 token hash
  - admin list/filtering is available for export access logs
- Added profile export privacy controls:
  - public profile JSON exports use scoped export tokens
  - profile exports are disabled per project by default
  - only approved users with unlocked, public profiles are exported
  - profile picture and fursuit picture URLs follow profile privacy flags
  - contact handles require project-level and user-level consent
  - profile exports do not include e-mail addresses
- Added application reopen/edit flow:
  - staff can reopen an application for applicant edits
  - reopened applications create internal notifications
  - applicants can edit only their own reopened applications
  - resubmissions create a new application version
  - original submitted answers remain preserved as older versions
  - submitted, approved, and rejected applications remain read-only
- Added clearer `My Events` archive/history:
  - current applications are separated from application history
  - approved, rejected, and archived applications move out of active work
  - application lists show stored version counts
  - application detail pages render all versions read-only
  - archived participation is grouped by year and project
- Added safe profile links from approved application surfaces:
  - staff can inspect applicant profiles from review pages
  - regular users can open only unlocked profiles opted into public visibility
  - public profile views hide contact handles unless the owner opted in
  - timetable host labels no longer expose e-mail addresses to regular users
  - public profile fallbacks avoid using e-mail addresses as display names
- Added richer internal notifications:
  - notifications can link to related applications, review pages, and shifts
  - `My Events` separates unread notifications from read notification history
  - users can mark their own notifications read
  - users cannot mark another user's notification read
  - resubmitted applications notify staff reviewers
  - notification links are visible from unread and read sections
- Added first grouped/recurring event support:
  - staff can create event groups in Django admin
  - panels can be assigned to a group with an order number
  - panels can carry recurrence labels such as `Daily` or `Day 2 repeat`
  - review pages show panel scheduling metadata
  - timetable and print views show group and recurrence metadata
  - timetable and print views warn when required group order is broken
- Added event group import and staff management:
  - YAML imports can create or update event groups
  - import output reports imported event group counts
  - `docs/example-project.yml` includes event group examples
  - staff can edit panel group/order/recurrence metadata outside Django admin
  - ordered groups require a group order
  - duplicate order numbers inside the same group are rejected
- Added richer event group management:
  - staff can create and edit event groups from project pages
  - project detail pages list event groups
  - event group detail pages show assigned panels
  - event group detail pages show placement and recurrence overview
  - ordered group detail pages warn about missing order numbers
  - regular users cannot open event group management pages
- Added grouped timetable metadata to public exports:
  - public timetable JSON includes group name and slug
  - public timetable JSON includes panel order inside the group
  - public timetable JSON includes recurrence labels
  - public timetable JSON does not include staff-only group warnings
  - grouped export tests cover host e-mail privacy
- Added export documentation and token operations:
  - `docs/integrations.md` documents website/signage endpoints
  - public timetable grouped-entry JSON shape is documented
  - token rotation process is documented
  - `check_export_tokens` reports export token health
  - token health output does not expose raw token values
- Replaced the development-only login placeholder with Google OAuth support:
  - `/oauth/google/start/` starts a state-protected OAuth login
  - `/oauth/google/callback/` exchanges the Google code and verifies identity
  - authorization still depends on active `AccessGrant` records
  - unverified Google e-mail addresses are rejected
  - local development email login remains available behind
    `MARU_DEV_LOGIN_ENABLED`
  - README documents Google OAuth environment variables and redirect URI setup
  - tests cover OAuth success, denied identities, invalid state, and unverified
    e-mail addresses
- Added Admin-only account management:
  - `/accounts/` lists allowed Google accounts
  - account rows show roles, active status, last login, and profile unlock state
  - Admin users can create and edit access grants
  - Board users cannot manage the access list
  - account changes create `AccessGrantAuditLog` records
  - audit entries capture actor, target account, before state, and after state
  - tests cover account list access, create/update changes, audit logging, and
    Google-only account validation
- Hardened authentication and production defaults:
  - development email login is disabled when `MARU_DEBUG=0`
  - production defaults enable HTTPS redirect and secure cookies
  - production defaults enable HSTS, content-type nosniff, frame denial, and a
    same-origin referrer policy
  - `MARU_CSRF_TRUSTED_ORIGINS` supports comma-separated production origins
  - Admin users can open account audit-log detail pages with before/after state
  - Board users cannot open account audit-log detail pages
  - `docs/deployment.md` documents required production environment variables
  - tests cover production settings and audit-log detail permissions
- Improved account list operations:
  - Admin users can search allowed accounts by e-mail
  - Admin users can filter by active/inactive status
  - Admin users can filter by role
  - filters preserve selected values in the UI
  - tests cover e-mail, status, and role filtering
- Added account CSV import/export helpers:
  - Admin users can export the access list as CSV
  - Admin users can import CSV files with `email`, `active`, and `roles`
  - imported roles use semicolon separators, such as `Host;Volunteer`
  - imports create audit logs for created and updated accounts
  - invalid imports are blocked without partial changes
  - validation catches non-Google e-mail addresses, invalid roles, duplicate
    e-mail rows, invalid active values, and missing columns
  - Board users cannot import or export account data
  - tests cover CSV export, successful import, failed import, and permissions
- Added Admin profile unlock controls:
  - account rows show unlock/lock actions when the user exists
  - accounts that have never logged in cannot have a profile unlocked yet
  - unlocking a profile creates an internal notification
  - profile lock/unlock changes create audit entries with before/after state
  - Board users cannot unlock or lock profiles
  - tests cover unlock, lock, missing user, notifications, audit entries, and
    permissions
- Added richer audit-log filters:
  - account changes can be filtered by target account
  - account changes can be filtered by actor e-mail
  - account changes can be filtered by action
  - recent changes now show up to 25 filtered entries
  - tests cover target, actor, and action filters
- Added optional staff notes on access grants:
  - access grants now have Admin-only notes
  - notes are visible on the account list and editable on access grant forms
  - notes are included in account CSV export
  - notes are optional in account CSV import
  - note changes are captured in access grant audit snapshots
  - tests cover create, update, export, import, and audit snapshots with notes

## Next Slice

Improve account operations:

1. Add duplicate/import validation reports for account YAML/CSV flows.
2. Add a preview mode for account imports before applying changes.
3. Add profile state filters on the account list.
4. Add audit-log pagination once the list grows.
5. Add staff-visible account history grouping by target account.

Target user flow:

```text
user signs in with Google -> maru checks access grant roles
```

## Near-Term Backlog

- Add duplicate/import validation reports for account YAML/CSV flows.
- Add profile state filters on the account list.
- Add profile state filters on the account list.

## Timetable Backlog

- Add panel scheduling models.
- Add timetable visibility rounds:
  - private placement
  - host negotiation
  - public timetable
- Add timetable layers:
  - panels
  - volunteer shifts
  - signage/reminders
  - staff-only operational blocks
- Add richer staff UI for grouped/recurring events.

## Export / Signage Backlog

- Add staff UI for export token rotation.

## Safety Notes

- Do not copy pretalx code directly without checking license obligations.
- Keep Google OAuth identity separate from maru authorization.
- Do not add email/password registration unless the product requirement changes.
- Internal notifications only; avoid outbound email workflows for now.
