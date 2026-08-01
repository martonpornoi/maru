# Events module

Status: Implemented edition aggregate, shared creation/profile commands,
mounted Pages 6–7, and authorized lifecycle kernel
Last updated: 2026-08-01

## Purpose and requirements

`maru.events` owns edition identity and lifecycle for EVT-002 through EVT-005,
ARC-003, UX-009, UX-022, and UX-023.

## Owned data and invariants

- organization and convention-series scope;
- case-insensitively series-scoped slug and display name;
- IANA time zone, ordered language/currency codes, and date range;
- draft, preparing, ready, live, closing, archived, and cancelled states;
- one monotonic aggregate version across profile and lifecycle commands;
- a separate monotonic lifecycle-history version;
- immutable actor/series/idempotency receipts for creation retries;
- reasoned, append-only lifecycle transition history; and
- archive amendments.

PostgreSQL checks ordered dates, limits the span to 31 days, and rejects an
organization/series mismatch even if ORM validation is bypassed. Database
guards keep organization, series, and slug immutable; require an exact
aggregate-version increment for either a profile or lifecycle change; forbid
combining those commands; and limit profile changes to Draft or Preparing.
Creation receipts are append-only, must match edition scope, and store only a
database-validated lowercase SHA-256 request digest. Lifecycle
guards also require a valid edge and exact lifecycle-version increment. Once
archived, an edition cannot be updated or deleted through normal model, bulk
ORM, or SQL paths
governed by the application database role.

## Commands and API

`create_event_edition(...)` is the canonical HTML/API creation command. It
requires `events.create`, normalizes and validates the complete input, locks the
exact organization and series, refuses a Closed organization or inactive
series, and generates a series-scoped stable slug. Edition, append-only retry
receipt, minimized audit, `events.edition.created.v1`, and outbox delivery
commit together. A repeated actor/series/key with the same normalized payload
returns the first edition; a changed payload conflicts.

`update_event_edition(...)` requires `events.change_profile` at exact edition
scope. It locks organization, series, and edition, compares the expected
aggregate version, permits only Draft/Preparing beneath a non-Closed
organization, writes actual changes only, and publishes
`events.edition.details_updated.v1` atomically with audit/outbox. No-op updates
advance nothing.

`platform_editions()` is the explicit C1 identity query used only after a
platform-administrator boundary has been established. The preserved context
API labels those rows `not_participating`, returns no capacities, and creates no
edition relationship for the administrator.

`transition_edition` requires an exact `events.transition` edition grant or an
explicit platform-administration policy decision, locks the row, validates a
state-machine edge, requires a reason, increments the
aggregate version, records the transition, and finalizes participation label
snapshots before archiving.

It then writes a correlated security audit event and a versioned domain event
plus outbox message in the same transaction.

Convention work's Setup guide presents the current state, only the valid
next lifecycle edges, a plain-language consequence, and a mandatory reason.
Cancellation and archival also require an explicit terminal-action
acknowledgement. The context projection says whether the signed-in person holds
`events.transition`; hiding a control is informational only and the command,
API policy, readiness checks, row lock, audit, and database triggers remain
authoritative. Registration activation and sales windows are separate from
edition lifecycle.

- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}`
- `PUT /api/v1/organizations/{organization_id}/editions/{edition_id}`
- `GET` and `POST /api/v1/organizations/{organization_id}/editions`
- `GET /api/v1/organizations/{organization_id}/editions/autocomplete`
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/transition`
- `POST /api/v1/organizations/{organization_id}/editions/bulk-transition`

The list supports bounded page size, exact lifecycle filter, and literal
name/slug search. Organization scope is required for count/list/search;
edition-scoped grants intentionally remain detail-only.

Creation and profile replacement reject undeclared JSON fields. Name, ordered
dates, IANA zone, 1–16 unique language codes, and 1–8 unique ISO 4217 currency
codes are validated again in the application service; the database defends
durable scope, dates, version, lifecycle, and receipt invariants. The complete
NFR-009 table and stable page states are in the
[Page 6](../product/page-contracts/06-create-event-edition.md) and
[Page 7](../product/page-contracts/07-event-edition-record.md) contracts.

The browser keeps its UUID retry key as a declared hidden form field. The API
requires the equivalent UUID in the `Idempotency-Key` request header and
rejects `idempotency_key` in JSON along with every other undeclared body field.

Autocomplete requires the same organization-level `events.view_basic`
authority as list/search, accepts a required literal query, returns at most 20
minimized suggestions, and deliberately omits a total count. List and
autocomplete reject undeclared query parameters; exact-detail GET accepts none.
Problem response components require only their invariant RFC 9457 members and
keep request identifiers and field-error details optional.

`bulk_transition_editions` accepts at most 25 unique edition identifiers. It
tenant-filters and locks the exact set in deterministic order, then authorizes
every edition before making any change. The command preserves input order in
its result and commits all target transitions, audits, domain events, and
outbox messages atomically.

