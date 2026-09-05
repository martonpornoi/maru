# Events module

Status: Implemented edition aggregate, immutable full-convention and
Workforce-only adoption profiles, guided Workforce setup, shared
creation/profile commands, Event edition record, authorized lifecycle kernel,
profile-scoped unified-shell context, and dormant Programme and Applications
reference seams; Programme Operations remains inactive
Last updated: 2026-09-02

## Purpose and requirements

`maru.events` owns edition identity, adoption profile, and lifecycle for EVT-002
through EVT-006, ARC-003, UX-009, UX-022, UX-023, UX-030, and NFR-013.

## Owned data and invariants

- organization and convention-series scope;
- immutable code-owned adoption-profile code and version;
- case-insensitively series-scoped slug and display name;
- IANA time zone, ordered language/currency codes, and date range;
- draft, preparing, ready, live, closing, archived, and cancelled states;
- one monotonic aggregate version across profile and lifecycle commands;
- a separate monotonic lifecycle-history version;
- immutable actor/series/idempotency receipts for creation retries;
- append-only, scope-validated Workforce-adoption setup receipts;
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

Existing editions migrate additively to `full_convention@1`. A new edition
chooses `full_convention@1` or `workforce_only@1`; its profile cannot be
changed by model save, bulk ORM, or direct SQL. Workforce-only stores `XXX` as
an internal no-currency sentinel and rejects later currency configuration.

## Commands and API

`create_event_edition(...)` is the canonical HTML/API creation command. It
requires `events.create`, normalizes and validates the complete input, locks the
exact organization and series, refuses a Closed organization or inactive
series, and generates a series-scoped stable slug. Edition, append-only retry
receipt, minimized audit, `events.edition.created.v1`, and outbox delivery
commit together. A repeated actor/series/key with the same normalized payload
returns the first edition; a changed payload conflicts.
Replay derives that comparison from the receipt edition's retained exact
profile code/version before consulting today's selectable mapping or Maru-
operator expansion policy. Exact retries therefore survive profile retirement,
version advancement, or later representation changes while that retained exact
manifest remains supported; an unknown retained pair fails closed without
consulting today's selector. Model and read projections use the complete
persisted-code choice set, while setup controls display only current selectable
codes and still accept a retired code when an HTTP/form retry reaches its
existing receipt. A new key uses the current selectable version and current
expansion policy.

Creation also validates and persists the requested adoption profile. A Maru-
operator organization may create only Workforce-only editions through ordinary
operator authority; creating a full-convention edition requires explicit
platform oversight. Existing Executive Board organizations retain the normal
full-convention path.

`set_up_workforce_adoption(...)` is the atomic, idempotent platform workflow
for UX-030. It creates or reuses Organization → Convention series → Event
edition, provisions truthful Maru operators only when no representation exists,
stores one append-only setup receipt, and creates no Participation,
Registration, payment, attendance, or unrelated module record. An Active
organization without accountable representation fails before partial child
creation.

`update_event_edition(...)` requires `events.change_profile` at exact edition
scope. It locks organization, series, and edition, compares the expected
aggregate version, permits only Draft/Preparing beneath a non-Closed
organization, writes actual changes only, and publishes
`events.edition.details_updated.v1` atomically with audit/outbox. No-op updates
advance nothing.

The profile catalog is the immutable code-owned source for each exact
`(profile code, profile version)` pair. `full_convention@1` and
`workforce_only@1` now pin literal module namespaces, authorization
capabilities, ordered context destinations, stable shell destination kinds,
event/delivery routes, code-owned catalog entries, cross-module adapters,
conflict sources, reserved accountable roots, and the primary module. The
registry and selectable-profile mapping are read-only at runtime. A new
same-namespace capability, starter, adapter, destination, or event does not
enter either v1 manifest automatically.

Shell destinations additionally resolve through one closed governed-kind
catalog. Manifest validation rejects a typo, retired/nonexistent kind, or a
future kind until that identifier is deliberately registered and assigned to
a new or reviewed exact manifest. The item code used by search or pinning may
differ from this product-purpose kind; for example, `my.equipment_offers` uses
the governed profile kind `my.equipment-offers`.

Every edition consumer carries both persisted values. Authorization denies an
unknown pair before self, platform, grant, or role evaluation; ordinary role
bundles require a non-empty capability set wholly pinned by the exact
manifest. Registration discovery queries exact code/version pairs.
Applications rechecks exact starter, self-purpose, eligibility, source, and
accepted-target adapters at disclosure and command time. Workforce selects its
assignment-evidence adapter and built-in catalog entries exactly. Context APIs
omit an unknown exact-profile edition before its tenant or edition names are
projected. Bootstrap administration applies the same exact profile/capability
filter before platform selectors or direct routes load those names; an
unsupported selector candidate is omitted and an unsupported direct route is
not found. The unified shell removes every edition-scoped destination not
pinned by the manifest. Effects rejects an unpinned enqueue and quarantines a
queued delivery that no longer resolves.
These projections complement, rather than replace, object authorization and
database scope guards.

