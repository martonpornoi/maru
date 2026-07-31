# Current project state

Last updated: 2026-07-31
Phase: Current implementation preserved; controlled page-by-page reset awaits
the product owner's baseline choice
Implementation status: Repository-controlled registration, reporting,
workforce onboarding, guided setup, management navigation, and closeout
evidence workflows are functional; external provider, infrastructure, load,
policy, and partner go/no-go gates remain

## Current outcome

On 2026-07-31 the product owner requested a controlled restart because repeated
administration-shell reorganizations had not produced a coherent experience.
The current source, documents, tasks, tests, migrations, generated assets, and
dirty working state are preserved at
`C:\Users\TheMw\AppData\Local\Temp\Maru-reset-snapshot-20260731-171759`.
The recovery folder includes a verified complete Git bundle, a binary-safe
tracked-change patch, the full repository-owned working-tree copy, Git status,
inventory, and SHA-256 manifests. Regenerable environments/caches are excluded.

No application code, working-tree history, or PostgreSQL data has been reset.
The next implementation action is deliberately blocked on one product choice:
retain the tested backend and expose an empty administration experience, or
create an empty codebase and re-earn every behavior. The crash-safe checklist
and page contract are in `docs/project/RESET_REBUILD.md`.

Maru is an executable Django/PostgreSQL modular monolith with versioned APIs,
React/TypeScript convention workflows embedded in Django administration, and a
neutral reference registration frontend.

`/admin/` is the canonical authenticated home and again renders the original
Django administration index. One collapsible sidebar exposes Convention work
and the permission-filtered specialist record directory on the index,
workflow pages, and model pages. Existing model paths such as
`/admin/identity/account/add/` remain stable. API-backed workflows render
inside the same shell at `/admin/workspace/` without their former React
sidebar, top bar, or duplicate workspace selector. Their inner pages now use
the same compact record-oriented modules, fields, tables, buttons, spacing,
and responsive language as specialist record pages. `/manage/`, `/staff/`, and
`/admin/records/` do not redirect or host alternate interfaces.

An active account may reach the administration home and embedded workflows,
but Django model pages retain staff/model permissions and API operations retain
Maru's scoped capabilities. A workspace-less account remains in a safe empty
state; an eligible active superuser receives the guarded one-time
convention-leadership ceremony contextually in Setup guide. The former global
Quick Start strip is removed. Staff status does not silently grant convention
capabilities.

Convention work provides:

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

## Verification

- 431 backend tests pass against PostgreSQL 17.
- Branch-aware coverage is 90.10%, above the required 90% gate.
- Ruff format/lint and strict mypy pass for 178 source files.
- Django system check, production-shaped deployment check, and migration drift
  check pass.
- OpenAPI 3.1 generation/validation and generated TypeScript types pass.
- 20 Convention work tests, TypeScript typecheck, and the Vite production
  build pass.
- Browser QA covers the original `/admin/` index and single sidebar, embedded
  `/admin/workspace/` workflows without nested navigation, desktop and
  390-pixel responsive behavior, Forms, access sharing/search, workspace-less
  administrator behavior, contextual first-authority ceremony, edition
  readiness, the real Marucon hierarchy, handle login, hidden staff questions,
  and restricted Infinity admission. No visible UUID, horizontal overflow, or
  runtime console error remained.
- Documentation validation passes for 117 Markdown files and 186 unique
  requirement identifiers.
- Fresh and existing-database migration apply passed for login handles,
  profile extensions, append-only/scope guards, and provenance guards.

## Known limits and production gates

- The recovery copy is in the operating system's temporary directory as
  requested. It is verified but can eventually be cleaned by the operating
  system; move it to durable storage before intentionally destroying the
  current working tree.

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

1. Choose the reset baseline in `RESET_REBUILD.md`: the recommended empty
   experience over the existing tested backend, or a genuinely empty codebase.
2. Choose whether the rebuild uses this working tree, a new branch, or a
   sibling worktree, then create a new empty database without altering `maru`
   or `marucon_rehearsal`.
3. Add a superseding UI-architecture ADR and implement only Sign in plus the
   agreed empty administration home before designing the next page.
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
`MARUCON_ADMIN_SCENARIO.md`,
requirements IDN-009/010, UX-009 through UX-012, REG-001 through REG-022,
HR-007/008/010, ADRs 0017 through 0029, and the authorization, events,
Convention work, registration, workforce, and demo-data module documents.

Do not trust selected-edition state as authority; expose Django Groups as a
second role system; grant convention capabilities from platform staff status;
show raw UUIDs as primary UI labels; create readiness evidence through model
saves; trust browser payment return; mutate active registration configuration;
charge a wait-listed person; auto-roll a person to a higher price; publish
unapproved media; or bypass closure gates in production.
