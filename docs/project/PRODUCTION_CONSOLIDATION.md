# Maru production consolidation

Status: Active master checklist. The 2026-08-11 canonical repository gate and
the scoped authenticated read-only Logistics browser journey at 1,920 and 390
pixels are accepted. ADR 0055's task-oriented shell/home and User accounts to
Board first slice is repository-verified. Its complete authenticated
reflow/zoom, keyboard, screen-reader, and owner matrix, Page 10 stopped-writer
cutover, invitation-retention activation, downstream adapters, broader browser
mutation-role coverage, production authority reconciliation, provider
certification, load, restore/PITR, and governance acceptance remain open.
Branch: `main`
Historical consolidation base: `327a7d63574d0118356a0fd11ca5a316d78b2aed`
Started: 2026-08-01  
Decisions: ADRs 0037–0056

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

- One authenticated `/admin/` namespace and one navigation system;
  purpose-built platform records use the reserved `/admin/platform/` segment.
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
| `main` and `origin/main` at `c7287ef0b81c` | Same committed tip | Current committed foundation beneath the preserved implementation working tree. |
| Current working tree | Uncommitted production-consolidation milestone | Contains the Page 10 and bounded vertical implementation described here; preserve concurrent changes and verify as one graph before any commit. |
| `origin/legacy/github-main-462e7ba` | Unrelated history | Early prototype archaeology only. |
| `origin/legacy/local-final-2026-07-29` | Unrelated history | Best timetable, room, application, shift, export, and signage interaction reference. Never merge its migrations or global-project model. |

The current branch is the only consolidation line. No local page or pre-reset
branch has ref-only commits. When a legacy behavior is reused, add a modern
requirement and test it against current authorization and tenant boundaries.

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

