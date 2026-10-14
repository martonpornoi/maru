# Roadmap

Maru is built for furry conventions that want to adopt one useful workflow at a
time. This page explains the direction and remaining outcomes. It is not a list
of features that are ready for production.

[CURRENT](CURRENT.md) records the active work and verified state.
[Requirements](../product/requirements.md) define the product contracts;
[module documentation](../modules/index.md), [architecture decisions](../architecture/decisions/index.md)
and [checkpoints](../checkpoints/index.md) retain implementation detail and history.
Dates depend on the scope, measured work and the first adopting convention.

## Active direction: approachable furry-convention operations

The maintainer authorized this direction on 2026-10-08. Programme umbrella #48
is deferred, with its acceptance and activation gates still open. Everyday work
should be understandable to volunteers without event-management experience,
including people who use English as a second language. Advanced configuration
must remain accessible without dominating ordinary tasks (UX-031).

The following sequence guides development. It does not require a convention to
adopt an earlier workflow before using a later one.

| Focus | Complete outcome | Owning requirements |
| --- | --- | --- |
| Understandable work and contributor entry | Find a task, understand the next action, discover advanced settings when needed, and follow a clear contributor setup path. | UX-031, NFR-013 |
| Announcements | Write, independently review, prepare channel copy, record manual publication, correct mistakes and export the history while using existing publishing channels. | ANN-001–009 |
| Guides and help desk | Maintain reviewed instructions and FAQs, confirm required reading, and handle requests through replies, escalation, handover and lost-and-found custody. | KNO, MSG, OPS-007 |
| Volunteer and attendee services | Handle training, coverage exceptions, meals and rewards; keep useful fursuit-lounge and quiet-room information current. Restricted specialist case work needs its own review. | HR, FUR-007, SAF-007 |
| Dealers and charity | Allocate dealer tables, then complete one art or charity-auction format from item intake through bids, settlement evidence, collection and reporting. | FUR-001–005 |
| Arrival and collection | Handle registration exceptions, badges, merchandise pickup, refunds and degraded operation. | REG, ACC, FUR-006 |
| Hospitality and next-year handover | Coordinate guest, room and travel obligations, spending and sponsor commitments, creative contributions and reviewed lessons. | VEN, FIN, PLN, KNO, FUR-008–010 |

