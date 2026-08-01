# Maru production consolidation

Status: Active master checklist  
Branch: `codex/production-consolidation`  
Base: `327a7d63574d0118356a0fd11ca5a316d78b2aed`  
Started: 2026-08-01  
Decision: ADR 0037

This is the crash-safe delivery map for turning the retained Maru foundation
into one understandable convention operating platform. Update this file after
every meaningful implementation slice. `docs/project/CURRENT.md` remains the
short handoff; this file carries the detailed forward plan.

## Product sentence

Maru is the authoritative, auditable, API-first operating record for a furry
convention: people register once per edition, teams plan through shared domain
objects, on-site work stays coordinated, and annual public frontends can change
without reimplementing convention rules.

## Non-negotiable boundaries

- One authenticated administration namespace and one navigation system.
- Platform administration is not convention participation.
- Organization data is tenant-scoped; edition data is additionally
  edition-scoped; department and resource restrictions narrow access further.
- Sensitive HR, legal, safety, medical, wellbeing, financial, and identity data
  is purpose-separated and denied by default.
- Every privileged mutation uses an application service, transaction,
  human-readable audit event, and outbox event where downstream consumers may
  care.
- One attendee registration per person and edition. Contribution applications
  are separate typed processes.
- Departments receive projections and layers over shared records, not isolated
  mini-apps.
- All examples, tests, and screenshots use synthetic people. Public volunteer
  rosters are not copied into fixtures.
- External systems remain replaceable adapters; Maru is the source of truth for
  decisions, state, messages, and evidence that belong to convention work.
- A feature is not described as production-ready until its infrastructure,
  privacy, security, recovery, load, and operating evidence passes.

## Repository and branch disposition

| Ref | Relationship | Use |
| --- | --- | --- |
| `main` / `origin/main` at `ca37acb` | Ancestor | Stable modern foundation checkpoint. Already contained here. |
| `codex/pre-reset-20260731` at `548f15a` | Ancestor | Preserved rich browser behavior and API workflows. Reference selectively. |
| Page 0 through Page 4 local branches | Linear ancestors | Keep as accepted interaction landmarks. Do not merge them again. |
| `origin/legacy/github-main-462e7ba` | Unrelated history | Early prototype archaeology only. |
| `origin/legacy/local-final-2026-07-29` | Unrelated history | Best timetable, room, application, shift, export, and signage interaction reference. Never merge its migrations or global-project model. |

The current branch is the only consolidation line. When a legacy behavior is
reused, add a modern requirement and test it against current authorization and
tenant boundaries.

## Honest capability ledger

The state vocabulary is deliberately small:

- **Mounted** — reachable in the current production/default URL set.
- **API-only** — supported through a current API but not the coherent browser
  journey.
- **Preserved/unmounted** — tested or implemented in the repository but absent
  from the default browser experience.
- **Partial** — a useful kernel exists but the described workflow is incomplete.
- **Absent** — no authoritative current module/model/API/workflow exists.
- **Deployment-gated** — code exists but external service or operating evidence
  blocks a production claim.

| Capability | State on 2026-08-01 | Evidence / next dependency |
| --- | --- | --- |
| Organization and series Pages 1–4 | Mounted | Accepted baseline views, services, audit, integration tests. |
| Convention-series record | Absent | Milestone 1, Page 5. |
| Edition lifecycle | API-only | `maru.events`; creation still lacks shared audited command. |
| Edition browser workspace | Absent | Milestone 1, Pages 6–7. |
| Organization representation | Partial | Requirement and rehearsal data exist; no organization-level governance workflow. |
| Department hierarchy | API-only | Workforce model/projection and rehearsal exist; editor is unmounted. |
| Department/resource authorization | Partial | Organization and edition grants exist; department/resource constraints do not. |
| Effective-access explanation | Absent | UX-020; depends on scope v2 for full fidelity. |
| Attendee registration | Preserved/unmounted | Large tested domain and headless API; deployment gates remain. |
| Registration extension fields | API-only | Append-only, permission-aware implementation exists. |
| Generic application/form portfolio | Absent | KNO-009 and REG-023. |
| Programme intake/review | Absent | PRG-001–007. |
| Venues and mergeable spaces | Absent | VEN-001, VEN-002, VEN-008. |
| Timetable and shifts | Absent | SCH-001–010; legacy is interaction evidence only. |
| Logistics/storage | Absent | LOG-001–008. |
| Governed document library | Absent | Workforce onboarding upload is not a knowledge library. |
| Notifications | API-only | Canonical service notifications exist. |
| Team conversations and on-site messaging | Absent | Needs scoped inbox/thread domain and delivery adapters. |
| Credentials/offline check-in | API-only | Tested domain; hardware, printing, recovery, and load gates remain. |
| Audit kernel | API-only / partial UI | Append-only integrity exists; human activity timelines are missing. |
| Stable API/OpenAPI | Partial | Strong current contract; new domains and organization/series writes absent. |
| Production infrastructure | Deployment-gated | Provider selection, SMTP, object storage, scanner, workers, secrets, monitoring, restore, load, and legal/security review. |

