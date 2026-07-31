# Events module

Status: Implemented V02 integrated kernel with guided locale entry  
Last updated: 2026-07-29

## Purpose and requirements

`maru.events` owns edition identity and lifecycle for EVT-002 through EVT-005
and ARC-003.

## Owned data and invariants

- organization and convention-series scope;
- case-insensitively series-scoped slug and display name;
- IANA time zone, ordered language/currency codes, and date range;
- draft, preparing, ready, live, closing, archived, and cancelled states;
- monotonic lifecycle version;
- reasoned, append-only lifecycle transition history; and
- archive amendments.

PostgreSQL checks the date range and rejects an organization/series mismatch
even if ORM validation is bypassed. Database guards also require a valid
lifecycle edge and an exact version increment. Once archived, an edition
cannot be updated or deleted through normal model, bulk ORM, or SQL paths
governed by the application database role.

## Commands and API

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
- `GET /api/v1/organizations/{organization_id}/editions`
- `GET /api/v1/organizations/{organization_id}/editions/autocomplete`
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/transition`
- `POST /api/v1/organizations/{organization_id}/editions/bulk-transition`

The list supports bounded page size, exact lifecycle filter, and literal
name/slug search. Organization scope is required for count/list/search;
edition-scoped grants intentionally remain detail-only.

Autocomplete requires the same organization-level `events.view_basic`
authority as list/search, accepts a required literal query, returns at most 20
minimized suggestions, and deliberately omits a total count.

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

Edition lists show convention name, organization, series, lifecycle, dates,
time zone, and lifecycle version with search and scope filters. Lifecycle is
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

ADR 0008 adds a persistent bootstrap-administration convention-workspace
selector. Once an edition is selected, edition-owned lists, direct object
lookup, ordinary foreign-key choices, and new-record defaults use that edition.
`All foundation data` deliberately clears the context so a bootstrap
administrator can create the first organization, series, or edition. This is a
query and navigation context only; it does not grant authority.

## Failure and concurrency

Transitions use `select_for_update`. Bulk transitions lock their complete
tenant-scoped target set before mutation, so a mixed-authority, missing,
cross-tenant, invalid-state, or effect-failure request changes nothing. Denied,
unknown, and cross-tenant bulk identifiers share one external unavailable
shape; the protected audit retains the actual outcome without target IDs.

Invalid skips, blank reasons, terminal transitions, and outbox failure cannot
leave partial canonical state. Denial and failure receive safe audit evidence.
Database triggers defend edition scope, lifecycle/version integrity,
transition immutability, and archive immutability.

## Retention and archive

Archived edition identity remains readable and immutable. Corrections are
separate `ArchiveAmendment` records; their authorized command and projection
remain future work.

## Tests

PostgreSQL tests cover the full lifecycle, invalid transitions, reason, scope
triggers, date constraints, raw lifecycle bypass, append-only transition
history, archived model/bulk mutation, archive snapshot orchestration,
authorization, correlated audit/event/outbox, autocomplete minimization,
mixed-authority target freezing, safe unknown-target errors, and atomic
single/bulk rollback on validation or effect failure.

## Limitations

Cancellation closeout, template cloning, archive-amendment API, date-format
policy, venues, and richer edition-local policy are not implemented.
