# Current project state

Last updated: 2026-07-31
Phase: Page 2 Create organization implemented; product-owner inspection is the
gate before Page 3
Implementation status: The default browser exposes Sign in, the platform
organization inventory, and name-only Draft organization creation; the tested
backend/API foundation and previous experience remain preserved but unmounted

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

The product owner accepted the empty baseline and Page 1. Page 2 is implemented
on `codex/page-02-create-organization` under ADR 0032, IDN-012, and UX-015. The
default `maru.baseline_urls` experience now exposes:

- `/accounts/login/`: the only unauthenticated HTML page;
- `/admin/`: the only authenticated HTML page, restricted to active platform
  administrators;
- `/admin/organizations/new/`: the platform-administrator-only name form that
  creates one Draft organization;
- `/`: a redirect to `/admin/`; and
- POST `/accounts/logout/`: an action, not a content page.

The administration home contains Maru identity, the signed-in name, Sign out,
the organization inventory, its empty/populated/failure states, a Page 2 create
action, and a clear platform-access-not-participation boundary. It shows only
organization identity, lifecycle, series count, and edition count. It has no
global menu, setup guidance, edition selector, Django model directory, embedded
application, registration, volunteer, or convention-owned operational content.
Previous HTML routes are not mounted and return 404. Health, build, schema, and
versioned APIs remain available.

Page 2 asks only for the recognizable organization name. Maru normalizes the
name, generates a collision-safe bounded slug, and atomically creates the Draft
record plus its successful audit event. It uses English and UTC defaults and
blank optional properties. It creates no membership, Executive Board,
authority, series, edition, participation, registration, or workforce record.
IDN-012 requires a later workflow to provision or backfill Executive Board
representation before activation and to restrict property editing to active
Executive Board authority and platform administration.

The isolated `maru_rebuild_empty` PostgreSQL database is migrated through
organizations `0003` and contains exactly one account: active platform
administrator `admin`. No sample organization was added during verification,
so it contains zero organizations, series, editions, memberships,
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

## Verification

- 466 backend tests pass against PostgreSQL 17, including 40 focused Page 2,
  empty-baseline, and tenant-model checks.
- Branch-aware coverage is 90.02%, above the required 90% gate.
- Ruff format/lint pass for 256 files and strict mypy passes for 182 source
  files.
- Django system check, production-shaped deployment check, and migration drift
  check pass.
- OpenAPI 3.1 generation/validation and generated TypeScript types pass.
- Browser QA covers successful handle login, Page 1 navigation, Page 2 initial
  and empty-submit validation states, and the real 390-by-844 responsive layout.
  The expected headings, labelled form, boundary explanation, and POST-only
  sign-out are present; Page 2 has no horizontal overflow or runtime console
  warning/error. Automated tests cover successful creation so browser QA does
  not add a sample tenant to the owner's empty database.
- The preserved frontend still passes 20 component tests, TypeScript
  typecheck/generated-contract validation, and its Vite production build, but
  it is not mounted by the baseline.
- Documentation validation passes for 128 Markdown files and 188 unique
  requirement identifiers.
- Fresh migration apply passed through organizations `0003`, identity `0010`,
  and registration `0030` on `maru_rebuild_empty`; existing-database migration
  evidence remains in the pre-reset checkpoint.

## Known limits and production gates

- Page 2 intentionally permits Draft organizations without an Executive Board.
  No controlled-browser activation exists. The later governance workflow must
  provision or backfill representation and enforce IDN-012 before activation or
  organization-property editing.
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

1. Restart the owner's local Django server if it predates this branch, then
   inspect Page 2 through **Create organization** at `/admin/` and accept or
   revise its one-field boundary.
2. Do not design or implement Page 3 before that response.
3. After Page 2 acceptance, write the Page 3 Organization record contract. It
   must separate necessary organization properties from jurisdiction-specific
   imprint details and define the platform-administrator/Executive-Board edit
   boundary before implementation.
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
through UX-015, REG-001 through REG-022, HR-007/008/010, ADRs 0017 through
0032, the Page 1 and Page 2 contracts, and the authorization, events,
organizations, Convention work, registration, workforce, and demo-data module
documents.

Do not trust selected-edition state as authority; expose Django Groups as a
second role system; grant convention capabilities from platform staff status;
show raw UUIDs as primary UI labels; create readiness evidence through model
saves; trust browser payment return; mutate active registration configuration;
charge a wait-listed person; auto-roll a person to a higher price; publish
unapproved media; or bypass closure gates in production.
