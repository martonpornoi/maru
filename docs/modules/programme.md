# Programme module

Status: dormant private-domain foundation; no current adoption profile, route,
API, navigation, worker, or production writer

Last updated: 2026-09-10

## Purpose and ownership

Issue #88 is adding the HR-015 staffing continuation under ADR 0093. Local
Programme requirement persistence, immutable work terms, protected current reads
and paginated history are implemented, together with exact source selection and
Workforce-owned binding/recovery commands and exact-source Scheduling coverage.
The [native staffing continuation](../product/page-contracts/programme-staffing.md)
and focused synthetic browser rehearsal are implemented locally; complete
certification remains in progress.
This is not a delivered staffing workflow or an activated Programme profile.

## Programme staffing requirements

`scope_references.resolve_private_planning_edition_reference` wraps the Events
fact projection for Programme callers. Ordinary preauthorization stays read-only;
locking item, host, readiness, source and staffing paths acquire the public
canonical Workforce parent/edition scope before person or Programme rows. The
already-held edition lock protects the subsequent Events fact read. This ordering
prevents source/binding races from deadlocking at deferred evidence foreign keys;
it changes no profile admission, lifecycle, capability or independent field ceiling.

`staffing_sources.load_programme_staffing_selection` independently resolves the
exact current requirement and selected Scheduling alternative. It requires
Programme work-field authority and Scheduling planning authority, retains the
edition mutex across both reads, and rechecks Programme authority before release.
Candidate, occurrence, placement and service-day revisions must remain current;
the owning Programme item must still be active. Copying another alternative does
not replace the selected source. Its immutable
work/source digest is an optimistic comparison token, not portable authority.
A cross-owner writer must acquire the canonical Workforce scope first and
resolve the selection again before commit. This source read creates no demand.
The public pure `resolve_programme_staffing_selection` comparison uses already
authorized coherent Programme and Scheduling snapshots. It avoids reloading
whole projections for every coverage row and grants no authority of its own.

The separate `scheduling.staffing_queries.load_planning_staffing` composition
reads one item's complete requirements against an explicitly selected private
alternative under the canonical owner lock chain. Both Programme and Scheduling
authorize independently; Workforce binding and coverage purposes authorize again.
Exact source and work-term digests determine freshness, so changed instructions
or a moved source yield stale null counts while ordinary open/lock transitions
can retain current coverage. Copying an alternative neither selects nor rebinds
work. Missing Workforce authority is withheld, and an incomplete dependency makes
the whole layer unavailable rather than partially covered. Rows contain opaque
requirement/occurrence IDs and minimized states/counts, not work copy, rationale,
personnel or full availability. This composition stays outside the base planning
reader to preserve the owner dependency direction; it does not activate a route.

`change_programme_staffing_requirement` accepts a typed `ProgrammeStaffingChange`
under independent exact-edition `programme.manage_staffing` authority. Creation
requires a current owned occurrence, Position and Department, explicit work
instructions, whole UTC-minute work times within the edition envelope, and
exact item/occurrence/edition versions. Revision additionally pins the current
requirement version. Work need not equal the audience-facing interval: setup,
teardown, briefing, reporting place, headcount, break and minimum rest are
deliberate terms. References resolve through the owners' public identifier-only
seams rather than their private models.

One item retains at most 128 requirements, including retired needs. A
requirement retains at most 1,000 ordinary revisions, plus one reserved
retirement revision. Its stable occurrence identity cannot be reassigned.
Retirement copies the previous work terms unchanged and is terminal; it can
retain a closed Position or retired occurrence without rewriting that history.
It is not a cancellation of Workforce demand and does not affect a volunteer.

The canonical Workforce edition lock chain precedes Programme control/item and
requirement locks. Current authority, owner references and optimistic versions
are rechecked there. Each successful command atomically writes the current need,
immutable revision, Programme receipt, minimized `programme.item.changed.v1`
staffing event, audit and outbox evidence. Retry identity is actor/edition-bound;
same normalized intent returns historical identifiers, not current private
terms. Different intent conflicts, and current authorization remains mandatory.