An unsupported persisted pair is an integrity/deployment incident, not an
instruction to infer the newest version. Stop edition-scoped writes and worker
replay, retain the edition, outbox, audit, and command evidence, and restore the
reviewed application release that declares that exact manifest. If the stored
pair itself is invalid, use a reviewed fix-forward migration or mutually
consistent whole-database recovery; never rewrite an edition to a newer profile
or add a wildcard fallback. Effects quarantine remains inspectable until the
compatible manifest and handler catalog are restored and explicitly replayed.

Adding a catalog member and adding it to a profile are two separate reviewed
changes. The owning module first declares one stable, versioned capability,
destination, effect route, catalog entry, adapter, or conflict source together
with its owner, result/failure semantics, and focused tests. Events' deployment
compatibility check must then recognize that independently registered member;
this registration alone does not change any existing manifest. To adopt it,
copy the complete reviewed behavior into a new immutable profile version,
extend the exact database guard and creation mapping with an additive
migration, prove old web/worker compatibility or fence downgrade, and only then
make the new version selectable. Never edit a v1 member set in place or map a
persisted code to an implicit latest version.

Typed adapter and conflict-source descriptors retain separate, non-empty
`result_semantics` and `failure_semantics`. The first states what one
trustworthy result means; the second states the fail-closed behavior when the
exact provider is unavailable, unpinned, ambiguous, or cannot make its
completeness claim. Empty prose is rejected while the owner catalog is built,
so a future profile cannot cite an adapter whose failure boundary exists only
in an unrelated runbook or implementation detail.

The `events.E001` compatibility check composes those owner catalogs lazily and
requires every manifest literal to resolve. It also rejects duplicate or
malformed owner entries, cross-catalog identity overlap, members owned outside
the adopted modules, selectable-pair drift, non-integer or boolean versions,
and disagreement with the independent database-supported exact-pair catalog.
Effects route resolution remains independently authoritative under
`effects.E001`. The database pair catalog builds the `EventEdition` check
constraint, so adding a manifest without its reviewed additive migration fails
both compatibility and migration-drift validation before deployment.

The empty Foundation adapter and conflict registries are sentinels, not a
synthetic product owner. New foundation behavior must be declared by its real
module owner and added explicitly to the compatibility union; it must not be
placed under a `foundation.*` namespace.

ADR 0081 accepts a successor `programme_operations@1` contract, but this
module does not yet declare, create, activate, or route that profile. Its target
manifest is keyed by the exact pair `(profile code, profile version)` and must
pin adopted product modules, capabilities, destinations, writers/effects, and
adapter/conflict sources. Adding a capability to a module catalog must not
silently widen an existing edition. The accepted product modules are
Applications, Programme, Scheduling, Venues, and Workforce; shared foundations
remain Audit, Authorization, Effects, Events, Identity, Organizations, and
Privacy. Programme now has a dormant installed namespace, private schema,
capability catalog, reserved adapter descriptor, and event definition;
Scheduling remains absent. Neither is executable under a current profile, and
the Programme declarations are deliberately absent from both existing v1
manifests.

ADR 0082 adds dormant Applications-owned Programme capabilities, the
`applications.self.programme_proposal@1` purpose descriptor,
`applications.target.programme_item@1`, and two registered event names. Those
declarations are also absent from both existing literal manifests, whose
fingerprints remain unchanged. Call domain activation or proposal submission
does not change an edition's profile, make `programme_operations@1` selectable,
or authorize any current destination, effect, target adapter, or writer.

ADR 0083 adds the Applications-owned
`applications.import.programme_call_proposal@1` adapter, two import/disposal
capabilities, and `applications.programme_import.changed.v1`. None is pinned by
either current manifest. The staged package, retention policy, source binding,
and preview evidence remain Applications data and do not change an
`EventEdition` profile. Stage, organizer preview, call commit, and proposal
claim consume the minimized private-planning reference; lead-self preview may
remain available after planning closes, while separately authorized disposal
deliberately does not require open planning writes. No lifecycle transition
activates the adapter or creates an import route, worker, or delivery.

ADR 0084 adds the dormant exact-Edition
`applications.recover_programme_department_ownership` declaration and
Applications/Workforce ownership-continuity commands. It does not alter either
current profile manifest or fingerprint. Reassigning or retiring an
Applications-owned call, reassigning or disposing an import batch, or probing
a Department retirement dependency cannot select a profile, register a
destination, activate an effect, create an Events row, or mount a handler. The
recovery declaration is absent from current platform roots as well as profile
manifests.

Recovery and export are mandatory profile contracts rather than implied module
adoption: version 1 must pin its continuity artifacts, regeneration, restore,
stop-use, and expansion behavior before activation. It does not gain every
present or future `exports` capability merely because continuity is required.