Edition closeout uses:

- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/closure-readiness`;
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/closure-gates/{code}`;
  and
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/closure-manifest`.

The Convention work setup guide is the human readiness-review workflow.
The operator chooses one of the five named gates and supplies a readable
evidence reference plus a review summary. Maru takes organization and edition
scope from the selected workspace and records the signed-in reviewer and
server time automatically. The evidence reference should be a recognizable
report name, controlled ticket/checklist reference, or secure document link;
it is not a database ID.

## Permission and sensitivity

Edition public metadata can eventually become C0 only through publication.
Draft identity and lifecycle are C1. Basic reads require `events.view_basic`;
lifecycle mutation requires `events.transition`, a reason, and audit.

## Bootstrap administration

The current baseline mounts Page 6 edition creation beneath an exact series
and Page 7 as the edition record/home. Progressive navigation reveals only the
selected organization, series, and edition. Page 7 supports explicit POST-only
**Use as working edition** and **Clear working edition** actions. The session
selection is display/query context, creates no authority or participation, and
is not performed automatically after creation.

The first effective-access summary labels active platform-administrator
oversight separately from convention participation. It is intentionally
static/provisional until M2 adds organization representation and department/
resource scope; it does not claim that convention groups or people have
access.

Edition lists show convention name, organization, series, lifecycle, dates,
time zone, and aggregate version with search and scope filters. Lifecycle is
not directly editable: transitions and archive amendments are command-owned,
searchable, read-only history with readable actor and reason summaries.
Archived editions are view-only and ordinary deletion is disabled.

Edition language and time-zone fields use the same searchable reference
choices as organization defaults. They store stable ISO language codes and an
IANA time-zone identifier. Labels show language names and current UTC standard
and daylight-saving offsets; labels are presentation only.

Readiness-gate records are read-only in Specialist records. Their list shows the
reviewer by display name and does not offer an Add form. Creation and
replacement must pass through the capability-checked, audited Convention
work/API workflow so raw organization IDs, reviewer IDs, or manual
timestamps cannot bypass the domain service.

ADR 0008's preserved workspace selector remains relevant behavior evidence.
The controlled baseline now exposes the smaller explicit Page 7 session action
rather than mounting the former selector or `All foundation data` workflow.

## Failure and concurrency

Creation, profile updates, and transitions use `select_for_update`. Bulk
transitions lock their complete tenant-scoped target set before mutation, so a
mixed-authority, missing,
cross-tenant, invalid-state, or effect-failure request changes nothing. Denied,
unknown, and cross-tenant bulk identifiers share one external unavailable
shape; the protected audit retains the actual outcome without target IDs.

Invalid skips, blank reasons, terminal transitions, and outbox failure cannot
leave partial canonical state. Denial and failure receive safe audit evidence.
Database triggers defend stable edition scope/slug, date range, aggregate and
lifecycle version integrity, separate command categories, editable profile
lifecycle, receipt scope/immutability, transition immutability, and archive
immutability.

The schema change requires a maintenance-window deployment: all application
nodes must move to aggregate-version-aware code together. Existing aggregate
versions are backfilled to at least lifecycle version, and migration stops
before adding the span constraint if any historical edition exceeds 31 days,
has more than 16 languages or eight currencies, or uses an unsupported pinned
ISO 4217 currency code.
The final migration fences destructive downgrade whenever an edition or
creation receipt exists, including pre-existing editions. Populated rollback
to old application code is unsafe; use the
[edition migration and recovery runbook](../operations/edition-workspace-migration-and-recovery.md)
and fix forward or follow an explicitly approved backup/PITR recovery plan.

## Retention and archive

Archived edition identity remains readable and immutable. Corrections are
separate `ArchiveAmendment` records; their authorized command and projection
remain future work.

## Tests

PostgreSQL tests cover creation, idempotent replay/conflict, strict inputs,
profile update/no-op/stale behavior, date/locale/currency/slug validation,
scope and version triggers, receipt immutability, populated downgrade refusal,
audit/event/outbox rollback, Pages 6–7, strict explicit working context, and
non-participation. They also cover the
full lifecycle, invalid transitions, reason, scope
triggers, date constraints, raw lifecycle bypass, append-only transition
history, archived model/bulk mutation, archive snapshot orchestration,
authorization, correlated audit/event/outbox, autocomplete minimization,
mixed-authority target freezing, safe unknown-target errors, and atomic
single/bulk rollback on validation or effect failure.

## Limitations

Cancellation closeout, template/configuration cloning, archive-amendment API,
computed effective-access management, date-format preference, venues, and
richer edition-local policy are not implemented. Edition creation inherits
only visible locale defaults; it does not create or publish registration or
any operational configuration.