| Capability | State on 2026-08-11 | Evidence / next dependency |
| --- | --- | --- |
| Organization and series Pages 1–5 | Mounted | Implemented under `/admin/platform/`; platform and scoped Board backend matrices pass. Browser/owner evidence remains. |
| Convention-series record | Mounted | Page 5 domain/API behavior and canonical shell route pass backend checks. Browser/owner evidence remains. |
| Edition lifecycle | Partial | Authorized API and Convention work are mounted; Page 7 remains record/profile/context only rather than the lifecycle command surface. |
| Edition browser workspace | Mounted | Pages 6–7 and scoped non-staff routes pass backend checks; current browser and owner rehearsal remain. |
| Unified navigation and My Maru | Mounted / first UX slice repository-verified | One permission-filtered searchable registry, stable reauthorized pins, selected-context header, and `/my/` personal destinations remain mounted. ADR 0055 now prioritizes durable tasks, natural-language search, contextual/search-only actions, a specialist-record gateway, a task home, and an accessible drawer at intermediate/narrow widths. Focused matrices pass; full rendered-width, zoom, keyboard, screen-reader, accessibility, and owner rehearsal remains. |
| Organization representation | Mounted / partial | Page 8 implements provision, exact verified-account invitation, own response, two-person cross-approval, atomic Draft-to-Active activation, and platform emergency containment. Its presentation now keeps a visible three-step progression and platform-admin User account preparation handoff without changing authority. Database guards, focused matrices, and the final local backend gate pass. Representative PITR, complete rendered/accessibility/owner evidence, routine term management, and safe planned replacement remain. |
| Department hierarchy | Mounted Page 9a.1 / repository accepted | Canonical Page 9 composes the minimized Executive Board anchor with one version-fenced bounded tree and mounts same-shell template/Department forms plus five strict API mutations over the stopped-writer command core. The 4,067-test canonical repository gate passes; Page 9 responsive-browser, accessibility, owner, and deployment evidence remain. Page 9b Positions remains separate. |
| Department/resource authorization | Mounted / deployment-gated | ADR 0041 exact Department and typed-resource policy, immutable issuance/binding evidence, migrations, database guards, and the global computed Access component are mounted without implicit hierarchy inheritance. Named relationship reads are audited and preview never impersonates. Production legacy reconciliation, policy cutover, representative restore/PITR, and unbounded candidate-load evidence remain. |
| Effective-access explanation and preview | Mounted | Management pages resolve a typed scope into computed Access; fixed self/public/safeguarding/security policies explain why mutation is absent. Signed exact-person and immutable-role previews are capped, audited, read-only, and keep the real principal for every POST. The focused Access matrix passes; this is not arbitrary page ACL sharing. |
| Attendee registration and admission commerce | Mounted / deployment-gated | Public/self registration, My Maru, exact-difference upward replacement, hard-ceiling capacity adjustments, strict FIFO batches, and hosted/demo payment boundaries are executable. Real provider/webhook, printer/device, load, retention, recovery, accessibility, refund/transfer, and fulfilment gates remain. |
| Registration extension fields | Mounted / cutover incomplete | Versioned definitions, closed self/staff/exact-Department/confirmed/public audiences, append-only values, audited API/directory projections, and self/staff browser editing are mounted. Compatibility-writer retirement, stopped-writer activation, and complete browser/accessibility evidence remain. |
| Typed application portfolio | Mounted / bounded | Ten code-owned starters, edition-owned drafts, organizer/applicant/reviewer journeys, exact named/immutable-role review provenance, and typed acceptance receipts are implemented. Real programme/workforce/SecOps/merchandise target adapters, staff answer correction, richer review rubrics, retention execution, and accessibility rehearsal remain. |
| Programme intake/review | Absent | PRG-001–007. |
| Venues and operational space bookings | Mounted / bounded | Reusable venue facts, edition selections, immutable physical-member expansion, hard availability, two-clique occupancy, independent approval/publication, and minimized public/My schedule projections are mounted. Guest allocation, programme ownership, full timetable layers/exports, and person/equipment conflicts remain. |
| Timetable and shifts | Partial | Venue bookings implement safe three-phase physical occupancy and public schedule projection, but shared programme releases, workforce shifts, people/equipment conflicts, operational layers, and exports remain absent. |
| Logistics/storage | Mounted / bounded / deployment-gated | Typed containment/custody/event/manifest/offline workflows, exact capability bindings, mounted routes, retention boundaries, runtime-role profiles, and fail-closed readiness are implemented. The serialized PostgreSQL matrix passes 26/26, the canonical repository gate passes, and scoped authenticated read-only browser rehearsal passes at 1,920 and 390 pixels. LOG-003 demand/reservation, LOG-004 driver/routes, LOG-006 invoice linkage, LOG-007 low-stock/wastage, broader mutation-role/visual/accessibility, restore/PITR, and production activation remain open. |
| Governed charity partners | Mounted / bounded | Reusable non-tenant partners, private edition review, independent media/confirmation/publication, and minimized public snapshots satisfy FUR-011. Fundraising campaigns, settlement, costs, and public financial reporting remain open. |
| Edition catalog and owned orders | Mounted / deployment-gated | Product/variant/beneficiary policy, finite stock, attendee orders, payment intents, activity, and same-shell attendee/staff pages are mounted. Real provider certification, order expiry/cancel/refund/exchange, fulfilment/shipping, and accounting export remain. |
| Governed document library | Absent | Workforce onboarding upload is not a knowledge library. |
| Notifications | API-only | Canonical service notifications exist. |
| Team conversations and on-site messaging | Absent | Needs scoped inbox/thread domain and delivery adapters. |
| Credentials/offline check-in | API-only | Tested domain; hardware, printing, recovery, and load gates remain. |
| Audit and activity | API-only audit / mounted record history | Append-only audit plus bounded Page 5/7 domain-fact history; cross-domain access-aware activity remains M2. |
| Stable API/OpenAPI | Partial | Mounted domain APIs use strict closed contracts and exact authorization boundaries. ADR 0056 adds private, locally served Swagger and ReDoc discovery views over the unchanged canonical schema; deterministic schema/client verification passes without drift. Organization writes, external credentials, future domains, deployment, and public developer-portal policy remain. |
| Synthetic demo governance | Mounted local-only | ADR 0042 makes `seed_demo_data` the canonical synthetic fixture and establishes two active Executive Boards through real services. The old public-roster scenario is deleted and its compatibility command fails before validation, file/network access, or database writes. |
| Production infrastructure | Deployment-gated | Provider selection, SMTP, object storage, scanner, workers, secrets, monitoring, restore, load, and legal/security review. |

Update this table whenever code changes state. Do not leave a capability marked
Mounted when its route is removed.

## Information architecture

The same `/admin/` shell and left navigation progressively reveal only the
selected scope:

```text
Administration home
├─ Convention work
├─ Platform administration
│  └─ Organizations                      + Add
│     └─ Selected organization
│        ├─ Organization record
│        ├─ Representation & access
│        ├─ Convention series             + Add
│        ├─ Venues and year-round assets
│        └─ Documents
│           └─ Selected series
│              ├─ Series record
│              └─ Convention editions     + Add
│                 └─ Selected edition
│                    ├─ Overview
│                    ├─ Organization structure
│                    ├─ Registration
│                    ├─ Applications
│                    ├─ Programme
│                    ├─ Timetable
│                    ├─ Shifts & tasks
│                    ├─ Venue operations
│                    ├─ Logistics
│                    ├─ Documents
│                    ├─ Communications
│                    ├─ Reports
│                    ├─ Activity
│                    └─ Settings & access
└─ Specialist records
```