`load_programme_staffing_requirements` requires the separate
`programme.view_staffing` capability and `staffing_requirements` field. It
returns a complete bounded set at one item version, excludes decision rationale
and historical actor fields from its SELECT, and grants no Workforce personnel
read. `load_programme_staffing_history` independently requires `staffing_history`
and releases restricted rationale only after audit. Pages contain at most fifty
revisions, pinned to an explicit inclusive version ceiling and exclusive cursor;
later changes never silently extend an in-progress historical read. Missing
revisions, malformed/future cursors, partial field decisions, revoked authority
or failed audit release no partial result.

Programme migrations `0010`–`0012` add scope/lifecycle, immutable-term,
reciprocal-evidence and truncate guards plus a populated downgrade fence.
Authorization `0028` adds two exact-edition capabilities without grants. Both
new tables remain runtime SELECT-only and neither executable profile gains
these capabilities. See [staffing recovery](../operations/programme-staffing-migration-and-recovery.md).

## Private item foundation

`maru.programme` owns the canonical private Programme item for one exact event
edition. It separates working information, delivery facts, Department
discussion, readiness evidence, and approved public copy so a future Programme
workspace can expose only the layer required for one task. It implements the
private item/readiness foundation of PRG-005, PRG-006, PRG-008, PLN-004,
EVT-006, EVT-007, AUD-001, AUD-003, AUD-005, PRI-001, NFR-002, NFR-003,
PRG-011, NFR-008 through NFR-010, and NFR-013 without claiming that Programme
Operations is active or usable. The boundary follows ADRs 0001, 0003, 0005,
0041, 0051, 0081, 0084, 0085, 0086, and 0087.

Programme does not own calls or proposal review, accepted Applications truth,
service days, occurrences, rooms, timetable release, volunteer Shifts,
personal schedules, attendance, Registration, or public pages. Applications
now owns a dormant Programme-call and collaborative-proposal kernel, including
shared answer history, contributor-owned profile revisions, exact sealed
proposal revisions, and included-collaborator acknowledgements. Its dedicated
[staged review and decisions kernel](programme-review.md) now also owns immutable
review policies, exact-seal evidence, independent decisions, and recipient-only
messages and acknowledgements. Its dedicated [accepted conversion](programme-conversion.md)
now owns the immutable transition receipt and orchestrates exactly one private
Programme item from a still-effective accepted revision. Review-side acceptance
alone is not conversion. Programme owns no proposal collaborator, and this
conversion creates no host or co-host; the separate
[host relationship boundary](programme-hosts.md) requires explicit invitation
and person-owned confirmation. [Scheduling](scheduling.md) owns dormant
occurrences and candidate placements. Workforce will later own Programme
staffing demand and Shift commitments.

Applications also owns the dormant preview-first staging evidence for imported
Programme calls and proposals. Staging and organizer preview create no call,
proposal, Programme item, or host; successful apply can invoke only the
protected Applications call/proposal commands and clears that item's private
payload. Source binding, exact-self claim, expiry, and continuity disposal
remain Applications concerns and grant Programme no access to source keys,
emails, answers, payloads, match state, or digests.

Applications also owns call and import-batch Department reassignment,
retirement dependency projection, and exact-ID historical-orphan recovery.
Programme neither reads that dependency state nor writes either owner.
Workforce receives only the closed `clear`, `blocked`, or `unavailable`
projection and no Programme/import identifier or content. Reassigning an
imported Draft call retains the original source binding and proves current
ownership through an immutable Applications receipt chain; no Programme item
or host relationship is created.

## Dormant adoption boundary

The module is installed so migrations, integrity checks, and typed contracts
can be deployed safely. The global catalogs declare the `programme` namespace,
core and host-purpose capabilities, one reserved accepted-application source
descriptor, and `programme.item.changed.v1`. Neither `full_convention@1` nor
`workforce_only@1` contains any of those declarations. Their literal manifest
fingerprints remain unchanged.

