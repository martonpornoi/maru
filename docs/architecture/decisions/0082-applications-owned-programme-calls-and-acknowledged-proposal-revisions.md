# ADR 0082: Keep Programme calls and acknowledged proposals in Applications

- Status: Accepted
- Date: 2026-09-01
- Extends: ADRs 0001, 0003, 0005, 0041, 0051, and 0081
- Requirements: IDN-014, PRG-001, PRG-002, PRG-006, PRG-008, PRG-009,
  AUD-001, AUD-003, AUD-005, PRI-001, NFR-002, NFR-003, NFR-008 through
  NFR-010, and NFR-013
- Issue: [#63](https://github.com/martonpornoi/maru/issues/63), child of
  [#48](https://github.com/martonpornoi/maru/issues/48)

## Context

ADR 0081 assigns calls, proposals, revisions, review, decisions, and accepted-
target evidence to Applications. The existing Applications module already owns
versioned definitions, typed questions, append-only answer revisions, and
submissions. Building a second Programme-specific form engine would duplicate
those controls and create two competing sources for eligibility, field policy,
answers, and concurrency.

A collaborative Programme proposal nevertheless needs stricter authorship than
the existing single-applicant flow. A lead selects the call, track, format, and
contributor roster. Collaborators may jointly edit answers, but cannot speak for
one another about a proposed-public biography or consent. Submission must name
one exact, reviewable snapshot rather than whatever rows happen to be current
when a reviewer later reads it.

The current Applications review and target seams predate this contract. Merely
adding a `programme_item` discriminator to a catalog would let a generic accept
command create incomplete target evidence before the Programme import and
accepted-transition contract exists. Likewise, registering capabilities or
events globally must not widen either current adoption manifest or give the
production runtime role a writer path into this dormant schema.

## Decision

### Extend the existing definition and submission aggregates

`ProgrammeCall` is a one-to-one Applications-owned facet of one
`ApplicationDefinition` whose target kind is `programme_item`. Its typed
tracks, formats, contributor fields, eligibility, deadlines, and content
policies remain children of that definition. The call has a closed domain
lifecycle:

```text
draft -> active -> retired
          |
          +-> copy-on-write successor draft
```

Activation means only that the call's Applications domain contract is active.
It does not select `programme_operations@1`, mount a route, publish the call, or
make it discoverable through the current Applications catalog. Active and
retired call content is immutable; change uses an explicit successor.
Call management requires exact current Department authority within the edition;
an ancestor Department, broad edition visibility, or account existence does
not inherit that capability.

Current Department ownership is required for call management and for discovery
or creation of a new proposal. It is not retroactively required for an
existing proposal's relationship-derived self access: a lead, live invitee, or
accepted collaborator keeps the lifecycle-permitted view or self action after
the owner Department is retired. Operators must therefore reassign a draft
call or retire an active call before retiring its owner Department. Retiring
the Department first intentionally blocks new starts but leaves the call
without an organizer management path;
[#64](https://github.com/martonpornoi/maru/issues/64) must add a Workforce
preflight and governed recovery rather than weakening either boundary.

`ProgrammeProposal` is a one-to-one facet of one `ApplicationSubmission`.
Existing `ApplicationAnswerRevision` rows remain the only answer history. The
submission's `aggregate_version` is the sole optimistic concurrency cursor for
answers, selection, roster, profile, invitation, sealing, acknowledgement,
reopening, submission, and withdrawal. There is no second independently
advancing proposal version that could permit a lost update or a split receipt.

### Keep collaboration purpose-scoped and attributable

Each proposal has one accountable lead. A collaborator transition is
append-only and retains actor, time, reason, prior state, resulting state, and
the aggregate version. Persisted states are `invited`, `accepted`, `declined`,
`left`, and `removed`. Expiry is derived from an unaccepted invitation and its
deadline; it is not an actorless state mutation. An expired invitation cannot
be accepted and does not block sealing or submission. Reinvitation retains the
old transition and appends a reasoned invitation with a new expiry. A new or
renewed invitation may expire at, but never after, the inclusive applicant edit
deadline so an unresolvable invitation cannot strand the draft after cutoff.

Only an active, verified person may be lead or collaborator. Eligibility is
independent of Participation, Registration, payment, attendance, Workforce,
membership, or another edition relationship. Accepted collaborators may edit
the shared applicant-writable answer set. The lead alone changes track, format,
and included-contributor roster. Each contributor alone creates revisions of
their proposed-public display name, biography, pronouns, website, and consent.
No lead, collaborator, organizer, or retry may impersonate that contributor.

Proposal collaboration is not a Programme host or co-host relationship. A host
relationship may be created only by a later accepted Programme transition,
after review and the typed import adapter are implemented.

### Seal and acknowledge one exact immutable revision

The lead may seal a draft only after required answers and included contributor
profiles are valid and no unexpired invitation remains unresolved. The sealed
`ProgrammeProposalRevision` records the exact definition and call schema
version, selection revision, answer revision for every applicable question or
its explicit absence, included contributor roster, each exact contributor-
profile revision, policy versions, predecessor where applicable, and a
canonical digest. Snapshot links are immutable and append-only.

Sealing blocks answer, selection, roster, profile, and invitation mutation.
Each included collaborator may acknowledge or decline only for themselves and
only against that exact sealed revision and the exact profile revision included
for them. Responses advance the same submission aggregate version but do not
rewrite the sealed snapshot. The lead cannot respond for another contributor.

The lead may submit only the current seal, after every included collaborator
has acknowledged and none has declined. Submission records the exact proposal
revision; it performs no review, decision, target transition, Programme import,
or publication. Reopening is explicit, retains the prior seal and responses,
invalidates it as the submission candidate, and requires a new seal before a
later submission. The lead may withdraw a draft, sealed, or submitted proposal;
history remains immutable.

### Deny every legacy review and target seam

The `programme_item` target kind and dormant target descriptor are reserved for
the future accepted adapter. Until that child lands, every legacy review,
decision, acceptance, target-record, target-query, starter-discovery, and target-
adapter seam must explicitly deny or omit Programme definitions and proposals.
PostgreSQL must reject an `ApplicationTargetRecord` with the Programme target
kind. This child adds no proposal-revision foreign key to that record and no
generic path may infer acceptance from proposal state.

The immediate successor is preview-first import of incumbent call and proposal
data through the same public commands. Structured review, decisions, and an
idempotent accepted Programme adapter follow. Programme item creation, host and
co-host relationships, readiness, public copy, scheduling, staffing, and
publication remain in their owning later children.

### Couple evidence atomically without widening the generic writer

Every successful Programme-call or proposal command commits its aggregate
change, a dedicated immutable Applications Programme command receipt, exact
version proof, minimized allow audit, registered dormant domain event, and
transactional outbox row in one transaction. Failure leaves none of those
success artifacts. Denial and validation-error audit remains value-minimized
and cannot disclose another tenant, proposal, answer, contributor profile, or
invitation.

The dedicated receipt relation is not an extension of the existing runtime-
insertable generic Applications receipt. This preserves a closed raw-DML proof
boundary while the new schema is dormant. Deferred database checks require the
exact aggregate transition and matching receipt in the same transaction and
reject replay-key reuse with a different normalized intent.

### Keep the kernel dormant at every adoption boundary

The capability, target, purpose, and event catalogs may declare the future
contract, but neither `full_convention@1` nor `workforce_only@1` pins any new
member. Their literal profile fingerprints therefore remain unchanged. There
is no `programme_operations@1` selection, root role, current-profile grant,
route, serializer, schema operation, template, navigation destination, Django
admin writer, worker, handler, delivery route, or background schedule in this
child.

The new Applications Programme relations are `SELECT`-only for the production
runtime role and their integrity functions remain owner-only. Migration
readiness fingerprints the exact relation, constraint, index, function,
trigger, owner, and ACL contract. Empty reversal is exact; durable Programme-
call or proposal evidence trips a populated downgrade fence before protected
objects can be removed. Recovery fixes forward or restores Applications,
Audit, Effects event/outbox, and migration evidence from one consistent point.

## Consequences

- Programme contributors can collaborate on a reviewable proposal without
  creating attendee, volunteer, payment, or host state.
- One aggregate version serializes every mutation, while exact sealed snapshots
  and collaborator-only responses preserve what each included collaborator
  actually accepted; the lead's attributable seal is the lead action.
- Reusing Applications answers avoids a parallel form engine, but commands and
  queries must maintain stricter purpose and field-level authorization.
- Reserving a target kind without enabling generic acceptance requires explicit
  negative tests at every legacy seam.
- The schema is deployable and recoverable but unusable by current profiles;
  this milestone is not a browser, API, publication, or adoption outcome.

## Alternatives considered

### Build a Programme-owned form and proposal engine

Rejected because it would duplicate Applications definitions, answer history,
field policy, and submission concurrency while creating ambiguous ownership.

### Treat all collaborators as co-hosts

Rejected because proposal collaboration is temporary Applications purpose.
Host and co-host authority belongs to an accepted Programme item and must not
exist before review and transition.

### Let the lead respond for every collaborator

Rejected because proposed-public identity and consent belong to each included
person. A shared lead response would erase individual authorship.

### Snapshot only the current answer values

Rejected because a later revision, conditional-field change, roster change, or
profile edit could make the reviewed content irreproducible. Exact revision and
explicit-absence links are required.

### Give proposal children independent versions

Rejected because concurrent mutations could each appear current and produce
incompatible seals. The submission aggregate version is the single cursor.

### Reuse the generic receipt or target-record path immediately

Rejected because the current runtime privileges and acceptance semantics are
broader than this dormant boundary. Dedicated evidence and explicit legacy-seam
denial preserve least privilege until later children deliberately connect it.

## Requirements affected

- **PRG-001 and PRG-002:** Calls and collaborative proposals have explicit
  Applications ownership, lifecycle, purpose, and concurrency semantics.
- **PRG-006 and PRG-009:** Exact private proposal and proposed-public profile
  revisions remain separate from any later approved Programme rendition.
- **PRG-008:** No Programme item or host relationship exists before a later
  accepted adapter consumes one exact reviewed proposal revision.
- **IDN-014:** Proposal lead, collaborator, reviewer, and later host purposes
  remain separate and create no unrelated edition relationship or workspace.
- **AUD-001, AUD-003, and AUD-005:** Mutations retain atomic, attributable,
  immutable, value-minimized evidence and reject split raw writes.
- **NFR-013:** Installing the dormant kernel creates no unrelated record,
  authority, destination, side effect, or current-profile expansion.