The Page 1–8 spine uses `/admin/platform/organizations/...`. The reserved
segment prevents collisions with Django application-label routes while keeping
all management work inside one namespace and one visual grammar.

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

## Fictional MaruCon starter structure

The repository-owned starter has no real accounts or imported taxonomy and
contains:

```text
Executive Board
└─ Convention Coordination
   ├─ Attendee Services
   ├─ Registration
   ├─ Programme
   ├─ Stage Production
   ├─ Venue Operations
   ├─ Logistics
   ├─ Volunteer Support
   ├─ Safety
   ├─ Accessibility
   ├─ Technology
   ├─ Communications
   ├─ Design & Publications
   ├─ Exhibitors
   ├─ Charity
   ├─ Guest Relations
   ├─ Accommodation
   ├─ Hospitality
   ├─ Finance & Procurement
   ├─ Partnerships
   ├─ Live Operations
   └─ Archive & Handover
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
- `RepresentationAppointment`: one exact person's accepted or historical term
  in that representation, linked to but not replaced by software authority.
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
| Executive / Convention Coordination | readiness, risks, approvals, cross-department blockers, material changes |
| Attendee Services / Registration | attendee lookup, payment/check-in state, badge, service requests, knowledge, surge staffing |
| Programme / Guest Relations | calls, proposals, review, readiness, timetable, hosts, public copy |
| Stage Production / Venue Operations | riders, cues, equipment, rehearsals, setup/teardown, operator shifts, media consent |
| Safety / Accessibility | narrowly scoped cases, duty routing, access policy, retention, ordinary minimum-disclosure tasks |
| Volunteer Support | opportunities, applications, onboarding, qualifications, assignments, availability, hours, handover |
| Logistics / Technology / Live Operations | storage, kits, manifests, movements, maintenance, deployment and return |
| Exhibitors / Charity / Hospitality / Partnerships | configured applications, allocations, inventory, staffing, payments and reconciliation |
| Communications / Design & Publications | briefs, assets, approvals, rights, publishing schedule, public renditions |
| Accommodation / Finance & Procurement / Archive & Handover | capacity, evidence, controlled spending, retention and year-to-year continuity |

## API rules

- `/api/v1/` remains the supported compatibility boundary until a versioning
  decision replaces it.
- HTML and API call the same command/query services.
- External IDs are stable; URLs never rely on database sequence ordering.
- Collection endpoints paginate and filter without cross-tenant counts or
  existence leaks.
- Mutating endpoints use idempotency where retries are plausible and reject
  stale versions.
- Edition creation uses the UUID `Idempotency-Key` HTTP header; the browser
  adapter keeps an equivalent hidden UUID. Retry keys do not belong in the API
  JSON body or routine activity/audit display.
- Public, ticketed, staff, department, and confidential projections are
  separate serializers/queries, not a broad serializer with client-side hiding.
- OpenAPI generation and client drift checks remain merge gates.
- Website, signage, calendar, and other read clients use expiring,
  least-privilege projection credentials and signed webhooks where push is
  needed.

## Canonical repository acceptance (2026-08-11)

The whole working tree has one current repository verdict, superseding earlier
focused counts without erasing their milestone history:

- Ruff formatting and lint pass over 624 files, strict mypy passes over 355
  source files, and collection finds exactly 4,067 tests.
- The serialized canonical PostgreSQL-backed run passes 4,067 of 4,067 tests in
  15,558.23 seconds (4:19:18) at 90.78 percent total branch-aware coverage.
  Registration and Identity coverage was repaired with coherent behavior and
  security matrices, without threshold/configuration changes, exclusions, or
  pragma omissions.
- Two genuine defects found during that repair are fixed: Registration setup
  dependency failures are handled before their broader command-error superclass
  so unavailable dependencies remain `503`, and canonical UUID form validation
  accepts the documented lower-case hyphenated version-agnostic shape while
  rejecting aliases.
- Installed module readiness, function/relation ACL, non-delegable runtime-role,
  tenant/object/field denial, OpenAPI/client, frontend, and migration-drift
  checks pass. The migration graph preserves the ordered `venues 0001 ->
  logistics 0001 -> authorization 0016 -> logistics 0002` chain, Workforce
  `0008` follows every exact Department-FK creator, historical Registration
  targets select the compatible Workforce leaf, and identity delivery integrity
  follows its reconciliation-audit fence.
- Invitation delivery, expiry, and retention heartbeats use one materialized
  PostgreSQL clock observation. Scheduler success, invitation transitions,
  retention receipts, and terminal delivery/disposition evidence are append-
  only or one-way under database guards and least-privilege ACLs. This does not
  activate the invitation-retention candidate or a deployment scheduler.
- The authenticated scoped read-only Logistics browser journey passes at
  1,920- and 390-pixel widths. Broader visual states and mutation roles,
  keyboard traversal, and automated accessibility remain unaccepted.

This is repository and bounded browser evidence only. No deployment, stopped-
writer/cutover, restore/PITR, production-data, owner, governance, or production-
readiness claim follows from it.

## Production milestones

### M0 — Consolidation map and truthfulness

- [x] Fetch and inventory every local and remote branch.
- [x] Select the Page 4 tip as the only safe base.
- [x] Create `codex/production-consolidation`.
- [x] Record ADR 0037.
- [x] Record ADR 0038 after implementation separated the record spine from
  governance/scoped access.
- [x] Stabilize explicit requirements for three-phase schedules, layers,
  one-registration/separate-applications, access headers, storage, documents,
  typed applications, and input contracts.
- [x] Create this capability ledger and crash-safe checklist.
- [x] Mark stale status documents as historical or update them to the ledger.
- [x] Commit the documentation checkpoint (`4f6cbcb`).

Exit: a maintainer can tell what runs, what exists only in APIs, and what is
still absent without reading branch history.

### M1 — Edition workspace spine

- [x] Page 5: convention-series record, edit, activity, edition inventory.
- [x] Page 6: minimal audited edition creation with organization defaults.
- [x] Edition creation service shared by HTML/API with tenant checks, audit,
  outbox, rollback, and idempotency decision.
- [x] Page 7: edition record/home and explicit persistent edition context.
- [x] Progressive series/edition navigation on every new page.
- [x] First truthful access header: platform authority shown separately from
  convention participation.
- [x] Full tests, docs, generated API/client, deployment-shaped checks, desktop
  and 390-pixel browser evidence, with accessibility caveats recorded.

M1 is locally verified, not production-ready. Owner tutorial rehearsal,
automated accessibility analysis, reliable keyboard traversal, the remaining
visual state matrix, and every external release gate stay open. The access
header is static/provisional and must not be mistaken for M2's computed
organization/department/person access.

That verification predates ADR 0039's default-shell and route migration. It
continues to support the M1 services and records but does not certify the
active URL or navigation changes.

Exit: the platform administrator can create and revisit organization -> series
-> edition without becoming a convention participant.

### M1.1 — Coherent administration shell

- [x] Record ADR 0039 and the collision-safe `/admin/platform/` route contract.
- [x] Update the current handoff, master checklist, roadmap, page contracts,
  architecture, module, and operator documentation for the chosen shell.
- [x] Make `maru.urls` the backend-verified default without exposing an unauthorized
  alternate management surface.
- [x] Mount Pages 1–7 under `/admin/platform/organizations/...` before
  `admin.site.urls`; define and test old-route behavior.
- [x] Present Administration home, Convention work, platform pages, and
  permission-filtered specialist records through one collapsible sidebar with
  no duplicate workspace selector or Quick Start strip.
- [x] Prove anonymous, inactive, ordinary active, Django staff/model-permission,
  and platform-administrator boundaries for every affected route.
- [x] Run focused route/navigation tests, migration drift, Django check, Ruff,
  mypy, Staff Console typecheck, 19 Vitest tests, and production build.
- [x] Record the pre-hardening isolated backend baseline: 710 tests and 90.03
  percent coverage passed before organizations `0009`–`0012` and the other
  IDN-011 guards landed.
- [x] Rerun the complete backend suite and 90-percent coverage gate once from
  the final consolidated hardening tree: 792 tests pass in 329.21 seconds with
  90.01 percent coverage and no warnings. A separate behavior run passes the
  same 792 tests in 291.86 seconds.
- [x] Prevent historical migration tests from contaminating later tests by
  restoring every app to the current on-disk migration leaf in a shared
  finalizer; the ordered regression passes 26 tests.
- [x] Prove the secure URL default under warnings-as-errors; 24 focused HTTPS
  tests pass.
- [x] Preserve Django `nav_sidebar.js`'s `#nav-filter` contract when a scoped
  account has no Specialist records. Seven focused unified-routing tests pass;
  a live Board-admin reload has exactly one hidden filter, no Specialist
  records, and zero new console warnings or errors.