Consequently, every real current-profile Programme command and protected query
fails closed. An unrelated grant, direct model row, or same-namespace catalog
member cannot activate the module. There is no `programme_operations@1`
persisted pair, root role, setup choice, URL, serializer, form, template,
navigation destination, admin writer, handler route, worker, or background
schedule.

The canonical command code always calls normal Authorization and exact Effects
adoption checks. Successful transaction behavior is exercised only by a sealed
future-profile test harness that substitutes the not-yet-installed profile
admission decision while retaining the real database, audit, domain-event, and
outbox writers. This is a doubly gated automated-test seam: a non-default
authorizer is denied unless the automated-test setting is true and the live
database name starts with `test_`. Passing the argument or satisfying either
condition alone cannot widen runtime behavior; base and environment production
settings do not enable the flag. No alternate publisher or allow-by-default
path exists.

## Owned records

All records duplicate organization and edition ownership where disclosure or
cross-row validation depends on it. Foreign keys are protective and no field
contains an untyped foreign aggregate identity.

| Record | Contract |
| --- | --- |
| `ProgrammeEditionControl` | Lazy edition-wide optimistic control; absence means version 0. |
| `ProgrammeItem` | Stable UUID, closed kind and provenance, independent lifecycle, and optimistic item version. |
| `ProgrammeItemSourceBinding` | One immutable source binding; organizer items have no foreign source, while accepted items use a reciprocal foreign key to the exact Applications transition at version 1. |
| `ProgrammeWorkingRevision` | Append-only private title and working summary. |
| `ProgrammeDeliveryRevision` | Append-only technical, accessibility-delivery, and media-consent facts. It stores no diagnosis. |
| `ProgrammeDepartmentDiscussionEntry` | Append-only decision-focused Department note and actor evidence. |
| `ProgrammeReadinessRequirement` | Current disposition and dependency version for one closed concern. |
| `ProgrammeReadinessRequirementRevision` | Append-only requirement history and rationale. |
| `ProgrammeReadinessEvidence` | Append-only evidence state, source version, and the exact requirement/dependency/item versions it supports. |
| `ProgrammePublicRendition` | Immutable approved public fields, source item/working version, reviewer evidence, and an exact predecessor chain. It is not publication state. |
| `ProgrammeCommandReceipt` | Immutable retry key, normalized request digest, reason, actor, correlation, affected object, and resulting control/item versions. |

Organizer-created core kinds are `ceremony`, `break`, `announcement`, and
`organizer_core`. A created item starts `active`; that word means only that the
private aggregate is current. It does not mean accepted, ready, scheduled,
published, staffed, or live. `accepted_proposal` is available only through the
dedicated accepted adapter with `applications_accepted` provenance and one
reciprocal source binding. Organizer-created items cannot fabricate one.

## Information layers and field ceilings

The tables are intentionally separate rather than one generic JSON document.
This keeps the disclosure ceiling structural:

- item summaries contain identifiers and closed operational codes only;
- working projections contain the current internal title and summary, while a
  separately authorized history retains actor, reason, time, and version;
- delivery projections contain technical, accessibility-delivery, and
  media-consent facts only; delivery rationale is available only in its
  separately authorized history;
- Department discussion contains its retained note, actor, reason, and time;
- readiness projections contain states and source versions, with rationale
  available only in the separately authorized history;
- public projections contain only the latest rendition number, approved title,
  summary, and bounded content note. Reviewer, rationale, time, and private
  source item version are available only in the private review history.

A generic item or public-copy projection never includes private working text,
delivery facts, discussion, readiness rationale, source identifiers, reviewer
identity, or prior public renditions. Event payloads and success audits use
stable identifiers and bounded codes, never these text fields.

## Readiness semantics

