# Architecture overview

Status: Target architecture with locally verified unified `/admin/` shell,
initial Executive Board representation, and database subject boundary
Last updated: 2026-08-01

## System shape

Maru is an API-first modular monolith. One Django deployment may host multiple
organizations and event editions, while separate clients consume versioned
APIs.

ADR 0030 reduced HTML to a controlled rebuild. Pages 1–7 then implemented
organization inventory/creation/record management, convention-series
creation/record, and event-edition creation/record/context for explicitly
classified platform administrators. HTML and API edition writes share
application services, audit, domain events, outbox, strict input, and aggregate
concurrency.

ADR 0039 supersedes the minimal default shell and moves the management spine to
reserved `/admin/platform/` routes inside one richer `/admin/` shell alongside
embedded Convention work and permission-filtered specialist records. The
default route, collision-safe ordering, and scoped shell authorization are
implemented and backend-verified. ADR 0037 still
delivers the remaining system as executable vertical milestones. Richer
clients in the diagram are current API consumers, preserved targets, or absent
capabilities until the live ledger in
`docs/project/PRODUCTION_CONSOLIDATION.md` says otherwise.

ADR 0040 adds a purpose-built Executive Board representation aggregate before
organization activation. Exact verified person accounts accept versioned
appointments; at least two accepted controllers receive cross-approved
assignments to an immutable root-role version in the same transaction that
moves the Draft organization to Active. The platform administrator is an
attributed bootstrap actor only and is never a representation, membership,
authority, participation, registration, or workforce subject. This M2.1 slice
is implemented with additive migrations, database constraints, service/HTML
adapters, minimized evidence, and backend security tests. Populated and fresh
migration, local restore-drill, sensitive-read/denial audit, and responsive
browser evidence pass; the final consolidated suite/coverage gate remains
pending.

ADR 0041 accepts the next authorization lattice—organization → edition → exact
department → exact typed resource—with trusted server-resolved targets and no
implicit hierarchy inheritance. It is an implementation contract, not current
capability: department/resource grants and assignments are not yet persisted.
ADR 0042 makes every repository fixture and tutorial synthetic and deletes the
old public-roster rehearsal path. ADR 0043 adds audited platform emergency
containment across all of one controller's organizations. Database guards in
organizations `0009`–`0012`, participation `0004`, registration `0031`, and
workforce `0003` protect governance provenance and the IDN-011
non-participating-platform invariant below the ORM.

```text
Attendee web ─┐
Administration / Convention work ├── Versioned REST API ── Django modular monolith
Mobile app   ─┤                              │
Kiosks       ─┤                    PostgreSQL system of record
Signage      ─┘                              │
                                  Workers, cache, object storage
                                             │
                                     External adapters
```

The monolith is a deliberate reliability and maintainability choice. Module
boundaries prepare the system for future extraction without paying distributed
systems costs before they are justified.

## Foundational data hierarchy

```text
PlatformAccount
  ├─ explicit platform administration (no organization relationship)
  └─ accepted organization relationship
       └─ Organization
            ├─ Executive Board representation
            │    └─ versioned appointments and scoped authority assignments
            └─ ConventionSeries
                 └─ EventEdition
                      ├─ Participation
                      ├─ Registration and orders
                      ├─ Programme and timetable
                      ├─ Workforce and shifts
                      ├─ Communications
                      └─ Operational records
```

Platform identity and organizer-owned records are distinct. A common login
identifier must never be used as a shortcut around tenant authorization.

An edition is the primary operational boundary. New editions copy templates or
configuration; they do not point at mutable records from an older edition.

## Proposed modules