The accepted future setup location is
`/admin/platform/setup/programme-operations/`, but that route is deliberately
inactive in this contract-only change. It must provision an independently
approved, version-pinned Programme operator authority set rather than widening
the immutable Workforce operator role. Purpose-specific host, reviewer, and
volunteer relationships must not create attendee Participation, Registration,
payment, attendance, accreditation, or unrelated module records.

`resolve_private_planning_edition_reference(...)` is Events' minimized
cross-module lifecycle seam. It proves the exact organization, edition, and
series tenant chain, optionally locks the edition inside a caller-owned
transaction, and returns only the edition UUID, organization UUID, and a
boolean derived from Events' lifecycle catalog. Draft and Preparing accept
private planning writes; Ready, Live, Closing, Archived, and Cancelled do not.
Consumers therefore neither import the private `EventEdition` model nor copy
its lifecycle rule.

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

The guided Workforce-only setup is intentionally an HTML platform operation at
`/admin/platform/setup/workforce/`; no public setup API is declared yet.

The list supports bounded page size, exact lifecycle filter, and literal
name/slug search. Organization scope is required for count/list/search;
edition-scoped grants intentionally remain detail-only.

Creation and profile replacement reject undeclared JSON fields. Name, ordered
dates, IANA zone, 1–16 unique language codes, and 1–8 unique ISO 4217 currency
codes are validated again in the application service; the database defends
durable scope, dates, version, lifecycle, and receipt invariants. The complete
NFR-009 table and stable page states are in the
[Create event edition](../product/page-contracts/06-create-event-edition.md) and
[Event edition record](../product/page-contracts/07-event-edition-record.md) contracts.

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

ADR 0039 mounts Create event edition and the Event edition record/home below the exact
organization and series in `/admin/platform/`. Progressive navigation reveals
only the selected organization, series, and edition. Event edition record supports explicit
POST-only **Use as working edition** and **Clear working edition** actions. The session
selection is display/query context, creates no authority or participation, and
is not performed automatically after creation.

The effective-access summary separates active platform oversight from
organization-scoped accountable-representation view and exact-edition profile
authority. Platform oversight is still denied an unadopted exact-edition
module.

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

ADR 0008's workspace selector is mounted in the unified shell. Platform
administrators may select any edition; ordinary accounts see only editions
covered by current unrevoked role assignments or grants with valid delegation
ancestry. Future, expired, revoked, foreign, or stale session choices are
excluded and cleared. **All foundation data** clears display/query context; it
does not broaden authority. Event edition record also exposes its exact scoped POST action.
Select, rejected-clear, and clear change only the authenticated session: tests
freeze capability grants, role assignments, memberships, participation,
registration, audit, domain-event, and outbox counts across each action,
including when `events.view_basic` comes from the canonical Executive Board
assignment.

For Workforce-only, the record presents the immutable adoption boundary,
suppresses the irrelevant currency editor, and explains that Registration,
payments, and attendee Participation were not adopted.

## Failure and concurrency

Creation, profile updates, and transitions use `select_for_update`. Bulk
transitions lock their complete tenant-scoped target set before mutation, so a
mixed-authority, missing,
cross-tenant, invalid-state, or effect-failure request changes nothing. Denied,
unknown, and cross-tenant bulk identifiers share one external unavailable
shape; the protected audit retains the actual outcome without target IDs.

Invalid skips, blank reasons, terminal transitions, and outbox failure cannot
leave partial canonical state. Denial and failure receive safe audit evidence.
API adapters preserve stable authorization reason codes but replace caught
domain-exception text with operation-specific public messages, so an internal
authorization diagnostic cannot cross the HTTP boundary.
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
audit/event/outbox rollback, Create event edition and Event edition record, strict explicit working context, and
non-participation. Working-context tests additionally prove platform, direct-
grant, and canonical Executive Board selection/clear never write authority,
relationship, registration, audit, event, or outbox state. They also cover the
full lifecycle, invalid transitions, reason, scope
triggers, date constraints, raw lifecycle bypass, append-only transition
history, archived model/bulk mutation, archive snapshot orchestration,
authorization, correlated audit/event/outbox, autocomplete minimization,
mixed-authority target freezing, safe unknown-target errors, and atomic
single/bulk rollback on validation or effect failure.

## Limitations

Cancellation closeout, template/configuration cloning, archive-amendment API,
computed effective-access management, date-format preference, richer edition-
local policy, and Programme Operations setup are not implemented. Edition
creation inherits only visible locale
defaults; it does not create or publish registration or any operational
configuration. Nine dormant Programme capability declarations, dormant
Applications-owned Programme call/proposal, preview-first import, and
Department-ownership-continuity declarations, and minimized
Identity/Events/Authorization reference seams now exist, but the accepted ADR
0081 profile, setup route, destinations, current-
profile effects, accepted-item adapter implementation, and user surfaces remain
unavailable until their runtime and security acceptance issues merge.