- [x] Repeat desktop and 390-pixel browser smoke for the shell, Pages 3/7/8,
  Convention work, and a scoped Board controller without console errors or
  horizontal overflow.
- [x] Run current `pip-audit` and the production `pnpm audit`; both report no
  known vulnerabilities. The production-shaped deploy check is clean. Repeat
  dependency audits for each release because advisory data changes.
- [ ] Complete keyboard traversal, automated accessibility checks, and the
  relevant error/denied/stale matrix.
- [ ] Rehearse the revised hands-on tutorial with the owner.

Exit: the richer `/admin/` grammar is the only supported management shell;
Pages 1–7, Convention work, and specialist records coexist without route or
authority collisions, and current verification evidence exists. This exit is
not production approval.

### M2 — Representation, people, and authorization scope v2

- [x] Accept ADR 0040 and Page 8's strict initial Executive Board lifecycle,
  non-participating platform boundary, two-controller activation invariant,
  and migration/recovery contract.
- [x] Finish the representation/appointment models and additive migration;
  never infer a real-person assignment or silently reconcile a non-Draft
  organization.
- [x] Finish Page 8 provision, exact-account invitation, self-response, and
  atomic activation adapters in the unified shell.
- [x] Prove tenant/principal non-disclosure, strict input, duplicate/replay,
  stale/concurrent activation, two-person cross-approval, platform exclusion,
  audit/outbox rollback, and database constraints.