Readiness concerns are closed to public copy, host confirmation, technical
needs, accessibility delivery, media consent, schedule availability, and
required files. Each concern is independently configured as `required` or
`not_applicable`. Current evidence may be `satisfied`, `blocked`, or
`unavailable`.

The projection derives exactly six explainable states:

- `not_applicable` from the current requirement disposition;
- `required` when no current evidence supports a required concern;
- `stale` when evidence names an older requirement or dependency version;
- `satisfied`, `blocked`, or `unavailable` from current evidence.

Working-copy changes advance only the public-copy dependency. Delivery changes
advance only technical-needs, accessibility-delivery, and media-consent
dependencies. Prior evidence remains immutable; it becomes stale by comparison
instead of being deleted or silently rewritten. There is no score, percentage,
inferred completion, automatic acceptance, schedule release, or publication
claim.

A newly configured concern starts at the latest applicable source item version:
public copy uses the latest working revision, and the three delivery concerns
use the latest delivery revision. It starts at zero only when no applicable
source exists. Reconfiguration preserves that concern's existing dependency
cursor until the relevant source layer changes.

Operator attestation may support any configured concern. A working revision or
public rendition may support only public-copy readiness, while a delivery
revision may support only the three delivery concerns. Typed evidence must bind
the source object's own sequence or rendition number and the requirement's
current dependency version. A later public rendition based on the same private
dependency does not silently invalidate existing readiness; Programme may
append new evidence when a fresh review is operationally required.

## Command contract

The dormant application service defines closed commands for organizer-core
creation, working and delivery revisions, Department discussion, readiness
configuration and evidence, and public-copy approval. Creation uses the exact
edition control version; the first item requires expected version 0. Item
commands use the exact item version. Every successful new intent advances its
applicable version once.

Commands normalize bounded inputs, acquire tenant and edition locks before
object locks, re-resolve the current actor, and authorize before and after the
trusted target is locked. Draft and Preparing editions are writable; later
edition lifecycle states fail closed. Exact retry of the same normalized intent
returns the original receipt result after authority and scope are rechecked.
Key reuse for a different operation or digest and stale versions fail closed.
Programme consumes Identity's active/verified account reference, Events' exact
private-planning edition reference, and Authorization's identifier-only policy
adapter. No private Identity or Events model crosses the module boundary.

One successful transaction appends the changed Programme state, immutable
receipt, minimized success audit, registered domain event, and transactional
outbox delivery. Audit, event, outbox, deferred-evidence, or database-guard
failure rolls the whole success transaction back. A required minimized denial
or error audit may be appended separately after rollback. It retains only
well-formed caller-supplied organization/edition scope identifiers and never a
Programme object, source, result identifier, or private value; malformed scope
values are minimized to null.

Public-copy approval is a bounded Programme content decision. It records the
reviewer and non-blank review reason as a new rendition without changing the
private item version or invalidating readiness evidence. Its event uses the
rendition's own aggregate stream. Approval does not implement Applications
review, moderation, timetable approval, release, or publication.

The C0 public-copy query reads only the approved-rendition relation and its four
approved projection fields. It returns the same absent result for an existing
item without approved copy, an unknown identifier, a sibling edition, or a
foreign organization; it never probes the private C1 item relation to distinguish
those cases.

## Authorization and queries

The dormant core item capability catalog is:

- `programme.view_private` and `programme.manage_items`;
- `programme.view_readiness` and `programme.manage_readiness`;
- `programme.view_delivery` and `programme.manage_delivery`;
- `programme.view_discussion`;
- `programme.view_public_copy`; and
- `programme.approve_public_copy`.

The separate [hosting catalog](programme-hosts.md) adds two exact-edition
manager/read capabilities and three non-persistable relationship-derived self
capabilities. Core item capabilities are persistable only at exact edition
scope. The PostgreSQL minimum-scope
function recognizes those exact-edition codes. Its downgrade fence refuses
catalog contraction after durable Programme grant or role evidence exists, but
current profile policy still denies every Programme capability because neither
v1 manifest pins one.

