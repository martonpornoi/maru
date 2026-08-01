# Delivery plan

Status: Long-range product sequence; active execution is tracked separately
Last updated: 2026-08-01

Use `PRODUCTION_CONSOLIDATION.md` for current mounted state, the Awoostria-first
vertical milestone order, and the crash-safe implementation checklist. This
file remains the broader lifecycle catalogue and does not by itself indicate
that a capability is implemented or mounted.

The product is delivered as end-to-end slices. A slice includes domain rules,
API, authorization, audit/timeline, background effects, role experience,
documentation, observability, retention, and failure behavior. “Models and CRUD
complete” is not a usable outcome.

Dates depend on team size, partner edition, and external providers. Sequence is
the default; discovery may reorder later slices without weakening the platform
spine.

## Prioritization rules

1. Protect identity, tenancy, money, safety, and historical integrity first.
2. Make a small workflow complete before creating every module shell.
3. Prefer a shared primitive that removes three future tools.
4. Move recurring decisions and handovers into Maru before adding analytics.
5. Design live and archive behavior with the initial workflow.
6. A provider-specific integration follows the canonical Maru state.
7. Automate only after the human workflow and authority are understood.
8. Partner validation can change terminology and order, not bypass security.

## Wave 0 — trustworthy walking skeleton

### V00: Reproducible engineering foundation

**Outcome:** a contributor can set up, test, lint, document, migrate, and run a
minimal Django service predictably.

Includes Python project, settings boundaries, PostgreSQL development service,
test factories, static analysis, dependency lock, CI, health/build endpoints,
documentation checks, security-safe defaults, and initial runbooks.

**Exit:** a clean clone reaches a passing production-shaped test suite and
reports the exact build; no business data exists yet.

### V01: Organization and edition kernel

**Outcome:** one account can safely see its organizations, series, editions,
memberships, and participation through an API.

Includes custom account identity, organization, convention series, event
edition, membership, participation, locale/time-zone rules, lifecycle, tenant
context, synthetic reference convention, and archive-safe identifiers.

**Exit:** exhaustive tests prove that similarly privileged users in other
organizations and editions cannot list, search, retrieve, mutate, or infer the
records.

### V02: Authority, activity, and reliable effects

**Outcome:** every subsequent module can make a consistent permission decision,
record accountable activity, and schedule reliable asynchronous work.

Includes capability catalog, scoped grants, role bundles, policy result and
obligations, DRF enforcement, audit writer, operational-event envelope,
transactional outbox, idempotent worker protocol, security-history projection,
and diagnostic correlation.

**Exit:** one example command demonstrates allow, field-limited read, denial,
delegation/expiry, audit, outbox retry, and cross-tenant resistance end to end.

### V03: Unified shell and action center

**Outcome:** a user enters one coherent My Maru or Convention work context and can
act on assigned work rather than hunt through modules.

Includes frontend selection ADR, generated API client, organization/edition
switcher, action/attention projection, inbox placeholder, global search
contract, consistent object workspace, accessibility baseline, and role-aware
navigation.

**Exit:** synthetic attendees and staff see different safe home views and can
move from one action to its object without losing context.

## Wave 1 — one coherent convention

### V04: Conversations, requests, and knowledge

**Outcome:** an organizer can replace shared operational chat and dead-end forms
with persistent team inboxes and routed work.

Includes conversations, messages, internal notes, team queues, ownership,
service targets, classified attachments, form schemas/submissions, knowledge
items, policy acknowledgement, templates, notification preferences, and
search.

**Exit:** an attendee request and an internal handover are resolved with correct
visibility, continuity, notification, retention, and archive behavior.

### V05: People, departments, recruitment, and onboarding

**Outcome:** a department can define staffing need, accept applications, make a
fair decision, onboard a person, provision scoped access, and offboard cleanly.

Includes positions, application/review, conflicts, assignments, qualifications,
onboarding plans, agreements, assets/access tasks, provider reconciliation,
department cockpit, and contribution history.

**Exit:** a synthetic candidate becomes a ready staff member, changes role, and
leaves with access and ownership reconciled.

### V06: Shared commitments, timetable, and volunteer shifts

**Outcome:** people, rooms, resources, sessions, shifts, rehearsals, and
operational work participate in one conflict-aware time model.

Includes availability, schedule versions, placements, hard/soft constraints,
travel/setup/rest, shifts, selection/assignment, personal and department views,
publication skeleton, iCalendar, and override reasons.

**Exit:** a volunteer can choose a suitable shift and a planner can explain and
resolve every conflict through published and personal projections.

### V07: Programme from proposal to release

**Outcome:** a programme team collects, reviews, schedules, advances, and
publishes content without re-entering host or room data.

Includes calls, collaborative proposals, review rubrics/conflicts,
decisions/revisions, public rendition, host commitments, access/technical
advance, schedule releases, attendee programme, and print/signage feeds.

**Exit:** proposal to revised live release passes all workflow, permission,
localization, impact, and history scenarios.

### V08: Registration, catalog, order, and payment

**Outcome:** an attendee can register and obtain a reconciled entitlement while
staff can solve exceptions without card access or manual ledger repair.

Includes configurable forms, eligibility, catalog, quotas, pricing, reservations,
orders, payment adapter, refund/change/transfer, attendee timeline, service
view, wait list, receipts, and finance reconciliation.

**Exit:** load- and concurrency-tested registration covers pay, retry,
duplicate webhook, refund, transfer, capacity exhaustion, and exception.