| Module | Owns |
| --- | --- |
| `identity` | Platform accounts, authentication links, user security history |
| `organizations` | Tenants, convention series, memberships, accountable representation and appointments |
| `events` | Event-edition identity, lifecycle, dates, and locales |
| `planning` | Objectives, projects, tasks, dependencies, readiness, risks, decisions |
| `participation` | Edition capacities, roles, status history, archive views |
| `registration` | Registrations, eligibility, badges, check-in |
| `commerce` | Products, orders, payments, refunds, invoices, inventory |
| `finance` | Budgets, approvals, procurement, expenses, contracts, sponsorship |
| `content` | Pages, structured content, media, translations, public metadata |
| `programme` | Submissions, reviews, sessions, hosts, publication |
| `scheduling` | Timetable versions, constraints, conflicts, views, calendars |
| `workforce` | Applications, onboarding, qualifications, shifts, time records |
| `venues` | Sites, spaces, bookings, lodging, travel, hospitality |
| `accreditation` | Credentials, access zones, issuance, verification, revocation |
| `logistics` | Assets, stock, custody, movements, vehicles, supplier delivery |
| `dealers` | Dealer applications, reviews, assistants, tables, documents |
| `messaging` | Conversations, team inboxes, participants, notes, attachments |
| `announcements` | Canonical announcements, audiences, approval, delivery |
| `knowledge` | Policies, runbooks, forms, acknowledgements, service catalog |
| `reporting` | Safe query definitions, read models, saved views, dashboards |
| `exports` | CSV, XLSX, PDF, iCalendar jobs and secured artifacts |
| `operations` | Live command, dispatch, run-of-show, queues, lost and found |
| `safety` | Separated restricted cases, duty routing, accessibility coordination |
| `stage` | Technical riders, cues, equipment, rehearsals, run-of-show |
| `signage` | Screens, playlists, layouts, emergency overrides |
| `auctions` | Lots, intake, bidders, bids, settlement, collection |
| `engagement` | Opt-in activities, achievements, feedback, limited analytics |
| `automation` | Versioned rules, triggers, approvals, execution history |
| `audit` | Privileged audit events, integrity checks, audit access |
| `effects` | Versioned domain facts, transactional outbox, delivery state |
| `activity` | Audience-safe operational renditions of allowlisted domain facts |
| `integrations` | External channel, payment, mail, storage, and identity adapters |

This is a target map, not permission to scaffold every module immediately.
Modules are introduced through vertical product slices.

## Module contracts

Each module exposes three possible contract types:

- **Commands:** Authorized state-changing operations such as
  `ApproveRegistration` or `PublishSchedule`.
- **Queries:** Purpose-specific reads and read models. Queries return only fields
  the caller is authorized to see.
- **Domain events:** Facts that already occurred, published after transaction
  commit through a transactional outbox.

Models, private services, and internal repository helpers are not public
contracts. Direct cross-module database access is prohibited except in an
explicit application service that owns the transaction and is covered by an
architecture test.

## Authorization model

Authorization is a combination of:

```text
actor + capability + organization + edition + department + resource + fields
```

Examples:

- Registration may verify a legal name without seeing an HR case.
- A department lead may assign shifts only within their edition and department.
- Front Desk may see a safe registration summary but not payment internals.
- IT may inspect delivery failures without reading message content by default.
- A user may see their own archived participation across organizers, while each
  organizer sees only its own records.

Roles are convenient bundles of capabilities, not hard-coded authorization
decisions. Capabilities may be delegated with an expiry. Every list endpoint
must filter unauthorized records; checking only detail endpoints is
insufficient.

## Archival design

Edition lifecycle:

```text
draft -> preparation -> live -> closing -> archived
```

Archiving will:

- prevent ordinary writes;
- retain durable participation and publication snapshots;
- freeze historical labels required to interpret records;
- continue enforcing tenant, resource, and field permissions;
- start or continue data-category-specific retention schedules;
- allow corrections only through an audited correction workflow.

Historical participation is modeled explicitly. It is not reconstructed from
current group membership or current role names.

## Activity and audit boundaries

Three streams must not be conflated:

1. **Security audit:** Sign-ins, account changes, privileged reads, mutations,
   exports, permission changes, and integration credentials.
2. **Operational timeline:** Domain events useful for understanding a
   registration, application, order, conversation, schedule, or case.
3. **Engagement analytics:** Optional measurements used to improve the event.

The first two are purpose-bound operational records. The third requires its own
documented purpose, minimization, retention, and user-facing treatment.

## Messaging and announcements

Messaging is persistent, scoped work communication rather than a general chat
server. Domain objects can have associated conversations and internal notes.
Department inboxes provide assignment and continuity when staff rotate.