Update this table whenever code changes state. Do not leave a capability marked
Mounted when its route is removed.

## Information architecture

The same left navigation progressively reveals only the selected scope:

```text
Platform
└─ Organizations                         + Add
   └─ Selected organization
      ├─ Organization record
      ├─ Convention series                + Add
      ├─ Representation & access
      ├─ Venues and year-round assets
      └─ Documents
         └─ Selected series
            ├─ Series record
            └─ Convention editions          + Add
               └─ Selected edition
                  ├─ Overview
                  ├─ People & departments
                  ├─ Registration
                  ├─ Applications
                  ├─ Programme
                  ├─ Timetable
                  ├─ Shifts & tasks
                  ├─ Venue operations
                  ├─ Logistics
                  ├─ Documents
                  ├─ Communications
                  ├─ Reports
                  ├─ Activity
                  └─ Settings & access
```

Only mounted destinations appear. A missing domain remains absent from the menu
rather than linking to a placeholder. Search and breadcrumbs preserve context.
Narrow screens stack the menu and content without horizontal overflow.

## Shared page contract

Every management page must define and test:

1. stable purpose and requirement identifiers;
2. trusted platform, organization, series, edition, department, and resource
   scope;
3. breadcrumb and exactly one current navigation action;
4. concise title, state, owner, and last meaningful modification;
5. effective-access summary and contextual Manage access action when allowed;
6. loading, empty, success, validation, permission-denied, stale-write,
   dependency-failure, and archived/read-only states;
7. keyboard operation, focus order, semantic labels, non-color state, and
   390-pixel behavior;
8. field type, bounds, normalization, classification, writer, retention, and
   error text;
9. application-service command, audit evidence, domain event, and API parity;
10. tenant, edition, department, field, and resource authorization tests;
11. rollback, optimistic concurrency, and idempotency behavior where relevant;
12. documentation, activity wording, observability, and recovery implication.

## Effective-access header

The header answers four questions without teaching users capability codes:

- Who can view this?
- Who can change it?
- Who can comment, review, or approve?
- Why do I personally have or lack each action?

Example display:

```text
Access
View: Executive Board, Events & Programming, Stage Tech collaborators
Edit: Events & Programming leads
Comment: Stage Tech, Security, Logistics
Approve: Programme reviewers
[Why can I access this?] [Manage access]
```

The values are computed from policy. The expanded explanation may name role
bundles and departments; it names people only when the viewer can already see
those memberships. Restricted cases do not advertise their subject or member
list. Platform oversight is labeled separately from participation, and a
reasoned sensitive read appears in Activity.

## Awoostria reference structure

The first reusable organization template has no real accounts and contains:

```text
Executive Board
└─ Helper Board
   ├─ Art
   ├─ Charity
   ├─ Ceremonies
   ├─ Dealers' Den
   ├─ Decorations
   ├─ Events & Programming
   ├─ Front Desk
   ├─ Fursuit Support
   ├─ Graphics Design
   ├─ Human Resources
   ├─ IT
   ├─ Legal & Compliance
   ├─ Logistics
   ├─ Maid Cafe
   ├─ Multimedia
   ├─ PEER
   ├─ Registration
   ├─ Security
   ├─ Social Media
   ├─ Stage Tech
   └─ Story
```