- [x] Exercise the real handoff in the local-only synthetic demo fixture with
  two distinct controllers per organization.
- [x] Complete bounded sensitive-read/privileged-denial audit coverage,
  including exact-tenant filtering, deterministic ordering, a 100-row ceiling,
  audited returned count, and fail-closed audit-append behavior.
- [x] Apply organizations `0008`–`0012`, participation `0004`, registration
  `0031`, and workforce `0003` to the populated local database; reconcile the
  synthetic demo through real governance services and prove a second seed is
  idempotent.
- [x] Rehearse the representation preflight, a fresh empty migration, and a
  populated local restore through organizations `0009`; retain bounded counts
  and remove the isolated drill database afterward.
- [x] Repeat the then-current pre-runtime-hardening operational rehearsal:
  fresh `maru_consolidated_demo` applied 106 migrations and contained 80 synthetic
  accounts, two organizations, and six editions; readiness is 16/16 with zero
  blockers. Restore into `maru_restore_drill_m21` passed and cleanup removed
  the drill database. Rebuild current-graph demo/recovery evidence after the
  organizations `0013`/workforce `0005`/authorization `0009` convergence.
- [x] Accept ADR 0042 and delete the public-roster rehearsal implementation;
  keep only a compatibility command that fails before validation, file/network
  access, or database mutation.
- [x] Accept ADR 0043 and implement platform-only global emergency controller
  containment with quorum-loss suspension and durable evidence.
- [x] Enforce IDN-011 below the ORM for organization, participation,
  registration, and workforce subjects, including concurrent account-kind
  reclassification.
- [x] Finish readiness-command parity and the focused representation/platform
  concurrency matrix: the readiness/core focus passes 10 tests and the
  representation/platform matrix passes 126 tests.
- [ ] Rehearse a representative restored deployment database through all
  current guards, reserved-role conflict, old-writer/fix-forward recovery, and
  backup/PITR evidence.
- [ ] Run keyboard/axe, complete visual states, and the revised owner tutorial.
- [x] Accept ADR 0041's exact department/typed-resource scope design with no
  implicit department-tree inheritance.
- [x] Mount Page 9a.0's canonical read-only Organization structure page and
  strict GET API; compose the minimized governance anchor, enforce exact
  edition-wide view, code-owned complete-tree ceilings, exact-role/active-
  person holder checks, fresh final authorization, audit-before-disclosure,
  safe typed failures, and remove the duplicate React destination.
- [x] Implement and pin immutable `marucon-reference@1` catalog content:
  exact 22 repository-owned Departments, Convention Coordination sole root,
  no Executive Board Department,
  exact identifier/no aliases, bounded graph validation, canonical JSON, and
  SHA-256 evidence. Application now uses only the mounted shared command.