Announcements use a canonical platform record. Channel adapters transform and
deliver a channel-specific version to the website, email, push, X, Bluesky,
Telegram, Barq, or future destinations. Delivery is asynchronous, idempotent,
observable, retryable, and never the canonical source.

## Scheduling

Scheduling uses one planning graph with different projections:

- items: programme sessions, shifts, rehearsals, blocks, breaks, tasks;
- participants: attendees, hosts, volunteers, staff, departments;
- resources: rooms, stages, equipment, vehicles, capacities;
- constraints: availability, qualification, overlap, rest, transit, dependency;
- versions: draft, reviewed, approved, published, superseded;
- projections: attendee programme, personal commitments, department roster,
  venue grid, resource plan, cross-department dependency view, signage, print.

Warnings are explainable and link to the records causing them. Overrides are
explicit and audited.

## Query and export architecture

The safe query builder operates on a registered field catalog and purpose-built
read models. It never exposes arbitrary SQL.

Each field definition includes:

- human label and description;
- type and supported operators;
- organization and edition scope;
- sensitivity classification;
- required capability;
- export eligibility and formatting.

Exports are immutable, expiring artifacts generated by background workers.
Authorization is checked when an export is requested, generated, and
downloaded.

## Administration experience

One `/admin/` namespace is the product management shell. `/admin/` is its
permission-filtered home, `/admin/workspace/` embeds API-backed Convention work,
`/admin/platform/` owns collision-safe purpose-built platform journeys, and
Django application/model routes provide permission-filtered specialist
records. They share one sidebar, identity, edition-context grammar, and
record-oriented visual language. No embedded board may add another global menu
or become a second staff product.

Every active account may enter the Maru shell. Platform administrators receive
platform oversight; ordinary accounts see only current organization/edition
scope derived from effective grants or role assignments, plus their own open
governance invitations. Django `is_staff` and model permissions remain a
separate prerequisite for specialist model records and never grant convention
authority by themselves.

Organizer authority is compatibility-readable until the one-way ADR 0044
activation marker is committed. After activation, a grant or role assignment
is effective only through its own immutable issuance and the exact actor and
approver sources pinned there; policy never substitutes another equivalent
source. The marker and its pre-existing generation latch select the runtime
contract without process-local caching. A missing or malformed marker after
the latch has advanced fails closed, while deferred PostgreSQL guards reject
new reachable authority without complete provenance. Activation itself is a
stopped-writer, platform-operated maintenance command with count-only
pre/postflight, exact audit coupling, stale-writer serialization, and a
non-reversible migration fence.
The production release separately requires exact provenance after cutover; a
restored database without the exact marker then denies organizer authority and
fails public readiness instead of silently falling back to compatibility.

Pages 1–8 remain server-rendered adapters over current module services. Django
model administration does not become an authoritative write path for audited
cross-domain operations merely because it supplies the shell and specialist
record grammar. Explicit platform routes resolve before `admin.site.urls`, and
route placement or selected-edition state never grants authority. Backend
evidence covers route ordering, permission separation, exact-principal
disclosure, tenant isolation, concurrency, and audit/outbox atomicity. Local
populated/fresh migration, restore-drill, and desktop/narrow browser smoke pass.
The final consolidated suite/coverage rerun, representative deployment/PITR,
keyboard, automated accessibility, complete visual states, and owner evidence
remain before release acceptance.

The console will favor:

- role-specific work queues over model lists;
- global search and saved views;
- dense but readable tables;
- keyboard navigation and bulk actions;
- side panels or preserved context for quick inspection;
- visible status history and next actions;
- consistent filters and URL-addressable state;
- clear permission explanations without revealing protected information;
- asynchronous handling of slow reports, deliveries, and exports.

Performance budgets will be defined using realistic edition-sized datasets and
enforced with automated query-count and latency checks.

## Infrastructure boundaries

- PostgreSQL is authoritative.
- A queue/cache service may accelerate work but cannot be the only copy of
  important state.
- Object storage holds uploaded media and generated artifacts.
- External identity, payment, mail, and social services are adapters.
- A transactional outbox prevents committed domain changes from losing their
  required asynchronous follow-up.
- On-site clients must define degraded and reconciliation behavior before they
  are considered production-ready.
