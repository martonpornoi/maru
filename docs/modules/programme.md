# Programme module

Status: dormant private-domain foundation; no current adoption profile, route,
API, navigation, worker, or production writer

Last updated: 2026-09-05

## Purpose and ownership

`maru.programme` owns the canonical private Programme item for one exact event
edition. It separates working information, delivery facts, Department
discussion, readiness evidence, and approved public copy so a future Programme
workspace can expose only the layer required for one task. It implements the
private item/readiness foundation of PRG-005, PRG-006, PRG-008, PLN-004,
EVT-006, EVT-007, AUD-001, AUD-003, AUD-005, PRI-001, NFR-002, NFR-003,
PRG-011, NFR-008 through NFR-010, and NFR-013 without claiming that Programme
Operations is active or usable. The boundary follows ADRs 0001, 0003, 0005,
0041, 0051, 0081, 0084, and 0085.

Programme does not own calls or proposal review, accepted Applications truth,
service days, occurrences, rooms, timetable release, volunteer Shifts,
personal schedules, attendance, Registration, or public pages. Applications
now owns a dormant Programme-call and collaborative-proposal kernel, including
shared answer history, contributor-owned profile revisions, exact sealed
proposal revisions, and included-collaborator acknowledgements. Its dedicated
[staged review and decisions kernel](programme-review.md) now also owns immutable
review policies, exact-seal evidence, independent decisions, and recipient-only
messages and acknowledgements. It remains dormant. Applications will own the
later accepted-transition receipt; review-side acceptance alone is not that
transition. Programme owns no proposal collaborator and creates no host or co-host
relationship until a later accepted transition imports one exact reviewed
revision. Scheduling will later own occurrences and placements. Workforce will
later own staffing demand and Shift commitments.

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
nine edition-scoped capabilities, one reserved accepted-application source
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
| `ProgrammeItemSourceBinding` | One structural source receipt; organizer items have no foreign source and the reserved Applications form uses a typed UUID and version. |
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
published, staffed, or live. The reserved `applications_accepted` provenance
cannot be used without exactly one typed source binding, and organizer-created
items cannot fabricate one.

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

The dormant capability catalog is:

- `programme.view_private` and `programme.manage_items`;
- `programme.view_readiness` and `programme.manage_readiness`;
- `programme.view_delivery` and `programme.manage_delivery`;
- `programme.view_discussion`;
- `programme.view_public_copy`; and
- `programme.approve_public_copy`.

They are persistable only at exact edition scope. The PostgreSQL minimum-scope
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

## Event and adapter seams

`programme.item.changed.v1` validates an exact payload of action, layer, item
kind, provenance, lifecycle, and concern codes. Item-changing commands use the
item UUID and version as the event aggregate. Public-copy approval uses the item
UUID with the rendition number in a separate public-rendition stream so repeated
approvals from one unchanged private source retain collision-free ordering. Every envelope carries
the exact organization, edition, actor, correlation, and time. The event is
registered so the future writer contract is stable, but no current manifest
pins an `(event, destination)` route and no built-in handler is installed.

`programme.accepted-application-source@1` declares the future inbound adapter
contract. A successful result will bind one exact immutable accepted
Applications transition without copying answers or review content. The
descriptor is not an implementation and no current profile pins it. The
Applications-owned `programme_item` target kind, call activation, proposal
seal, collaborator acknowledgement, proposal submission, or withdrawal cannot
create a `ProgrammeItemSourceBinding` and is not accepted-item evidence.

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
consistent backup point. Recovery must not fabricate an Application, review,
host, readiness fact, rendition, occurrence, Shift, release, or other module
record.

## Current limitations

This module is a deployable, testable private-domain foundation, not a usable
Programme workspace. Applications-owned calls and collaborative proposals now
have separate dormant call/proposal, preview-first import, and owner-Department
continuity kernels, but they create no Programme record or host relationship.
That continuity prerequisite is implemented without activating its recovery
capability, profile, route, or UI.
Staged review and decisions and the accepted Applications adapter follow; only
that later accepted Programme transition may create host and co-host
relationships.
Interactive timetable editing, Scheduling, Venue placement, staffing, release,
public and personal timetables, on-site continuity, profile activation, and
integrated browser rehearsal remain later children of the Programme Operations
umbrella.