### V09: Arrival, credentials, fulfilment, and Relay

**Outcome:** Front Desk can identify, check in, print, issue, revoke, and
reconcile during both normal and venue-outage operation.

Includes credential/access model, badge templates, stock custody, scanners,
check-in, item fulfilment, reprint/revoke, relay packaging, signed snapshots,
offline command journal, reconciliation console, and fallback pack.

**Exit:** a deliberate network outage and conflicting offline operations are
handled in a rehearsal with no silent double issue.

### V10: Announcements and coordinated publication

**Outcome:** one approved fact reaches internal inbox, web/API, mail/push,
social adapters, calendar, print source, and signage with visible delivery.

Includes canonical announcements, localization, audience, approval, urgency,
variants, provider adapters, manual publication task, receipts, correction, and
acknowledgement.

**Exit:** normal and emergency rehearsals show partial-provider failure,
correction, rate limit, and audience minimization without contradictory truth.

### V11: Now Mode and live change control

**Outcome:** volunteers, departments, service desks, and event command share an
actionable current view and can coordinate a major room change.

Includes run-of-show, dispatch, duty roles, handover, live issues, data
freshness, impact graph, atomic release, acknowledgements, queue/capacity
observations, load shedding, and incident operations log.

**Exit:** room loss, absent staff member, and provider outage drills meet
decision, communication, continuity, and reconciliation criteria.

### V12: Close, archive, learn, and clone

**Outcome:** an edition becomes a trustworthy history and a reviewed source for
the next edition.

Includes closeout/reconciliation board, retention execution, access expiry,
participation projection, archive manifest/integrity, amendments, lessons,
template promotion, selective clone, and cross-edition comparison context.

**Exit:** the reference edition closes and archives, a user sees correct
history, restricted data expires, and the next edition inherits only reviewed
configuration.

## Wave 2 — professional operating packs

These reuse the spine and may be reordered by partner need.

### V13: Venue, lodging, travel, and hospitality

Space graph, access routes, hotel inventory, fair allocation rounds, room
groups, guest travel, transfers, catering, lounge and hospitality obligations.

### V14: Dealers and commercial floor

Applications, review, wait list, agreements, payment, assistants, table/power
planning, setup slots, content/age policy, vendor support, and future-edition
reapplication.

### V15: Stage, production, signage, and media

Technical riders, room configurations, calls, rehearsals, cues, recordings,
media consent/assets, screen/player management, local cache, and emergency
override.

### V16: Logistics, assets, and suppliers

Inventory, kits, custody, requests/reservations, vehicle/load plans, storage,
delivery acceptance, maintenance, discrepancy, return, and disposition.

### V17: Budget, procurement, expenses, contracts, and sponsorship

Budget versions, commitments, approvals, purchase trail, reimbursement,
contract obligations, sponsor fulfilment, operational ledgers, and accounting
export.

### V18: Merchandise

Design and rights approval, supplier, preorder, variants, stock, sales/pickup,
refund, residual inventory, and reconciliation.

### V19: Art show, charity, and auction

Beneficiaries, campaigns, lot intake/provenance/rights, custody, display, bidder
eligibility, append-only bids, close, settlement, collection, and public report.

### V20: Accessibility, welfare, security, and safeguarding

Public access information, request coordination, minimum-disclosure tasks,
separated case types, duty routing, evidence custody, break glass, handover,
retention, and emergency-plan exercises.

This slice demands specialist and legal review. The operational-instruction
contract arrives earlier where needed; full case management does not ship as
generic CRUD.

### V21: Community experience pack

Fursuit lounge/lockers/water/repair, parade, photoshoots, meetups, gaming,
cafés, dances, competitions, content/age zones, capacity, queues, consent,
staffing, and optional private achievements.

## Wave 3 — leverage and ecosystem

### V22: Self-service intelligence and document studio

Semantic datasets, safe query builder, certified questions, department
dashboards, scheduled reports, CSV/XLSX/PDF/iCalendar/JSON, accessible document
templates, restricted-artifact controls, and reproducibility.

Basic fixed exports ship with the domains that need them; V22 makes the system
organizer-configurable.

### V23: Automation and planning assistance

Typed triggers/actions, dry run, permission ceiling, approvals, versioning,
rehearsal, run history, kill switch, solver assistance, and carefully bounded
AI-assisted drafts and summaries.

### V24: Supported application and connector ecosystem

Application manifests, organization installs, scopes, webhooks, SDKs, example
clients, connector certification, contract lifecycle, data exit, and extension
governance.

## Cross-slice release gate

Every slice must:

- map behavior to requirement IDs;
- document domain ownership and public contracts;
- test tenant, edition, object, field, state, and bulk authorization;
- test concurrency/idempotency and external failure where relevant;
- classify fields and define retention/archive behavior;
- expose operational and user-visible timelines appropriately;
- meet accessibility and performance budgets with reference data;
- document degraded behavior and support diagnostics;
- ship role-oriented documentation and migration/recovery notes;
- update `CURRENT.md`; and
- create a milestone checkpoint when its outcome becomes usable.

## What is deliberately deferred

- microservices without measured need;
- unrestricted organizer-written code;
- a general chat/social network;
- full statutory accounting;
- payment-card storage;
- emergency-services replacement;
- automatic consequential people decisions;
- opaque volunteer scoring;
- cross-organizer people search; and
- custom forks for each convention.
