# maru TODO

Last updated: 2026-05-22

## Done

- Created clean-room `maru` repository under `Desktop/pretalx/maru`.
- Added product, architecture, security, and YAML import notes in `docs/`.
- Added Django project baseline with SQLite development setup.
- Added development login placeholder that enforces Gmail/Googlemail and the
  internal access list.
- Seeded `marton.pornoi@gmail.com` with `Admin`, `Board`, and `Event Manager`.
- Added personal dashboard page with archived participation placeholder.
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
- Expanded `seed_demo` into a richer interactive scenario:
  - demo host, DJ, and volunteer accounts with different roles
  - approved scheduled panels in several rooms
  - submitted and reopened applications for review/edit flows
  - public profiles with profile/fursuit image paths
  - confirmed, claimed, and open volunteer shifts
  - internal notifications for demo users
  - tests cover the richer seeded demo data
- Added first application submission flow:
  - submit an imported subproject form
  - store answers by original Google Forms label
  - show submitted applications in the personal dashboard
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
  - assigned shifts show under the personal dashboard
  - seeded demo data includes example volunteer users, shifts, and assignments
- Added volunteer self-service claiming:
  - approved volunteers can browse scheduled shifts with open capacity
  - volunteers can claim open shifts themselves
  - full shifts cannot be claimed
  - overlapping assigned shifts cannot be claimed
  - claimed shifts reuse the existing personal dashboard volunteer shift list
- Added staff confirmation and claim management:
  - assignments can be `claimed`, `confirmed`, or `removed`
  - staff can confirm volunteer claims
  - staff can remove assignments while keeping a visible record
  - removed assignments free shift capacity
  - staff can lock or reopen shifts
  - locked shifts cannot be claimed
  - assignment status appears under the personal dashboard
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
- Added clearer personal archive/history:
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
  - `My Profile` separates unread notifications from read notification history
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
- Added profile state filters on the account list:
  - Admin users can filter accounts by unlocked profile
  - Admin users can filter accounts by locked profile
  - Admin users can filter accounts that do not have a user yet
  - profile filters preserve selected values in the UI
  - tests cover unlocked, locked, and missing-user profile filtering
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
- Added account audit-log pagination:
  - recent account changes are paginated at 25 entries per page
  - pagination links preserve audit-log filters
  - invalid page values fall back through Django pagination handling
  - tests cover second-page results and filter-preserving pagination links
- Added staff-visible account history:
  - each account row links to a grouped account history page
  - recent change rows link to account history when the grant still exists
  - account history shows current account state and all recorded changes
  - Board users cannot open account history pages
  - tests cover grouped account history, list links, and permissions
- Added optional staff notes on access grants:
  - access grants now have Admin-only notes
  - notes are visible on the account list and editable on access grant forms
  - notes are included in account CSV export
  - notes are optional in account CSV import
  - note changes are captured in access grant audit snapshots
  - tests cover create, update, export, import, and audit snapshots with notes
- Added account import validation reports and preview mode:
  - uploaded account CSV files show a validation report before applying
  - report rows are classified as created, updated, unchanged, or rejected
  - validation report includes line number, account, status, roles, notes, and
    row-specific issues
  - invalid imports cannot be applied
  - valid imports require an explicit Apply import step
  - previewing a valid import does not write database changes
  - tests cover preview, apply, rejected rows, and no partial writes
- Added account import preview diff details:
  - updated rows show field-level before/after changes before applying
  - active, roles, and notes changes are formatted for Admin review
  - unchanged, created, and rejected rows stay concise
  - tests cover previewed active, role, and note diffs
- Added rejected-row CSV downloads for account imports:
  - blocked account imports offer a CSV download for rejected rows
  - rejected-row downloads include line, email, active, roles, notes, and issues
  - downloading rejected rows does not create or update access grants
  - tests cover rejected-row CSV output and no partial writes
- Added staff UI for export token rotation:
  - Admin and Board users can manage tokens from project pages
  - token management can create scoped export tokens
  - token rotation generates a new active token for an existing token record
  - token management can deactivate and reactivate tokens
  - raw tokens are only shown immediately after creation or rotation
  - Event Managers cannot manage export tokens
  - integration docs describe the project token page rotation process
  - tests cover create, rotate, deactivate, reactivate, and permissions
- Added clearer persistent navigation and Admin profile access:
  - top navigation moved into a left sidebar with grouped sections
  - redundant Personal links were removed from the sidebar
  - the profile card is the only sidebar route to the signed-in user's profile
  - the profile card does not display the user's e-mail address
  - general public links are ungrouped in the sidebar
  - account management moved from the sidebar into an Admin section on Users
  - project operations/setup links moved into a top sidebar project dropdown
  - project dropdown items show project name plus compact start/end dates
  - project-specific pages make the dropdown show the active project name
  - project-specific Users links keep the selected project context
  - Setup -> Hotels opens global hotel records in general context
  - Setup -> Con Spaces opens project hotel assignments in active-project context
  - profile settings moved onto profile pages instead of the sidebar
  - Admin users can edit profile settings for their own and other profiles
  - locked regular users remain blocked from profile editing
  - tests cover Admin locked-profile access and locked-user sidebar behavior
- Added dedicated profile pages:
  - signed-in users can open their own profile at `/profile/`
  - the sidebar profile card links to `My Profile`
  - own profile pages are visible even when the profile is not public
  - profile and fursuit pictures render inline on one page
  - owners can see their own contact details and private fursuit picture
  - tests cover own-profile picture rendering and sidebar links