- [x] Page 9a.1: complete the edition-owned structure write boundary in the
  repository; responsive-browser, accessibility, owner, and deployment
  acceptance remain separate gates.
  - [x] Add the expansion schema, immutable built-in template catalog,
    optimistic aggregate model, minimized command-receipt model, coherent
    version-fenced read projection, and shared Department command core.
  - [x] Preserve immutable resource bindings as retirement history rather than
    live blockers while retaining new-target and hard-delete protection; add
    exact-scope close-only services for expired authority below retired
    Departments with audit/event evidence and tenant/scope denial tests.
  - [x] Install workforce `0007` as a stopped-writer cutover: count-only
    legacy preflight, deterministic `legacy_existing` control backfill,
    outermost global activation barrier, per-edition mutex, one-way retirement,
    aggregate/receipt handshake, direct-DML rejection, reverse fence, catalog
    fingerprints, and genuine runtime-role tamper tests.
  - [x] Retire or migrate every older Department/Position/assignment writer,
    including specialist Department editing, first-authority bootstrap,
    synthetic demo seeding, Position binding creation, and assignment
    activation; preserve closed historical relationships without allowing new
    targets below retired Departments.
  - [x] Pass the definitive current-graph repository gate on a fresh isolated
    PostgreSQL database: 1,471 tests in 1,538.40 seconds at 90.13 percent branch
    coverage.
  - [x] Mount the shared strict HTML/API template application and Department
    create, update, reparent, order, retire, and protected-delete adapters over
    the stopped-writer command boundary. The mutation API focus passes 48 tests
    for strict input, denial/non-disclosure, replay/conflict, lifecycle,
    rollback, method/CSRF, and OpenAPI behavior.
  - [x] Pass the fresh isolated PostgreSQL combined Page 9 gate: 159 tests in
    102.89 seconds across core/forms, Page 9 read and HTML mutations, mutation
    and adjacent workforce APIs, exact-lineage navigation, and unified routing.
  - [x] Add 118 targeted adapter/contract invariants: 59 HTML, 50 API/contract,
    and 9 immutable-template cases. The focused HTML selection passes 59 tests
    with 27 deselected in 28.13 seconds; the adjacent API/contract batch passes
    152 tests in 73.90 seconds.
  - [x] Pass the definitive adapter-expanded repository gate: 1,693 tests in
    1,653.43 seconds (27:33) at 90.50 percent total branch-inclusive coverage.
- [ ] Complete the authenticated desktop/390-pixel, keyboard, accessibility,
  and complete validation/stale/protected/denied/limit/dependency state matrix.
  Chrome was unavailable during the definitive repository evidence run, so no
  new visual QA result is claimed.
- [ ] Page 9b: mount Position/template/reporting/opportunity management only
  after its authority-bearing dual-control and recovery contract is complete.
- [x] Page 9a.0 focused evidence: 52 Page 9/API/catalog/template tests, the
  standalone query-count regression, 65 adjacent navigation/shell/admin/
  representation tests, OpenAPI validation/client regeneration, TypeScript,
  19 Vitest tests, Vite build, repository-wide Ruff/mypy/Django/migration/
  production checks, and authenticated desktop smoke pass. The later
  definitive adapter-expanded graph passes 1,693 tests at 90.50 percent total
  branch-inclusive coverage; a reliable 390-pixel Page 9 management run remains
  open.
- [x] Implement ADR 0041 department and typed-resource constraints in
  authorization policy, grants, assignments, migrations, and trusted targets.
- [x] Add deterministic immutable `workforce.position` bindings, including
  activation backfill and explicit live creation from specialist-record and
  preserved bootstrap workflows.
- [x] Add a privacy-minimized readiness command that separates migration-data
  readiness from production readiness and names authority-source provenance as
  unresolved without disclosing people, capabilities, or resource IDs.
- [x] Pass the consolidated 876-test backend gate at 90.43 percent branch
  coverage, the 57-test ordered migration matrix, static/deploy/OpenAPI/client/
  frontend/documentation gates, populated synthetic migration/readiness, and
  scoped live browser smoke.
- [x] Record and enforce exact actor/approver authority-source provenance for
  root grant and role issuance.
  - [x] Accept ADR 0044's typed append-only issuance ledger, deterministic
    source selection, non-cyclic Board ceremony, no-rebinding semantics, staged
    reconciliation, and fail-closed activation contract.
  - [x] Implement additive issuance/control schema and source-aware writers.
  - [x] Backfill only provable initial Board and delegated-parent evidence with
    a dry-run-first, stopped-writer, idempotent reconciliation command.
  - [x] Enforce distinct controller principals under concurrent database writes
    and pass the 964-test repository gate at 90.41 percent branch coverage,
    static/deploy/OpenAPI/frontend checks, and current dependency audits.
  - [ ] Revoke/recreate effective ordinary legacy authority without inference,
    replacing referenced unproven role definitions.
  - [x] Implement the dynamic lineage policy, database completeness guards,
    one-way marker/evidence, downgrade fence, runtime-role readiness, guarded
    activation, and local synthetic failure/recovery verification.
  - [x] Hold target resolution to five fixed tenant-chain queries and exact
    issuance validation to database-call chunks of 256 checks.
  - [ ] Prove acceptable latency and memory for representative unbounded
    authority-candidate cardinality; the 256-item issuance chunks do not bound
    candidate-set construction or total work.
  - [ ] Rehearse representative deployment backup/PITR and fix-forward, then
    perform the stopped-writer production activation only after ordinary legacy
    reconciliation and named operator approval.