Departments can nest further. Each department supports multiple leads,
deputies, and volunteers. A person may hold several time-bounded positions in
several departments. The template is editable and is not a claim about the
legal reporting structure of every organizer.

## Canonical people model

Keep these concepts separate:

- `Account`: platform identity and authentication.
- `OrganizationMembership`: relationship to an organizer.
- `OrganizationRepresentation`: accountable board/representation authority.
- `Participation`: relationship to one edition.
- `EditionRegistration`: attendee purchase/attendance record, one per account.
- `PositionAssignment`: staff/volunteer role in an edition and department.
- `CapabilityGrant` / `RoleAssignment`: explicit authority, time bounded.
- `Application`: request to contribute or receive an allocation; grants none of
  the above merely by existing.

The platform administrator has only the first concept plus platform authority.

## Registration and application portfolio

### Base registration

Every edition owns one registration workspace and at most one active
registration configuration. Every account has at most one edition
registration. Creating an edition does not create a person's registration or
silently publish a form. Configuration may begin blank, from a reviewed prior
edition, or from an approved template and becomes independent copy-on-write
state.

### Typed applications

Use one form vocabulary and lifecycle framework, with typed adapters for:

- host a panel or community event;
- DJ set;
- performance, competition, or charity show;
- Maid Cafe participation;
- dealer application and booth allocation;
- Art Show or auction item submission;
- conbook, art, story, or media contribution;
- volunteer opportunity;
- guest, press, accessibility, or other configured services.

Each application type defines purpose, owner departments, eligibility,
cardinality, deadlines, applicant/staff edit windows, classification,
retention, review stages, decisions, and the typed object created on acceptance.
Applicant answers, staff corrections, reviewer notes, and authoritative facts
are separate provenance classes. A staff-only ticket entitlement is not an
applicant checkbox.

### Field contract

Every configurable field records:

- stable code and localized label/help;
- short text, long text, integer, decimal, boolean, single choice, multiple
  choice, date, time, instant, email, phone, URL, address, person reference,
  domain reference, or safety-checked file type;
- required/optional/conditional expression;
- length, numeric range, option set, file type/size, and cardinality;
- purpose and classification;
- applicant-visible, applicant-writable, staff-visible, staff-writable,
  reviewer-visible, public-after-approval, and API projection rules;
- edit deadline, review requirement, retention, export, and deletion behavior;
- immutable definition version and append-only value provenance.

## Venue model

Reusable organization facts:

- site/property;
- building;
- atomic space;
- entrance, zone, route, accessible feature, service contact;
- equipment/capacity facts and floor-plan document;
- space configuration consuming one or more atomic spaces;
- travel-time relation between sites or operational zones.

Edition-owned selection adds display names, capacity overrides, availability,
blocks, restrictions, service hours, and operating notes without mutating the
reusable source. Scheduling a combined `Room A+B` consumes both atomic rooms.
Neither `A` nor `B` may be independently occupied during that placement.

## Programme and timetable

### Item lifecycle

`proposal -> review -> accepted private item -> ready -> placed in WIP ->`
`approved release -> delivered/cancelled -> retained delivery record`

Private proposal answers and reviewer notes never become public merely because
an item is accepted. Public copy is a separate approved rendition.

### Work envelope

Every placement uses four ordered instants:

```text
preparation_starts_at
effective_starts_at
effective_ends_at
teardown_ends_at
```

The three derived phases are preparation, effective delivery, and teardown.
The room conflict matrix is:

| Intersection in same consumed atomic space | Result |
| --- | --- |
| Effective vs any phase | Hard conflict |
| Preparation of following item vs teardown of preceding item | Allowed shared turnover; still check people/equipment/tasks |
| Preparation vs preparation | Warning by default; policy may make hard |
| Teardown vs teardown | Warning by default; policy may make hard |
| Any phase outside hard availability | Hard conflict |
| Composite room vs any consumed component | Hard conflict |

