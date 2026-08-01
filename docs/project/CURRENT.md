# Current project state

Last updated: 2026-08-01
Phase: Page 4 Create convention series and progressive navigation revision
implemented; product-owner inspection is the gate before Page 5
Convention-series record
Implementation status: The default browser exposes Sign in, the platform
organization inventory, complete optional Draft creation, linked organization
records, audited profile editing, protected empty-Draft deletion, and nested
convention-series creation; the tested backend/API foundation and previous
experience remain preserved but unmounted

## Current outcome

On 2026-07-31 the product owner requested a controlled restart because repeated
administration-shell reorganizations had not produced a coherent experience.
The current source, documents, tasks, tests, migrations, generated assets, and
dirty working state are preserved at
`C:\Users\TheMw\AppData\Local\Temp\Maru-reset-snapshot-20260731-171759`.
The recovery folder includes a verified complete Git bundle, a binary-safe
tracked-change patch, the full repository-owned working-tree copy, Git status,
inventory, and SHA-256 manifests. Regenerable environments/caches are excluded.

The complete pre-reset state is also durable as commit `548f15a` on
`codex/pre-reset-20260731`. The owner selected the empty-experience option and
implementation continues on `codex/page-by-page-rebuild`.

The product owner accepted the empty baseline and Pages 1 through 3. Page 4 is
implemented on `codex/page-04-create-convention-series` under ADRs 0035 and
0036 plus UX-018 and UX-019, using the preserved Convention Series vocabulary
and compact navigation pattern inside the reviewed organization-scoped
journey. The default `maru.baseline_urls` experience now exposes:

- `/accounts/login/`: the only unauthenticated HTML page;
- `/admin/`: the only authenticated HTML page, restricted to active platform
  administrators;
- `/admin/organizations/new/`: the platform-administrator-only complete
  creation form that keeps organization name as its sole required value;
- `/admin/organizations/<slug>/`: the platform-administrator-only complete
  organization record and profile-update form;
- `/admin/organizations/<slug>/series/new/`: the platform-administrator-only
  convention-series creation form scoped to that organization;
- POST `/admin/organizations/<slug>/delete/`: confirmed deletion restricted to
  an empty Draft with no protected relationship;
- `/`: a redirect to `/admin/`; and
- POST `/accounts/logout/`: an action, not a content page.

The administration home contains Maru identity, the signed-in name, Sign out,
the organization inventory, its empty/populated/failure states, and a clear
platform-access-not-participation boundary. Pages 1 through 4 share a global
**Organizations** row with an adjacent compact **+ Add** action. Pages 3 and 4
also show a section named for the selected organization with **Organization
record** and **Convention series**, plus the scoped series **+ Add** action.
Exactly one action identifies the current page. The desktop sidebar now begins
at normal viewport padding rather than inside a centered 88-rem grid; narrow
layouts stack the same destinations above the content.
The inventory shows only organization identity, lifecycle, series count, and
edition count. It has no setup guidance, edition selector, Django model
directory, embedded application, registration, volunteer, or convention-owned
operational content. Previous HTML routes are not mounted and return 404.
Health, build, schema, and versioned APIs remain available.

Page 2 requires only the recognizable organization name and optionally accepts
public description; legal name/address/representative; registration, tax, and
additional imprint wording; website/email/E.164 telephone; country, languages,
and time zone. Maru normalizes the name, generates a collision-safe bounded
slug, validates the complete model, and atomically creates the Draft plus its
successful audit event. Audit metadata contains field names, not entered legal
or contact values. English and UTC remain fallbacks. Page 2 creates no
membership, Executive Board, authority, series, edition, participation,
registration, or workforce record. IDN-012 requires a later workflow to
provision or backfill Executive Board representation before activation and to
restrict property editing to active Executive Board authority and platform
administration.