- Added richer profile details:
  - profiles can store pronouns from a selectable list
  - profiles can store phone number, personal e-mail, convention e-mail, and address fields
  - country is selected from a fixed list
  - address details are only shown to owners and staff
  - convention profiles track attendee type per project
  - convention profiles track multiple assigned roles per project
  - Admin users can assign convention roles from profile edit pages
  - tests cover contact/address saving and convention role assignment
- Added Public navigation pages:
  - signed-in users can open the Users directory from the ungrouped sidebar links
  - signed-in users can open Social Media from the ungrouped sidebar links
  - signed-in users can open a Statistics page from the ungrouped sidebar links
  - Admin users can manage accounts from an Admin button group on Users
  - general Users shows all registered/access-listed users
  - project Users shows only people attached to the active project
  - statistics show convention profile totals by project, attendee type, and country
  - tests cover regular-user directory access and statistics rendering
- Added Social Media publishing workspace:
  - registered users can save social media drafts
  - posts support body text, one safe embed URL, and uploaded media
  - posts can be published immediately or scheduled for a future time
  - publishing creates an immutable version snapshot
  - publishing queues local publication records for Telegram, Bluesky, and X
  - post lists separate drafts, scheduled posts, and published posts
  - publication rows show whether external delivery actually happened
  - due scheduled posts can be processed with `publish_scheduled_social_posts`
  - queued records are ready for future bot/API workers without calling external services yet
  - tests cover navigation, drafts, publishing, scheduling, queue records, and draft visibility
- Added user directory tile colors:
  - the Users page now renders people as square tiles instead of a table
  - tiles use larger profile images with the name under the image
  - tiles only show names and profile pictures
  - tile border colors use configured attendee type rules
  - tile interior colors use configured volunteer type rules
  - color rules now use one selected color plus an edge/interior selector
  - volunteer type supports None, Volunteer, Deputy, Lead, and Board Member
  - default colors exist for common attendee and volunteer types when no custom rule exists
  - setup users can manage tile color rules under Setup -> Color Codes
  - tests cover layered tile colors, setup access, and regular-user denial
- Added clickable archive entries under the personal dashboard:
  - archived panel titles link to read-only detail pages
  - archive detail pages show project, year, title, and added date
  - archived details are restricted to the owning user
  - tests cover archive links, detail rendering, and owner-only access
- Added Hotels and project-specific room settings:
  - setup users can open a separate Hotels page
  - hotel rooms keep persistent names, capacities, and equipment/properties
  - hotels are reusable master records shared by multiple projects
  - projects select which hotels they use from their room settings page
  - hotels can store, edit, and remove multiple floor layout images by floor level
  - project room settings can rename rooms locally for one convention
  - project room settings can block rooms for one convention
  - project room settings can add multiple room opening windows
  - panel and volunteer shift placement validates room opening windows
  - timetable and public exports use project-local room names
  - tests cover floor layout upload/edit/delete, permissions, local names, reusable hotels, and room hours
- Added maru branding assets:
  - favicon and app icon files live under Django static files
  - the sidebar brand uses the main `maru_rectangle_full_logo.png` logo
  - duplicate sidebar brand text was removed because it is part of the logo
  - the shared website theme uses the logo navy, amber, and ivory palette
  - redundant root favicon pack files were removed
- Added project-aware Forms management:
  - the sidebar includes a Forms page in both general and active-project context
  - general Forms shows every form ever used across projects
  - active-project Forms shows only forms attached to the selected project
  - staff can create Google Forms-style forms and fields outside Django admin
  - forms support draft, published, and closed states
  - draft and closed forms do not accept application submissions
  - projects can inherit forms from another project as editable draft copies
  - inherited forms copy their field definitions without modifying the source form
  - each project keeps at least one timetable-source form for panel scheduling
  - tests cover general/project form lists, creation, field creation, inheritance, and timetable-source fallback
- Added configurable roles, statuses, benefits, and labels:
  - `docs/roles-and-access.md` records the settled V1 model
  - active allowlisted users can use profile and public/user-facing pages without project authority
  - Admin remains the only account/login access manager
  - Board keeps full project authority without account management
  - global role presets can be cloned into projects as editable local roles
  - project role assignments can grant module permissions such as forms, statuses, labels, and timetable management
  - ticket levels are modeled as Pending, Paid, Sponsor, Super Sponsor, and Infinity
  - fursuiter status is self-submitted and validated by Fursuit Support
  - benefits can target con-space access, check-in perks, and consent-safe exports
  - global labels can be overridden per project for visible renamings
  - YAML import supports roles, role assignments, benefits, status-benefit grants, and labels
  - role/status export tokens expose aggregate and consent-safe benefit data
  - access configuration changes are audit logged

## Next Slice

Project status:

1. Current requested foundation is implemented and verified.
2. New work should start from specific product decisions or UI polish requests.

Target user flow:

```text
user signs in with Google -> maru checks access grant roles
```

## Near-Term Backlog

- Decide whether project creation/editing should move from Django admin into
  maru staff screens.
- Decide whether hotel room combinations should get a richer editor outside
  Django admin.

## Future Expansion

- Add richer dashboard polish for repeated staff workflows.
- Add more complete project setup screens outside Django admin.
- Add richer staff-only operational timetable blocks beyond panels and
  volunteer shifts.

## Export / Signage Backlog

- Add optional staff UI for editing existing signage reminders.

## Safety Notes

- Do not copy pretalx code directly without checking license obligations.
- Keep Google OAuth identity separate from maru authorization.
- Do not add email/password registration unless the product requirement changes.
- Internal notifications only; avoid outbound email workflows for now.
