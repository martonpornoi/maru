# Roadmap

The roadmap is outcome-based. Dates are intentionally omitted until a team and
first convention partner are known.

## Phase 0: Discovery and risk framing

Outcomes:

- validated department workflows and terminology;
- first convention and edition configuration;
- data classification and retention matrix;
- threat model and permission matrix;
- architecture prototype for tenant and edition scoping;
- prioritized first vertical slice.

Exit criterion: Registration, HR, Programme, Front Desk, and IT can each confirm
that their critical workflow and access boundaries are represented.

Repository status: the research-based baseline, capability map, personas,
workflows, data model, authorization, privacy, threat, resilience, integration,
and delivery design are complete. Partner interviews and jurisdiction-specific
review remain required before this phase can be considered externally
validated. Foundation implementation may proceed without pretending that
validation already occurred.

## Phase 1: Platform foundation

Outcomes:

- Django project, development environment, CI, and documentation automation;
- accounts, organizations, convention series, event editions, memberships;
- capability-based scoped authorization;
- audit foundation and transactional outbox;
- OpenAPI conventions and generated client;
- reference convention test dataset;
- initial staff console shell.

Exit criterion: Automated tests demonstrate tenant isolation and edition
scoping through API, queries, administration, and audit.

Repository status: the initial Staff Console shell, generated API types,
reference dataset, authority/audit/outbox spine, supervised worker, and recovery
drill are implemented. Verified identity, session security, scoped restrictions,
service notification delivery, safe media processing, privacy operations, and
closure evidence now extend that foundation. Guided tenant/series metadata,
searchable ISO/IANA locale setup, and a password-confirmed browser adapter for
the one-shot first-authority service reduce clean-environment operator error.
Broad user/staff activity
projections beyond the implemented registration actions remain before this
phase is treated as complete across the whole product.

## Phase 2: Registration vertical slice

Outcomes:

- products and entitlements;
- registration lifecycle;
- payment-provider adapter;
- badge generation;
- check-in and degraded-operation design;
- Front Desk and Registration search;
- exports and personal history foundation;
- edition closing and archival rehearsal.

Exit criterion: A synthetic convention can register, pay, check in, close,
archive, and display participation history end to end.

Repository status: versioned forms, phased volunteer/early-bird/normal offers,
payment reservations and expiry, FIFO waitlists, controlled deadlines and
waivers, complete headless submission, hosted payment intent/authenticated
webhook, operational finance/receipts/refund/dispute/settlement, canonical
inbox/email delivery, entitlement, minor/guardian flow, safe moderated media,
privacy correction/retention receipts, credentials, signed offline check-in,
closure manifest, public reference definition, explicit prior-profile
suggestions, current-edition profile self-service, structured
pronoun/language/fursuit data, separately consented public country and
authoritative attendee labels, minimized public attendee list, staff
reconciliation, attendance/country reporting, and badge-data CSV are
implemented. Staff-assisted intake can exact-match an active identity or
explicitly and atomically create a previously unseen unverified account; draft
form items are removable, and telephone entry is country-aware with E.164
storage.

The repository-controlled safety boundary is complete, but the phase exit
criterion is not an automatic production approval. A concrete provider and
deployment must be certified; workers, SMTP, scanner/storage, telemetry, relay,
devices/printers, and retention policies must be provisioned; representative
load must be measured; and partner privacy, finance, security, safeguarding,
jurisdiction, operations, and go/no-go review must pass. Admission transfer,
product change/repricing, badge layout/printing, and broader fulfilment remain
explicit product gaps.

## Phase 3: Programme and workforce

Outcomes:

- programme submission and review;
- HR application and onboarding pipeline;
- qualifications, availability, shifts, and work records;
- shared conflict-aware timetable;
- attendee, personal, department, venue, and print projections;
- internal messaging and team inboxes.

Exit criterion: A programme item and volunteer can move from application through
published schedule and completed assignment with complete history.

Repository status: the first workforce onboarding slice is implemented:
one-shot empty-organization chair bootstrap, reusable furry-convention
position templates, edition department/reporting hierarchy, publishable
position opportunities, applications, reviewed PDF agreements, headcount, and
dual-controlled role/capacity activation. The one-shot bootstrap is now
available through a password-confirmed superuser form as well as its operator
command. Qualifications, availability,
shifts, work records, purpose-built approval UI, and the programme/schedule
side of this phase remain.

## Phase 4: Operational platform

Outcomes:

- dealers and table planning;
- canonical announcements and external connectors;
- signage;
- stage technical planning;
- operations cases, assets, and lost and found;
- safe query builder and department dashboards;
- mature export templates and runbooks.

Exit criterion: Core onsite departments can operate from Maru without parallel
spreadsheets being their authoritative source.

## Phase 5: Extended convention ecosystem

Possible outcomes, prioritized by partner need:

- merchandise and fulfilment;
- charity and art auctions;
- activities and achievements;
- guest and travel coordination;
- volunteer rewards and meals;
- deeper accounting and logistics integrations;
- supported extension SDK.

Exit criterion: Defined per selected capability; this phase is not a promise to
implement every possible feature.

The more detailed, vertical sequence is maintained in
[`DELIVERY_PLAN.md`](DELIVERY_PLAN.md); implementation-ready foundation work is
in [`BACKLOG.md`](BACKLOG.md).