Page 3 links each inventory name to its organization record and prepopulates
the complete Page 2 profile. Saving locks and reloads the record, repeats
platform authorization, normalizes and validates the profile, and changes
neither stable slug nor lifecycle. Only actual changed fields are written and
audited; their values are excluded, and an unchanged save writes and audits
nothing. Deletion is a separate POST requiring the current name exactly and an
explicit acknowledgement. It succeeds only for Draft lifecycle and cannot
cascade: every direct organization relationship is protected, so a series,
edition, membership, authority, participation, registration, workforce,
communication, or other related record refuses deletion. Delete plus its
UUID-only audit evidence are atomic. Closure and data exit remain future
workflows.

Page 3 now presents an organization-scoped Convention series section before
the long profile, with empty/populated states and **+ Add series** unless the
parent is Closed. Page 4 carries over the preserved series name, description,
website, contact email, and availability vocabulary while taking the parent
only from the authorized URL and generating its bounded stable slug in code.
Only name is required; availability defaults Active and means eligible for a
future edition, not published. The service repeats platform authorization,
locks and refuses a Closed parent, validates the complete model, and atomically
audits field names without values. It creates no edition, governance,
membership, authority, participation, registration, volunteer, onboarding, or
workforce record. Page 5 will own existing-series changes.

The isolated `maru_rebuild_empty` PostgreSQL database is migrated through
organizations `0004` and contains exactly one account, active platform
administrator `admin`, plus the owner's Draft `MaruCon` organization with slug
`marucon`. Its newly added optional profile values are blank and existing values
were not rewritten. The database contains zero series, editions, memberships,
participations, registration configurations, registrations, volunteer
applications, departments, positions, and workforce assignments. The `maru`
and `marucon_rehearsal` databases remain unchanged.

All application superusers are now explicitly classified as platform
administrators rather than inferred from record order. They receive global
platform-policy decisions without stored convention grants, may be attributed
actors, and are rejected as convention membership, authority, participation,
registration, volunteer, onboarding, or workforce subjects. The one-shot
bootstrap therefore appoints only the distinct human Chair; the platform
administrator remains outside the convention. Self-only and future
break-glass-required capabilities do not follow from platform status.

## Preserved backend and pre-reset experience

The following capabilities remain implemented and tested, but descriptions of
their pages refer to preserved source rather than the currently mounted
experience.

Maru is an executable Django/PostgreSQL modular monolith with versioned APIs,
React/TypeScript convention workflows embedded in Django administration, and a
neutral reference registration frontend.

In the preserved pre-reset URL configuration, `/admin/` rendered the original
Django administration index. One collapsible sidebar exposed Convention work
and the permission-filtered specialist record directory on the index,
workflow pages, and model pages. Existing model paths such as
`/admin/identity/account/add/` remain stable. API-backed workflows render
inside the same shell at `/admin/workspace/` without their former React
sidebar, top bar, or duplicate workspace selector. Their inner pages now use
the same compact record-oriented modules, fields, tables, buttons, spacing,
and responsive language as specialist record pages. `/manage/`, `/staff/`, and
`/admin/records/` do not redirect or host alternate interfaces.

In that preserved experience, an active account could reach the administration
home and embedded workflows,
but Django model pages retain staff/model permissions and API operations retain
Maru's scoped capabilities. A workspace-less account remains in a safe empty
state; an eligible active superuser receives the guarded one-time
convention-leadership ceremony contextually in Setup guide. The former global
Quick Start strip is removed. Staff status does not silently grant convention
capabilities.

Preserved Convention work provides:

- one shared administration navigation rather than nested global menus;
- a separate Forms area for attendee registration, staff-assisted intake,
  volunteer applications, and onboarding documents;
- Today, People, Organization structure, My registration, Registration,
  Reports & badges, Security history, Setup guide, and specialist-record
  navigation;
- password-confirmed, exact-scope-confirmed first Chair bootstrap through the
  same one-shot audited service as the operator command;
- capability-aware edition lifecycle controls with valid next states,
  consequences, mandatory reasons, and terminal-action acknowledgement;