Queries return frozen layer-specific projections. Collection discovery is
tenant-first, edition-first, bounded, and deterministically ordered; an
authorized empty edition returns an empty collection. An absent or unauthorized
scope fails with the same non-disclosing authorization result. Authorized detail
reads use one non-disclosing unavailable result for absent items. Protected
layers authorize before loading labels or counts, reauthorize before release,
and append minimized sensitive-read audit evidence before returning values.
Operational histories are newest-first with a stable tie-breaker so the default
bound always retains the most recent rationale and review evidence.

The dormant editor's `list_programme_timetable_items` is a separate complete
inventory, not the general query's 200-row first page. It requires both
`item_summaries` and `working_information` under `programme.view_private` and
returns at most 2,000 current item identities, lifecycles, versions and private
working titles. A sentinel overflow or missing current working revision is
explicitly unavailable; neither becomes a partial unscheduled list. SQL selects
only the latest title/version and item facts, never summaries, delivery notes,
Department discussion, readiness evidence, public-copy review or host calendars.
The title is current private copy, not an approved public or historical title.
Final authorization and the required minimized audit precede disclosure.

## Event and adapter seams

The dormant [Scheduling contract](scheduling.md) consumes Programme's separately
authorized `load_programme_scheduling_dependencies` query for current item and
explicit host consequences. It sees only current deliberately shared per-item
periods in memory, never private proposal/review content or copied calendars in
candidate history. Physical reservation is not host consent or Programme release.

The separate [hosting contract](programme-hosts.md) documents four host commands,
independently ceilinged personal/organizer reads, versioned shared-availability
dependencies and current-person readiness checks. Host commands use the same
item version, receipt namespace and event stream; they do not rewrite private
working, delivery or approved public-copy layers.

`programme.item.changed.v1` validates an exact payload of action, layer, item
kind, provenance, lifecycle, and concern codes. Item-changing commands use the
item UUID and version as the event aggregate. Public-copy approval uses the item
UUID with the rendition number in a separate public-rendition stream so repeated
approvals from one unchanged private source retain collision-free ordering. Every envelope carries
the exact organization, edition, actor, correlation, and time. The event is
registered so the future writer contract is stable, but no current manifest
pins an `(event, destination)` route and no built-in handler is installed.

`programme.accepted-application-source@1` identifies the implemented dormant
[accepted conversion](programme-conversion.md) boundary. A successful result
binds one exact immutable Applications transition without copying answers or
review content. No current profile pins it. The
Applications-owned `programme_item` target kind, call activation, proposal
seal, collaborator acknowledgement, proposal submission, or withdrawal cannot
create a `ProgrammeItemSourceBinding` and is not accepted-item evidence.

## Exact release-source decisions

[ADR 0095](../architecture/decisions/0095-trusted-programme-release-sources.md)
adds the dormant `programme.placement-decisions@1` and
`programme.release-source@1` adapters. `placement_queries` supplies an exact
authorized preview and separately ceilinged fixed-history pages;
`placement_commands.record_programme_placement_decision` records accountable
`accessibility_fit` or `staffing_not_required` decisions against that preview.
Typed selection and decision intent retain item, occurrence, candidate/revision,
placement and exact optimistic versions. The source digest is recomputed before
write; it is not caller-supplied proof of success or permission.

Fit requires explicit delivery revision and independently authorized complete
Venue access/configuration facts. No algorithm infers suitability from prose.
No-staffing requires complete absence of active requirements and operative work
across all retained Workforce binding history. The owner explicitly records
satisfied, blocked or withdrawn with reason. Exact immutable placement and
matching owner sources permit reuse in an identical copied candidate, but the
original candidate remains retained provenance, not reusable disclosure authority.