- [x] Mount the computed Access query/header/component and audited scoped
  person/immutable-role assignment workspace, including capped read-only
  exact-person and role preview that never changes the session principal.
- [ ] Cross-domain, access-aware human activity workspace resolving safe actor
  and target labels. Pages 5/7 already provide bounded aggregate record
  history; that does not complete this item.
- [ ] Invitation discovery/delivery, expiry, withdrawal, replacement, removal,
  representation suspension/reactivation, quorum recovery, multi-position,
  and multi-department tests.

Exit: convention authority can operate Pages 3 onward without broad
edition-wide grants, while the platform administrator remains external.

### M2.5 — Page 10 identity and Registration journey

- [x] Accept ADR 0047 and the Page 10 contract: one shared administration
  shell, a non-participating platform administrator, recipient-owned account
  passwords, exact edition scope, synthetic-only educational data, and staged
  writer retirement.
- [x] Implement and independently accept the platform account inventory,
  invitation commands, recipient acceptance, durable delivery/reconciliation,
  and strict versioned APIs.
- [ ] Independently accept the author-verified invitation-retention v10
  corrective candidate for
  immutable tombstones, provider-reference disposal, arbitrary challenge
  history, fair bounded work, strict database time/source evidence, populated
  upgrade, and fix-forward downgrade behavior. Do not activate a deployment
  retention policy before this gate.
- [x] Implement and independently accept the draft section, question, product,
  minor-policy, and profile-definition builder commands and APIs.
- [x] Implement and focused-verify blank/template/prior-edition setup start
  with complete source provenance, immutable original binding, and exact
  receipt/target/audit/event/outbox replay evidence, including the immutable
  code-owned `convention-registration` starter.
- [x] Repair and focused-verify configuration review/activation after the
  authoritative-evidence, provenance, validation, review-durability, source-
  binding, and version-anchoring findings. This is command/migration evidence,
  not stopped-writer deployment acceptance.
- [x] Repair and independently accept profile-definition approval, activation,
  successor, and retirement after the source-retirement, replay-target,
  source-generation, immutability, and populated-downgrade findings.
- [x] Add the dedicated exact-edition `registration.view_profile_extensions`
  and `registration.update_profile_extensions` capabilities without widening
  existing grants or role bundles.
- [x] Replace the legacy profile-value writer/read with sequence-fenced,
  idempotent append commands, dedicated staff capabilities, ownership-aware
  attendee policy, audited bounded reads, and minimized event/outbox evidence.
- [x] Focused-verify the governed reusable-template publication/catalog
  lifecycle and its exact receipt, target, audit, event, outbox, child stamp,
  concurrency, rollback, and database-guard evidence from migration `0037`.
- [x] Mount strict profile-definition and profile-value HTML/API adapters,
  including self/staff same-shell editing, exact reader/writer policy, optional
  typed clearing, and immediate consent-withdrawal removal.
- [ ] Complete the final governed configuration scalar/successor adapter
  surface, reconcile compatibility aliases and all remaining direct writers,
  then install the stopped-writer generation with readiness and recovery
  rehearsal.
- [ ] Run the deterministic synthetic education journey plus tenant,
  field-policy, stale/replay, failure-atomicity, desktop/390-pixel, keyboard,
  WCAG 2.2 AA, load-ceiling, and representative recovery matrices.

Exit: a platform operator can provision identity and observe the complete
journey without becoming a convention subject; an authorized organizer can
build and activate one form; a synthetic attendee can register and append only
allowed profile facts; and direct or foreign writers fail closed.

### M3 — Venue foundation

- [x] Reusable property/site/building/atomic-space/configuration models.
- [x] Edition selections, local display names/restrictions, versioned hard
  availability, and current public/internal/security layout references.
- [x] Composite-room atomic consumption with PostgreSQL physical-member
  exclusion and safe teardown-to-setup turnover.
- [x] Configured/fire capacity validation and independently reviewed media/
  layout references; full access-feature/equipment/travel-time matrices remain
  later Venue work.
- [x] Same-shell HTML, strict API, audit, outbox, exact typed authorization,
  public/My schedule, tenant/isolation/concurrency, and DST-focused tests.