- country and attendee-level reporting plus a minimized, audited badge CSV;
- contextual **Manage access** for principals with
  `authorization.manage_roles`;
- exact-email assignment to reusable scoped convention groups such as Board,
  Front Desk, Registration, Treasurer, department roles, and Volunteer;
- optional expiry, reason, independent approval, audited atomic replacement,
  and immediate reasoned removal; and
- human names, emails, labels, slugs, and references instead of visible UUIDs.

Access sharing grants system capabilities only. It does not appoint someone to
a workforce position, satisfy an NDA, consume headcount, create a reporting
relationship, or add official convention capacities. Those consequences
remain in the workforce appointment workflow.

The setup guide also contains an edition closeout readiness review for privacy,
finance, operations, security, and jurisdiction/safeguarding. The operator
enters a readable evidence reference and review summary. Maru takes
organization/edition scope from the selected workspace and records the
signed-in reviewer and server timestamp automatically. The readiness-gate
Advanced-record table is tenant/edition scoped, read-only, shows reviewer
names, and no longer offers a raw Add form with UUID or timestamp fields.

The registration boundary includes versioned and removable draft form items,
volunteer/early-bird/normal offers, time-limited paid reservations, FIFO
wait-list promotion, reasoned payment exceptions, authenticated provider
evidence, notifications, profiles, multiple fursuits, moderated reusable
images, public attendee consent, country/language data, staff-assisted account
creation, reporting, credentials, offline check-in, privacy operations, and
evidence-gated archival. Reviewed edition-owned profile extensions let an
attendee or authorized registration staff append missing current information
under per-field writer policy without mutating the submitted answers.
Infinity, payment, entitlement, role, capacity, and restriction facts remain
authoritative records rather than extension answers.

The workforce boundary includes one-shot first Chair bootstrap, ten reusable
furry-convention position templates, departments/reporting lines, publishable
opportunities, applications, reviewed PDF agreements, headcount, dual-control
position activation, scoped role assignments, and participation capacities.
The exceptional first-authority action is available as a guarded Management
Console ceremony; `bootstrap_convention` remains its operator/recovery
fallback, and neither path exposes ordinary editable authority records. A
minimized Organization structure projection shows nested departments,
positions, several holders, and multi-department roles without private HR or
contact data.

The local/test demonstration fixture supplies synthetic records across all
registered admin models. It includes familiar starter access groups and
assignments, independent access approvers, populated registration/finance/
workforce/profile-extension evidence, and the documented static local credential
`Z7!maru-demo-fixture-2026`. Demo seeding is unavailable in production.

A separate local/test Marucon rehearsal creates its deterministic
administrator as the first account, then Marucon Organizers, the Marucon
series, Marucon 2031, a distinct public-handle Chair, all explicitly
acknowledged public roster accounts, nested departments, dual-controlled
positions, a published template, and an inherited active registration. The
live run in the isolated `marucon_rehearsal` database produced 206 roster
accounts, 23 departments, 92 positions, and 245 assignments. The importer
copies public handles, department descriptions, and role labels only; it
excludes images/contact data and automated tests use a synthetic miniature.

## Accepted decisions

- ADRs 0001–0019 define the modular monolith, tenant/edition boundary,
  capability authorization, audit/outbox, registration, identity, payment,
  communications, privacy, credentials/closure, reporting, and workforce
  foundation.
- ADR 0020 retains guided locale/data entry and explicit staff account
  creation; its former Django-admin first-authority adapter is superseded, and
  ADR 0024 restores the behavior as a guarded Convention work ceremony.
- ADR 0021 defines Maru's owned accessible platform identity and behavior-only
  use of the legacy prototype.
- ADR 0022's global Quick Start is superseded. ADR 0024 retains the guarded
  first-authority ceremony; ADR 0027 moves setup guidance into Setup guide.
- ADR 0023 introduces a Forms hub and scoped Drive-like role sharing. ADR 0026
  supersedes its standalone React shell and route placement.