Each placement/kind has its own contiguous stream: 1,000 ordinary decisions and
one final withdrawal slot. Receipt, audit, event and outbox are atomic, with
separate `programme.accessibility_fit` / `programme.staffing_absence` event
aggregates keyed by placement and sequence. The item version does not advance.
These operational decisions are allowed in Draft/Preparing/Ready/Live without
reopening private content editing. Withdrawal may reference independently
authorized historical candidate evidence after draft movement; its candidate
version is that retained manifest's original sequence, while the item precondition
is current. Retry requires current authority and returns the retained result.

Previews require `placement_decisions` plus `delivery_information` or
`staffing_requirements`; fixed-ceiling history instead requires `delivery_history`
or `staffing_history`. Rationale and actor do not enter release preflight results.
`release_queries` exposes complete seven-concern readiness and minimized current
copy consequences under independently admitted readiness/copy/person-reference
fields. Missing concern membership is unavailable. Public copy must reference the
current working revision and have an active verified reviewer distinct from every
retained working-copy author. Old self-curated copy stays historical; deactivating
an author does not erase authorship. No private text becomes a public fallback.

`collect_programme_release_person_references` supplies opaque ephemeral references
for the complete lock closure, not a personnel directory or caller-selectable
success flag. It includes current selected-item hosts and latest copy reviewers;
the compositor must combine Workforce people before taking any person locks.
The [source recovery guide](../operations/programme-release-sources-migration-and-recovery.md)
documents schema, read-only runtime containment and populated downgrade fences.

## Database integrity and recovery

Programme migrations are additive and seed no control, item, requirement,
profile, capability grant, or cross-module row. PostgreSQL guards enforce exact
scope, closed shapes, contiguous versions, append-only evidence, immutable
source and public-rendition chains, and receipt-backed aggregate changes. Guard
functions use `SECURITY INVOKER`, a fixed safe search path, and revoked public
execute privilege. The bounded health probe fingerprints exact relations,
columns and collations, complete constraint/index definitions, relation
metadata, function bodies/configuration, trigger attachments, ownership, and
ACLs; this reports schema integrity, not profile activation.

Because no production caller exists, the runtime role receives `SELECT` only
on every `programme_*` relation and no Programme function execution. A later
activation must deliberately review and widen only the relations its canonical
writer needs. Direct insert, update, delete, truncate, reference, trigger, or
maintenance authority is not implied by installation.

An empty Programme schema can reverse exactly. Once any durable Programme row
exists, `0003` provides the early downgrade fence and the reverse paths of
`0002` and `0001` repeat same-transaction `ACCESS EXCLUSIVE` preflights
immediately before guard and table removal. A refusal preserves the schema,
guards, and migration evidence. Recover by fixing forward or restoring
Programme, Audit, Effects event/outbox, and migration history from one mutually
consistent backup point. The later accepted-source graph also includes
Applications and Authorization; its unused reversal and populated fences follow
the [conversion recovery runbook](../operations/programme-conversion-migration-and-recovery.md).
The host graph adds its own unused reversal and early retained-history fence;
follow [host recovery](../operations/programme-host-migration-and-recovery.md)
before attempting any contraction of those tables, guards or capabilities.
Recovery must not fabricate an Application, review,
host, readiness fact, rendition, occurrence, Shift, release, or other module
record.

## Current limitations

This module is a deployable, testable private-domain foundation, not a usable
Programme workspace. Applications-owned calls and collaborative proposals now
have separate dormant call/proposal, preview-first import, and owner-Department
continuity kernels, but they create no Programme record or host relationship.
That continuity prerequisite is implemented without activating its recovery
capability, profile, route, or UI.
Dedicated staged review, decisions and explicit accepted conversion are also
implemented but dormant. Conversion creates private planning state only;
Programme-owned host/co-host invitation, confirmation and deliberately shared
per-item availability now have a separate dormant owner boundary.
Scheduling candidates, conflicts, explicit Venue reservations, interactive
editing, staffing and complete release preflight now have dormant owner kernels.
Persisted independent approval, atomic release,
public and personal timetables, on-site continuity, profile activation, and
integrated browser rehearsal remain later children of the Programme Operations
umbrella.