Assigned people, exclusive equipment, qualifications, travel, maximum hours,
minimum rest, and dependencies are evaluated independently. Authorized planners
may accept warnings with a recorded reason; hard conflicts require a specific
policy-backed exception and must never disappear silently.

### Editor and releases

- Room columns and a selected service-day time axis.
- Drag or keyboard move with preview, conflict explanation, and optimistic
  version check.
- Resize preparation, effective, and teardown handles independently while
  preserving ordering and minimum durations.
- Filters for tracks, departments, owners, readiness, conflict, and layer.
- Ordered access-controlled layers for public programme, room turnover, Stage
  Tech, Security, Logistics, staffing, Multimedia, accessibility, and comments.
- Immutable named releases with comparison, change summary, approval, public
  projection, iCalendar, signage, and print/API outputs.
- Human Activity entries such as “Synthetic Planner moved Cooling 101 from
  Panel A 11:00 to Panel B 11:30; preparation now starts 11:00.”

## Logistics and storage

Use a location/containment graph rather than editable “current location” text:

- storage facility, area, rack, container, box, vehicle, loading zone, venue
  staging area, and room are typed locations;
- boxes may contain assets, stock lots, kits, or other boxes within bounded
  depth;
- a node cannot contain itself or an ancestor;
- serialized assets and counted stock remain distinguishable;
- current containment, location, and custody derive from append-only events;
- receive, pack, unpack, move, load, unload, handover, count, damage, loss,
  return, and disposal events carry actor, time, source, destination, condition,
  reason, and evidence;
- manifests are immutable snapshots linked to their resulting movements;
- QR/barcode scans identify objects, not the personal location of volunteers;
- offline scans use signed bounded manifests and reconcile conflicts visibly.

## Documents and institutional memory

One governed library stores documents and approved renditions with:

- organization, optional series/edition/department/event-type applicability;
- public, ticketed, internal, department-confidential, restricted, or legal-hold
  classification;
- owner, purpose, reviewer, version, status, effective date, review date,
  supersession, retention, and lawful-basis record where applicable;
- source file, safe preview, public rendition, checksum, malware result, and
  download audit according to classification;
- acknowledgement or signature requirement bound to the exact version;
- contextual links from forms, tasks, programme types, shifts, spaces, assets,
  and cases;
- permission-aware search and versioned API projections.

NDAs and submitted onboarding evidence remain distinct: a policy/document is
organization knowledge; a person's signed or uploaded evidence is a restricted
relationship record.

## Department views over shared primitives

| Department | Initial useful projection |
| --- | --- |
| Executive / Helper Board | readiness, risks, approvals, cross-department blockers, material changes |
| Registration / Front Desk | attendee lookup, payment/check-in state, badge, service requests, knowledge, surge staffing |
| Events & Programming | calls, proposals, review, readiness, timetable, hosts, public copy |
| Stage Tech / Multimedia | riders, cues, equipment, rehearsals, setup/teardown, operator shifts, media consent |
| Security / PEER / Legal | narrowly scoped cases, duty routing, access policy, retention, ordinary minimum-disclosure tasks |
| HR | opportunities, applications, onboarding, qualifications, assignments, availability, hours, handover |
| Logistics / Decorations / IT | storage, boxes, kits, manifests, movements, maintenance, deployment and return |
| Dealers / Art / Charity / Maid Cafe | configured applications, allocations, content classification, inventory, staffing, payments and reconciliation |
| Graphics / Story / Social Media | briefs, assets, approvals, rights, publishing schedule, public API/content renditions |
| Fursuit Support / Ceremonies | service capacity, spaces, programme dependencies, queues, shifts, run of show |

## API rules

- `/api/v1/` remains the supported compatibility boundary until a versioning
  decision replaces it.
- HTML and API call the same command/query services.
- External IDs are stable; URLs never rely on database sequence ordering.
- Collection endpoints paginate and filter without cross-tenant counts or
  existence leaks.
- Mutating endpoints use idempotency where retries are plausible and reject
  stale versions.
- Public, ticketed, staff, department, and confidential projections are
  separate serializers/queries, not a broad serializer with client-side hiding.