- ADR 0024 adds the guarded first-authority ceremony and reasoned edition
  lifecycle panel without granting convention authority from staff status.
- ADR 0025's React-at-`/admin/` design is superseded.
- ADR 0026 restores the original `/admin/` index and single Django navigation,
  embeds API-backed Convention work at `/admin/workspace/`, keeps model URLs
  stable, and removes the former standalone routes without redirects.
- ADR 0027 aligns Convention work inner pages with specialist records and
  removes duplicate global setup chrome.
- ADR 0028 adds optional case-insensitively unique login handles, bounded
  local public-roster import, and the minimized hierarchy projection.
- ADR 0029 adds reviewed, versioned profile extension fields and append-only
  values while keeping submitted answers and authoritative benefits immutable.
- ADR 0030 supersedes ADRs 0026 and 0027 for the mounted browser experience,
  retaining the backend while reducing the default HTML surface to Sign in and
  one empty staff home.
- ADR 0031 restores Page 1 as a platform-administrator-only organization
  inventory, explicitly separates platform authority from convention
  participation, and supersedes the platform-controller participation portions
  of ADRs 0019, 0020, and 0024.
- ADR 0032 adds Page 2 as an audited, name-only Draft organization command and
  defers Executive Board provisioning and organization-property editing to
  their reviewed workflows.
- ADR 0033 supersedes ADR 0032 only for Page 2 presentation and optional field
  scope, adding shared Organizations/+ Add navigation and the complete initial
  legal/imprint, contact, and locale profile.
- ADR 0034 partially supersedes ADR 0033's navigation layout and edit deferral,
  adding the linked Page 3 record, audited profile changes, and confirmed
  protected empty-Draft deletion.
- ADR 0035 supersedes ADR 0020 only for the current series-creation browser
  adapter, nesting Page 4 under Page 3 and keeping organization/slug code-owned.
- ADR 0036 supersedes ADRs 0034 and 0035 only for navigation placement and
  current state: mounted pages appear at their real global or selected-context
  scope, and the desktop sidebar aligns to ordinary viewport padding.

## Verification

- 518 backend tests pass against PostgreSQL 17; 79 focused Page 1–4 checks
  pass.
- Branch-aware coverage is 90.23%, above the required 90% gate.
- Ruff format/lint pass for 258 files and strict mypy passes for 182 source
  files.
- Django system check, production-shaped deployment check, and migration drift
  check pass.
- OpenAPI 3.1 generation/validation and generated TypeScript types pass.
- Browser QA covers Page 3's selected-organization navigation and series empty
  state plus Page 4's parent context, scoped current add action, one required
  name, optional fields, Active default, boundary text, and actions. At 1920
  pixels the sidebar begins 40 pixels from the viewport edge; at 390 by 844 it
  stacks at 16 pixels. Both have no horizontal overflow or browser runtime
  warnings/errors. The menu add action navigates from Page 3 to Page 4. The live
  form was not submitted; MaruCon remains unchanged with zero series.
- The preserved frontend still passes 20 component tests, TypeScript
  typecheck/generated-contract validation, and its Vite production build, but
  it is not mounted by the baseline.
- Documentation validation passes for 140 Markdown files and 188 unique
  requirement identifiers.
- Fresh migration apply passed through organizations `0004`, identity `0010`,
  and registration `0030` on `maru_rebuild_empty`; the existing MaruCon Draft
  retained its values, and broader existing-database evidence remains in the
  pre-reset checkpoint.

## Known limits and production gates

- Page 2 intentionally permits Draft organizations without an Executive Board.
  No controlled-browser activation exists. The later governance workflow must
  provision or backfill representation and enforce IDN-012 before activation,
  then extend Page 3 property editing to active Executive Board authority.
- MaruCon was created before the complete profile fields were added, so those
  values are blank. Page 3 now provides authorized editing for that existing
  organization; browser QA deliberately did not fill or delete it.
- Page 3 deletion is intentionally unavailable once any protected related
  record exists. Such organizations require the future closure/data-exit
  workflow rather than cascading deletion.