Approachable navigation and contributor entry were delivered through
[PR #209](https://github.com/martonpornoi/maru/pull/209). Consult CURRENT before
describing later workflows as available. External delivery adapters follow the
manual Announcements workflow individually, when their operating needs are known.

Each increment includes setup, ordinary use, exceptions, history, export and
recovery. Batch related changes for one final clean-commit certification and
independent hosted acceptance. Reuse neither older results nor a source preview
as evidence that a later workflow is accepted.

## Progressive adoption strategy

NFR-013 makes partial adoption a supported product choice. A convention may use
Maru for volunteers, communications, an auction or another complete workflow
while keeping its existing registration, payments and other systems.

Each adoption profile defines its required foundations, visible tasks, roles,
records and notifications; imports, exports and printable/manual fallbacks;
recovery and retention; and the explicit action needed to expand or stop using it.
Unselected capabilities must create no unrelated records or operational duties.
A volunteer, host, bidder or communications account does not imply attendance,
registration, payment tracking or unrelated data collection.

Keep profile versions exact. Adding a catalog entry must not silently expand an
existing edition's authority, navigation or effects. Cross-module work uses the
owning commands and queries, with explicit scope and current permission checks.
External integrations remain adapters rather than the source of truth.

### Current progressive-adoption outcome

`workforce_only@1` supports the Structure through Shifts journey with guided
setup and enforced coexistence. `full_convention@1` retains its existing meaning.
Assignment evidence must match the immutable edition profile: Workforce-only
creates no attendee Participation; incompatible evidence is an integrity conflict.
See [Workforce adoption and recovery](../operations/workforce-only-adoption-and-recovery.md).

[ADR 0117](../architecture/decisions/0117-standalone-manual-announcements.md)
defines the optional `announcements_only@1` workflow. Reviewed Guides follow
with explicit expansion of an existing edition. Later profiles must preserve
earlier records, authorities and profile meanings. Current implementation and
acceptance status belong in CURRENT rather than this roadmap.

`programme_operations@1` is the accepted target in
[ADR 0081](../architecture/decisions/0081-composite-programme-operations-adoption.md).
It combines Applications, Programme, Scheduling, Venues and Workforce over
shared foundations, excluding attendee Participation, Registration, payments,
attendance and unrelated modules. Its dormant implementation and isolated
evaluation do not activate it. Charity auction and Registration without payments
remain future independently adoptable outcomes.

## Current contributor-documentation outcome

Keep one short newcomer path: understand Maru, see its current maturity, run a
synthetic example and make a first contribution. Everyday tutorials should use
current UI wording. Deep reference, architecture and historical evidence remain
available through the documentation hubs, without becoming mandatory first reading.

Examples use fictional conventions and people. Add role guides and verified
screenshots as the corresponding interfaces become stable. Remove duplicated
status prose instead of maintaining competing project summaries.

## Current production-consolidation discipline

The application uses one coherent administration shell with task-focused
Convention work and secondary specialist records. The
[capability ledger](PRODUCTION_CONSOLIDATION.md#honest-capability-ledger) distinguishes
mounted, API-only, unmounted, partial, absent and deployment-gated work.
Code, tests and a visible page do not by themselves establish a complete journey.

Every accepted workflow needs tested tenant and edition isolation, object- and
field-level permissions, accountable mutations, recovery and useful failure
behavior. UI acceptance includes relevant roles, empty/error/stale states,
keyboard operation and narrow layouts. Native database, restricted-runtime,
browser, independent-human and deployment-owner evidence remain separate.
Production cutover additionally needs representative recovery/PITR, retention,
operational ownership and a convention partner's acceptance.

## Phase 0: Discovery and risk framing

Validate department workflows and terminology, data classifications, retention,
threats and access boundaries with a first convention. Existing research and
design support implementation; partner interviews and jurisdiction-specific
review are still needed for external validation. Each selected workflow needs a
bounded adoption and exit story before its implementation is treated as complete.

## Phase 1: Platform foundation

Maintain reproducible development, scoped identity/organization/edition records,
authorization, Audit, reliable effects, OpenAPI clients, synthetic fixtures and
the shared shell. Demonstrate tenant and edition isolation through commands,
queries, APIs, administration and Audit. The historical
[foundation backlog](BACKLOG.md) records its original acceptance contracts;
it is not the active work queue.

## Phase 2: Registration vertical slice

Complete products and entitlements, registration, an optional payment adapter,
badges, check-in, Front Desk search, personal history, exports and edition closing.
Acceptance follows a synthetic person through the selected journey, including
exceptions, degraded operation, closure and archive. Existing backend kernels
do not establish complete ordinary-person, provider or production acceptance.
Registration without payments must remain a valid independent adoption choice.

## Phase 3: Programme and workforce

Complete optional Programme setup, event submissions and review, accepted content,
conflict-aware scheduling, volunteer recruitment/onboarding, qualifications,
availability, shifts and work records. Include useful public, personal,
department, room and print projections and team communications.

The Programme outcome is one approved timetable that a department can staff and
operate on site without attendee systems, then recover or stop using safely.
Issue #48 remains deferred. Its open #92 human acceptance, #109 integrated
evaluation and #108 final activation must be reconciled before promotion.
Use the [acceptance evidence map](../operations/programme-acceptance-evidence.md)
and [maintainer walkthrough](../operations/programme-maintainer-walkthrough.md)
when resuming. Logical restore evidence does not replace production/PITR proof.

## Phase 4: Operational platform

Complete dealer/table planning, Announcements and selected external delivery,
signage, stage technical planning, operations requests, assets/lost and found,
safe department reporting and portable runbooks. For each adopted workflow,
people must be able to rely on its records through a real handover and degraded
operation, without maintaining a second authoritative spreadsheet.

Existing Venue and Logistics kernels supply reusable facts and bounded inventory,
custody and movement behavior. Demand/reservation planning, transport routing,
supplier-invoice links, low-stock/wastage rules and full loss/disposal workflows
still need complete selected journeys. A kernel does not make all of on-site
operations ready to adopt.

## Phase 5: Extended convention ecosystem

Choose the next complete capability according to a convention's need: merchandise
and fulfilment; charity and art auctions; activities; guests and travel; volunteer
meals and rewards; accounting/logistics integrations; or supported extensions.
Define acceptance separately for each choice rather than promising every feature.

The charity directory and edition catalog are bounded foundations. Campaigns,
donation/settlement reconciliation, auctions, refunds/exchanges, supplier and
shipping fulfilment, handover and accounting export retain their separate scope.
Media/layout references do not constitute an upload, malware-scanning, object
storage or rendition service. Regulated payment processing, statutory accounting,
emergency services and specialist creative tools remain integration boundaries.

The [delivery plan](DELIVERY_PLAN.md) retains the broader lifecycle catalogue;
the [capability map](../product/capability-map.md) describes the product horizon.
Neither supersedes the active priorities or acceptance boundaries above.

## Contributor workflow baseline

PR #211 delivered disposable preview startup and clarified routine risk-selected
testing. Guides remains the next product outcome; exhaustive testing is still
required for global safety and test infrastructure changes.