- OpenAPI generation and client drift checks remain merge gates.
- Website, signage, calendar, and other read clients use expiring,
  least-privilege projection credentials and signed webhooks where push is
  needed.

## Production milestones

### M0 — Consolidation map and truthfulness

- [x] Fetch and inventory every local and remote branch.
- [x] Select the Page 4 tip as the only safe base.
- [x] Create `codex/production-consolidation`.
- [x] Record ADR 0037.
- [x] Stabilize explicit requirements for three-phase schedules, layers,
  one-registration/separate-applications, access headers, storage, documents,
  typed applications, and input contracts.
- [x] Create this capability ledger and crash-safe checklist.
- [ ] Mark stale status documents as historical or update them to the ledger.
- [ ] Commit the documentation checkpoint.

Exit: a maintainer can tell what runs, what exists only in APIs, and what is
still absent without reading branch history.

### M1 — Edition workspace spine

- [ ] Page 5: convention-series record, edit, activity, edition inventory.
- [ ] Page 6: minimal audited edition creation with organization defaults.
- [ ] Edition creation service shared by HTML/API with tenant checks, audit,
  outbox, rollback, and idempotency decision.
- [ ] Page 7: edition record/home and explicit persistent edition context.
- [ ] Progressive series/edition navigation on every new page.
- [ ] First truthful access header: platform authority shown separately from
  convention participation.
- [ ] Full tests, docs, desktop and 390-pixel browser evidence.

Exit: the platform administrator can create and revisit organization -> series
-> edition without becoming a convention participant.

### M2 — Representation, people, and authorization scope v2

- [ ] Organization-level Executive Board representation model and activation
  gate; no automatic real-person assignment.
- [ ] Awoostria-shaped editable department template using synthetic data.
- [ ] Mounted hierarchy/position editor and minimized structure view.
- [ ] Department and resource constraints in authorization policy and grants.
- [ ] Effective-access query/header and audited contextual assignment editor.
- [ ] Human activity timeline resolving safe actor/target labels.
- [ ] Invitations, expiry, replacement, removal, multi-position and
  multi-department tests.

Exit: convention authority can operate Pages 3 onward without broad
edition-wide grants, while the platform administrator remains external.

### M3 — Venue foundation

- [ ] Reusable site/building/atomic-space/configuration models.
- [ ] Edition selections, display overrides, availability and hard blocks.
- [ ] Composite-room atomic consumption and travel-time matrix.
- [ ] Capacity/access/equipment validation and floor-plan document links.
- [ ] HTML/API/admin-shell pages, audit, events, isolation/concurrency tests.

Exit: an edition has safe schedulable spaces, including mergeable rooms and
multiple venues.

### M4 — Typed applications and panel vertical

- [ ] Domain-neutral versioned field/form vocabulary.
- [ ] Application type, submission, revisions, review, decision, conversation,
  deadline, and retention kernels.
- [ ] Applicant/staff/reviewer/public field matrices.
- [ ] “Host a panel” template and proposal workflow.
- [ ] Acceptance creates a private programme item idempotently.
- [ ] File safety, audit, outbox, API, isolation, and lifecycle tests.

Exit: a synthetic host can submit, revise, receive a decision, and create an
accepted private programme item without gaining unrelated access.

### M5 — Three-phase timetable and layers

- [ ] Programme readiness and public-rendition separation.
- [ ] Schedule WIP/version/release models.
- [ ] Four-instant work envelope and complete conflict engine.
- [ ] Visual and keyboard editor with move/resize preview and optimistic lock.
- [ ] Department comments, operational layers, and shift demand.
- [ ] Immutable releases, changelog, public/credentialed API, calendar and
  signage projections.
- [ ] Concurrency, daylight-saving, combined-room, person/equipment, override,
  accessibility, performance, and publication tests.

Exit: Maru can replace the central pretalx timetable workflow for a rehearsal
edition while adding furry-convention operations.

### M6 — Registration and governed documents

- [ ] Mount the existing registration domain through the coherent shell.
- [ ] Registration workspace “not configured” state and reviewed activation.
- [ ] Staff-assisted correction and extension-field builder with precise writer
  rules.