- Page 4 creates identity only. Series editing, deactivation, transfer,
  publication, deletion/closure, and dated edition creation remain Page 5 and
  later reviewed workflows.
- The verified recovery copy remains in the operating system's temporary
  directory and can eventually be cleaned, but the same pre-reset state is now
  durable in Git commit `548f15a` and branch `codex/pre-reset-20260731`.

- No concrete payment vendor has been selected or certified. Production
  endpoint, credentials, webhook secret, sandbox evidence, and
  finance/security approval remain external gates.
- SMTP, ClamAV, object storage/lifecycle, scheduler, worker supervision,
  telemetry, alerts, relay devices/client, scanners, printers, secrets, and
  restore procedures must be installed and rehearsed in the target
  environment.
- Production-shaped load evidence and first-partner jurisdiction, privacy,
  finance, safeguarding, security, operations, and event-leadership approval
  remain mandatory.
- Badge data export exists; badge layout/building, stock custody, bundled
  printing, and printer integration do not.
- Transfer, admission-product change, and repricing remain intentionally
  unavailable until their full finance workflows exist.
- Workforce qualifications, availability, shifts, work records, assignment
  ending/replacement, approval notifications, and richer hierarchy UX remain.
- Programme, timetable, venue catalogue, team inboxes, announcements, and
  credentialed read projections remain planned modules.
- Access sharing currently assigns existing accounts only. Staff-assisted
  registration can explicitly create an unverified account, but a
  production-grade expiring invitation/password-setup flow remains required.
- Specialist records still host several low-frequency setup forms. They should
  move behind purpose-built workflows incrementally rather than duplicating
  domain commands in Django model saves.
- The suite emits Django's 6.0 transition warning for the default URL-field
  scheme. Choose and test the HTTPS-default compatibility setting before the
  Django 6 upgrade.

Maru must not receive production personal data or be described as
production-approved until these deployment and governance gates pass.

## Smallest sensible next actions

1. Inspect Page 3's MaruCon Convention series section and Page 4 at
   `/admin/organizations/marucon/series/new/`; accept or revise them without
   submitting the live form unless a real MaruCon series is now wanted.
2. Do not design or implement Page 5 before that response.
3. After Page 4 acceptance, write the Page 5 Convention-series record contract.
   It must define stable identity, editing/deactivation, history protection,
   organization ownership, authorization, audit, and failure states before
   implementation.
4. Use the retained `marucon_rehearsal` database and role accounts for
   education, permission review, and usability feedback; turn findings into
   stable requirements before extending the hierarchy editor.
5. Select the first partner, jurisdiction, hosted payment provider,
   SMTP/storage/scanner topology, forecast, and named operational owners.
6. Certify provider and infrastructure failure paths, representative load,
   backups/restores, secret rotation, offline arrival, and closure.
7. Provision independently approved retention, minor, refund, restriction,
   and readiness policies.
8. Build badge layout/batch-printing only after the first partner confirms its
   printer, stock, fulfillment, and visual-template requirements.
9. Prioritize the next purpose-built setup/approval screen from real partner
   testing rather than exposing command-owned raw records.

## Resume instructions

Read `AGENTS.md`, this file, `RESET_REBUILD.md`, `ROADMAP.md`,
`MARUCON_ADMIN_SCENARIO.md`, requirements IDN-009 through IDN-012, UX-009
through UX-019, REG-001 through REG-022, HR-007/008/010, ADRs 0017 through
0036, the Page 1 through Page 4 contracts, and the authorization, events,
organizations, Convention work, registration, workforce, and demo-data module
documents.

Do not trust selected-edition state as authority; expose Django Groups as a
second role system; grant convention capabilities from platform staff status;
show raw UUIDs as primary UI labels; create readiness evidence through model
saves; trust browser payment return; mutate active registration configuration;
charge a wait-listed person; auto-roll a person to a higher price; publish
unapproved media; or bypass closure gates in production.
