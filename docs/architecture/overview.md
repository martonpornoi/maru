# Architecture overview

Status: Baseline  
Last updated: 2026-07-26

## System shape

Maru is an API-first modular monolith. One Django deployment may host multiple
organizations and event editions, while separate clients consume versioned
APIs.

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
  └─ OrganizationMembership
       └─ Organization
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
| `organizations` | Tenants, convention series, memberships, departments |
| `events` | Event editions, lifecycle, venues, rooms, resources, locales |
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

Django admin is a bootstrap and emergency data-management interface. The staff
operations console is task-oriented and API-driven.

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