- [ ] Governed document/version/rendition/acknowledgement library.
- [ ] NDAs, policies, department and event-type document links.
- [ ] Production payment, mail, storage, malware scan, privacy, load, and
  printing gates.

Exit: real attendees can safely register once; authorized staff can correct or
extend information; governed documents are served by context and classification.

### M7 — Workforce, logistics, and live coordination

- [ ] Shift templates, qualification, availability, demand, claims,
  confirmation, attendance, hours, rest and handover.
- [ ] Storage/location graph, containers, boxes, assets, stock and kits.
- [ ] Append-only movements, scans, manifests, truck loading, venue deployment
  and return reconciliation.
- [ ] Department inboxes, threads, assignments, announcements, acknowledgement
  and delivery adapters.
- [ ] Offline bounded manifests for check-in and logistics-critical scans.
- [ ] Operations common picture and rehearsal mode.

Exit: Awoostria can rehearse staffing, room operations, equipment movement, and
on-site change communication from Maru.

### M8 — Specialized services and production certification

- [ ] Dealer, Art Show, DJ, performance, Maid Cafe, charity, conbook, press,
  guest, and other templates/adapters built from shared primitives.
- [ ] Finance/procurement/reconciliation integrations required by the pilot.
- [ ] Search, reports, exports, exit package, signed webhooks and external read
  credentials.
- [ ] Data inventory, retention schedule, processor review, threat review,
  accessibility audit, penetration test, restore/failover exercise, load test,
  incident runbooks, monitoring/alerts and operator training.
- [ ] Awoostria rehearsal with synthetic data; then controlled real-data pilot.
- [ ] Release checklist, migration/recovery plan and production sign-off.

Exit: production readiness is supported by evidence, not inferred from feature
count.

## Verification matrix for every milestone

- formatting and lint;
- static typing;
- PostgreSQL unit/integration/workflow suites;
- tenant, edition, department, resource and field denial matrices;
- migration generation/drift and forward/backward rehearsal where possible;
- OpenAPI schema and generated-client drift;
- coverage at or above repository gate without excluding new code;
- axe/keyboard/responsive browser checks and screenshots for critical pages;
- concurrency and stale-write checks for scheduling, capacity, assignments,
  movements and financial records;
- safe logging, audit integrity and outbox retry/idempotency;
- deployment check and changed runbook rehearsal.

## Immediate continuation after a crash

1. Read `docs/project/CURRENT.md`.
2. Read this file and find the first unchecked item in the active milestone.
3. Read ADR 0037 and the page/domain contract being changed.
4. Run `git status --short --branch`; do not discard unrelated changes.
5. Confirm the latest local checkpoint/commit and test result in `CURRENT.md`.
6. Continue only the smallest active slice; update this checklist before
   switching domains.

## Production gates outside the repository

These require named owner decisions or real infrastructure and cannot be
completed by adding code alone:

- hosting topology, domain, TLS, WAF/rate limits and secret management;
- PostgreSQL backup, point-in-time recovery and tested restoration;
- object storage, malware scanner, retention and secure download delivery;
- supervised outbox/workers, SMTP and messaging/push adapters;
- payment provider contract and authenticated production configuration;
- printer, badge, scanner, QR/barcode and on-site network hardware;
- privacy/legal basis, processor contracts, retention, minor/safeguarding and
  financial policy approval;
- alert destinations, support rota, incident response and recovery owners;
- representative Awoostria load, accessibility, security and operator rehearsal.

## Ideas after the core path

- A “rehearsal twin” that clones configuration without people or secrets and
  captures drill findings as next-edition work.
- Schedule heat maps for crowd pressure, staffing gaps, room turnover, travel,
  noise and accessibility rather than only timetable collisions.
- QR labels for boxes and kits with an offline-first “scan onto truck” manifest.
- Department handover packages generated from open tasks, decisions, documents,
  assets, risks and lessons.
- Policy impact preview: show affected forms, programme types, people and
  acknowledgements before a new version takes effect.
- Public read models and signed webhooks so annual websites, signage, mobile
  clients and conbook tooling consume the same released facts.
- A minimized on-site command view optimized for intermittent networks and
  tablet/phone use without becoming a separate product shell.
