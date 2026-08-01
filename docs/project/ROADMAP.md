# Roadmap

The roadmap is outcome-based. Dates are intentionally omitted until a team and
first convention partner are known.

## Current production-consolidation discipline

ADR 0030 established and preserved the accepted empty-experience baseline while
retaining the tested backend and APIs. ADR 0039 now supersedes that decision's
default URL configuration: the active milestone uses one coherent
`/admin/` shell with Convention work, specialist records, and Pages 1–7 under
the collision-safe `/admin/platform/` route space. Backend route, permission,
schema-drift, frontend build, populated/fresh migration, local restore-drill,
and desktop/390-pixel smoke evidence passes. The final consolidated local
backend invocation passes 792 tests in 329.21 seconds with 90.01 percent
coverage and no warnings. Accessibility, representative recovery/PITR,
complete visual-state, and owner evidence remain. ADR 0031
restored Page 1 as a platform-administrator-only organization inventory
without adding convention participation. ADR 0032 adds the name-only audited
Draft command, ADR 0033 expands Page 2 with the complete optional profile,
ADR 0034 adds the linked Page 3 record, compact one-row
**Organizations**/**+ Add** navigation, audited profile updates, and protected
empty-Draft deletion, and ADR 0035 adds organization-scoped Page 4 convention
series creation. M1 adds Page 5 series record, Page 6 audited/idempotent edition
creation, and Page 7 edition record plus explicit working context. ADR 0036
makes navigation progressive: global pages remain
global while selected-organization pages appear in a named contextual section,
and the desktop sidebar aligns to ordinary viewport padding. All retain the
no-governance and no-participation side-effect boundary. The
phase descriptions below are capability evidence and future outcomes, not a
list of currently mounted pages. ADR 0037 now groups page contracts into
executable vertical milestones so that complete journeys can advance without a
mandatory pause after every isolated page. Each page still requires UX-013's
scope, states, authorization, navigation, test, documentation, desktop, and
narrow-viewport evidence. ADR 0038 records that the locally verified M1 record
spine precedes M2 governance and computed scoped access; it does not weaken the
full ADR 0037 outcome. ADR 0039 selects the richer pre-reset record-oriented
visual grammar without restoring a second menu, Quick Start, direct
cross-domain saves, or legacy domain assumptions. ADR 0040 now starts M2.1 with
Page 8's explicit Executive Board representation lifecycle: exact verified
accounts accept their own invitations, at least two distinct controllers
cross-approve root authority, activation moves the Draft organization to
Active atomically, and the platform administrator remains external. Its
initial schema, service, HTML, authorization, and synthetic-fixture lifecycle
are backend-verified alongside the M1.1 shell. ADR 0041 implements exact
department/typed-resource scope without implicit hierarchy inheritance through
sealed targets, policy, commands, immutable bindings, and database guards.
Its contextual access editor remains unmounted, and exact actor/approver
authority-source provenance remains a production gate. ADR 0042 makes repository fixtures synthetic-
only and removes the public-roster rehearsal implementation. ADR 0043 adds
global platform emergency containment when a Board controller must be removed.
`PRODUCTION_CONSOLIDATION.md`
is the authoritative
mounted/API-only/preserved/partial/absent/deployment-gated ledger and current
milestone checklist.

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
- initial administration shell with embedded convention workflows.

Exit criterion: Automated tests demonstrate tenant isolation and edition
scoping through API, queries, administration, and audit.

Repository status: the backend foundation and preserved former `/admin/` shell
with embedded Convention work,
generated API types,
reference dataset, authority/audit/outbox spine, supervised worker, and recovery
drill are implemented. Verified identity, session security, scoped restrictions,
service notification delivery, safe media processing, privacy operations, and
closure evidence now extend that foundation. Guided tenant/series metadata,
searchable ISO/IANA locale setup and a contextual Setup guide reduce
clean-environment operator error without occupying global administration
chrome. One collapsible administration navigation, record-oriented Convention
work inner pages, a separate Forms home section, integrated specialist records,
and exact-person convention-group access sharing replace the visible
staff/admin split without introducing page ACLs or Django Groups.
Active scoped non-staff accounts enter that shell without gaining specialist
model access; effective grants/assignments drive organization and edition
navigation, while Django staff/model permission remains a separate boundary.
The preserved one-shot first-authority operator command/service is no longer
the normal establishment path under ADR 0040. Its browser ceremony and
management API are retired; recovery use requires an explicit legacy-
reconciliation procedure. Authorized leaders can still move editions through
valid, explained lifecycle transitions without directly editing lifecycle
fields.
ADR 0039 reintroduces that shell as the single management surface. Its
current services, APIs, policy checks, audit, and effects remain authoritative;
pre-reset screens supply layout and interaction grammar rather than a parallel
domain implementation. Backend route ordering, platform/scoped-nonstaff/staff
permissions, sidebar behavior, Convention work, specialist-record gating, and
frontend checks pass. The pre-hardening isolated suite/coverage baseline,
populated/fresh migrations, local restore through the representation boundary,
clean dependency audits, responsive smoke, and the final 792-test/90.01-percent
coverage gate pass locally without warnings. Accessibility, representative
restore/PITR, and complete visual-state evidence remain open. Broad user/staff activity
projections beyond the implemented registration actions also remain before
this phase is treated as complete across the whole product.

The accepted Pages 1–7 implement Page 1 organization inventory, complete
Page 2 Draft creation, Page 3 organization records for maintaining public
identity, legal/imprint, contact, and locale defaults, Page 4 creation of a
recurring public convention brand, Page 5 versioned series maintenance and
edition inventory, Page 6 shared HTML/API edition creation, and Page 7
versioned edition maintenance plus explicit working context. A
confirmed empty Draft can be deleted, but a created series or any other
protected relationship refuses deletion. Series creation generates scoped
identity and audit evidence only. Edition creation starts one Draft identity
with idempotency receipt, audit, domain event, and outbox; it does not create
registration, programme, venue, people, or workforce records. The access
summary distinguishes platform, Board, exact-edition, and own-invitation
authority but remains provisional: exact department/resource enforcement now
exists below the UI, while the computed human explanation and field-purpose
detail remain Phase 1 work. Draft organizations
created during this interval must be brought under the IDN-012 Executive Board
invariant before activation.

The accepted Page 8 contract is the first Phase 1 scope-v2 slice. It separates
the Executive Board representation aggregate from membership, departments,
participation, and generic role sharing; requires existing active verified
person accounts and invitee-owned versioned decisions; and defines atomic
two-or-more-controller activation with value-minimized audit/outbox evidence.
The local-only synthetic demo establishes two controllers per organization
through these real services rather than forcing Active state.
The working-tree implementation passes schema drift, tenant/principal non-
disclosure, core concurrency/replay, platform exclusion, cross-approval,
rollback, scoped-shell, populated/fresh migration, local restore through
organizations `0009`, bounded sensitive-read/denial audit, IDN-011 database
subject guards through organizations `0012` plus participation `0004`,
registration `0031`, and workforce `0003`, and desktop/390-pixel smoke gates.
The readiness/core focus passes 10 tests, the representation/platform matrix
passes 126 tests, the ordered migration-contamination regression passes 26
tests, and the final consolidated backend gate passes 792 tests in 329.21
seconds with 90.01 percent coverage and no warnings. A separate behavior run
passes the same 792 tests in 291.86 seconds. Representative restore/PITR,
accessibility, complete visual-state, and owner-rehearsal gates remain.

The later ADR 0041 implementation supersedes that backend baseline: all 876
tests pass in 458.05 seconds with 90.43 percent branch coverage. The populated
synthetic database applies the three-migration scope sequence with zero scope
or representation blockers, and platform/Board browser smoke preserves exact
foreign-organization denial. Exact actor/approver authority-source provenance
remains the next production gate before the contextual hierarchy editor.
Appointment expiry, routine replacement/removal,
planned suspension/reactivation, invitation delivery, root authority-source
provenance, the contextual department/resource assignment editor, and the full
effective-access header remain later M2 work.

The committed M1 spine is locally verified across the complete suite, migration rehearsal,
OpenAPI/client regeneration, deployment-shaped checks, and desktop/390-pixel
visual smoke. Owner rehearsal, automated accessibility analysis, reliable
keyboard traversal, and the remaining visual state matrix stay open and no
production-readiness claim follows from M1. M1.1 repeated backend/frontend,
coverage, populated-migration, and responsive-smoke evidence after the unified-
shell migration. The later integrity tree now passes the final consolidated
local suite and coverage gate; accessibility, complete visual-state,
representative recovery, and owner evidence remain before release acceptance.

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
implemented. The `/admin/` workspace now provides the five-gate closeout review
without raw organization/reviewer IDs or manual timestamps; the corresponding
Advanced-record table is inspection-only. Staff-assisted intake can
exact-match an active identity or
explicitly and atomically create a previously unseen unverified account; draft
form items are removable, and telephone entry is country-aware with E.164
storage. Reviewed post-submission profile extensions let attendees or
registration staff append missing edition information under per-field writer
policy without changing the immutable submission. Authoritative Infinity,
payment, entitlement, capacity, role, and restriction facts cannot be
reintroduced as extension fields.

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
dual-controlled role/capacity activation. The old one-shot bootstrap remains
only as an operator command/service for an approved legacy reconciliation; its
guarded browser ceremony and management API are retired. A minimized
Organization structure page shows
nested departments, positions, several holders, and multi-department roles
under exact edition scope.
Qualifications, availability,
shifts, work records, purpose-built approval UI, and the programme/schedule
side of this phase remain.

The reviewed legacy prototype supplies behavior-level acceptance input for
this phase: proposal revision history; an explicit approved-to-programme
transition; service days, layers, recurrence and ordered groups; shared
attendee/person/department/venue/print projections; conflict explanations;
and transactional volunteer demand, claim, confirmation, removal, lock and
completion states. These are to be implemented in current owning modules and
must not import the prototype's global-project or cross-domain-save design.

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

Behavior-level inputs retained from the legacy prototype include reusable
venue facts with explicit edition selection and overrides, canonical scheduled
announcements with per-channel delivery evidence, credentialed minimized read
projections, rotation/access telemetry, preview-first imports, and archive
views. Current tenancy, authorization, privacy, audit, connector, and closure
requirements remain authoritative.

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