Exit: an edition has safe schedulable spaces, including mergeable rooms and
multiple venues.

### M4 — Typed applications and downstream adapters

- [x] Closed versioned field/form vocabulary in the bounded Applications
  context.
- [x] Definition, submission revision, review/decision, deadline, successor,
  and append-only provenance kernels.
- [x] Applicant and assigned-reviewer field projections with audited sensitive
  reads; staff/public visibility metadata is stored on definitions.
- [ ] Add staff answer-correction commands/windows and an approved public-answer
  projection; definition metadata alone does not complete those audiences.
- [x] Ten code-owned non-panel starters (merchandise, DJ, dance competition,
  Maid Cafe, adult performance, volunteer, feedback, idea, damage, and helper)
  plus organizer, applicant, and reviewer workflows.
- [ ] Add the host-panel starter and its real programme target adapter.
- [ ] Acceptance creates a private programme item idempotently.
- [x] Safe-file receipt boundary, audit, outbox, strict API, exact reviewer/
  tenant isolation, lifecycle, and same-shell tests. Real file storage/scanning
  and downstream typed-object adapters remain external or later milestones.

Current bounded exit: a synthetic applicant can submit, revise, and receive an
assigned-reviewer decision without gaining unrelated access. The full milestone
exit still requires the unchecked host-panel starter and idempotent private
programme adapter above.

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

- [x] Mount the existing registration domain through the coherent shell and My
  Maru.
- [x] Mount Registration not-configured/start, definition, review, and
  activation journeys through the governed Page 10 command boundary.
- [x] Mount the profile-extension definition builder and exact self/staff value
  editors with closed reader/writer rules.
- [ ] Complete broader staff-assisted correction beyond governed extension
  values and finish the Page 10 compatibility-writer/stopped-writer cutover.
- [ ] Governed document/version/rendition/acknowledgement library.
- [ ] NDAs, policies, department and event-type document links.
- [ ] Production payment, mail, storage, malware scan, privacy, load, and
  printing gates.

Exit: real attendees can safely register once; authorized staff can correct or
extend information; governed documents are served by context and classification.

### M7 — Workforce, logistics, and live coordination

- [ ] Shift templates, qualification, availability, demand, claims,
  confirmation, attendance, hours, rest and handover.
- [x] Mount the bounded storage/location graph, containers, boxes, assets,
  stock, and kits.
- [ ] Add demand/reservation and complete stock planning.
- [x] Mount append-only custody/location events, manifests, vehicle loading,
  venue deployment, return/discrepancy handling, person offers, and actionable
  Stage Tech receiving.
- [ ] Add route/driver optimization and supplier invoice linkage.
- [ ] Department inboxes, threads, assignments, announcements, acknowledgement
  and delivery adapters.
- [x] Bounded expiring offline Logistics batches reconcile against current
  server state; the installed migration/auth/API/UI/readiness/runtime-role gate
  passed in the 26/26 acceptance matrix.
- [x] Accept the scoped authenticated read-only Logistics browser journey at
  1,920- and 390-pixel widths.
- [ ] Complete broader Logistics visual-state and mutation-role browser
  rehearsal, keyboard traversal, and automated accessibility analysis.
- [ ] Operations common picture and rehearsal mode.

Exit: MaruCon can rehearse staffing, room operations, equipment movement, and
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
- [ ] MaruCon rehearsal with synthetic data; then controlled real-data pilot.
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
3. Read ADRs 0037–0054 and the page/domain contract being changed, including
   Page 8 for representation work.
4. Run `git status --short --branch`; do not discard unrelated changes.
5. Confirm the latest local checkpoint/commit and test result in `CURRENT.md`.
6. ADR 0041 scope v2 and ADR 0044's guarded exact-lineage activation are
   implemented and locally verified with synthetic data. Resume with ordinary
   legacy reconciliation on a representative restore, the unbounded candidate-
   cardinality load gate, and stopped-writer cutover/PITR rehearsal; only then
   consider a real production activation. Page 9a.1's aggregate, stopped-
   writer cutover, immutable template application, and shared Department
   command core and strict HTML/API mutation adapters are implemented. The
   canonical 4,067-test repository/coverage gate and scoped authenticated read-
   only Logistics browser journey at 1,920 and 390 pixels pass; continue with
   broader visual/mutation-role and accessibility acceptance. The computed
   Access explanation and safe preview are mounted. Keep stopped-writer/
   cutover, representative deployment/PITR, keyboard/automated accessibility,
   complete visual states, and owner/governance evidence open. Update this
   checklist before switching domains.

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
- representative MaruCon load, accessibility, security and operator rehearsal.

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
