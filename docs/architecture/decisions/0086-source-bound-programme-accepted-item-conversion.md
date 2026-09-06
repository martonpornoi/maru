# ADR 0086: Convert exact accepted proposals through reciprocal owner receipts

- Status: Accepted
- Date: 2026-09-06
- Extends: ADRs 0051, 0081, 0084, and 0085
- Partially supersedes: ADR 0082 only for its deferral of a dedicated accepted
  Programme adapter. Generic review and target-record fences remain closed.
- Requirements: REG-023, PRG-003 through PRG-006, PRG-008, PRG-009, PRG-011,
  IDN-014, AUD-001, AUD-003, AUD-005, and NFR-001 through NFR-003,
  NFR-008 through NFR-010, and NFR-013
- Issue: [#77](https://github.com/martonpornoi/maru/issues/77), child of
  [#48](https://github.com/martonpornoi/maru/issues/48)

## Context

Applications retains accountable acceptance of exact acknowledged proposals.
Programme retains separate private items and readiness. A historical accept
decision may become ineffective after withdrawal, a newer seal, late recusal,
or Department retirement. A generic target record proves neither current
acceptance nor creation of an actual Programme item.

## Decision

### Applications owns conversion and the immutable source

One dedicated reasoned command names the exact decision and proposal seal,
current review-case and Programme edition-control versions, retry key, and
explicitly supplied bounded private working text. It never chooses a latest
decision implicitly or interprets an arbitrary answer as Programme content.

Fresh conversion requires an active verified person, exact tenant and edition,
current owner Department, open private planning,
`applications.convert_programme_acceptance` at that Department, and independent
`programme.manage_items` authority at the edition. Conversion authority is
nondelegable and grants no review-content read, final-decision, hosting,
readiness-attestation, or public-copy approval. A decision maker may also
convert only when separately authorized. Both the Applications target adapter
and Programme inbound adapter must be independently pinned.

After minimal retry proof and shared Applications retry serialization, fresh
work acquires the existing structure/provenance/retirement barriers,
Organization, ConventionSeries, EventEdition, edition mutex, current Department,
actor, Applications source, and Programme aggregate locks in that order.
It revalidates the exact submitted and acknowledged seal, decision coherence,
effective review evidence, ownership, adoption, lifecycle, and both versions.

One immutable `ProgrammeAcceptedTransition` per exact revision and accepted
decision binds the actual Programme item, source/result versions, actor,
reason, normalized intent digest, retry key, correlation, source channel,
audit, and event. It contains no answer sheet, review scores/rationale,
contributor profiles, or copied Programme prose. Conversion does not advance
the source submission or review-case cursor.

### Programme owns the target and initial unresolved readiness

The dedicated Programme command resolves its source through an Applications-
owned identifier-only public query. Supplying an unchecked UUID or constructing
a DTO cannot manufacture accepted provenance. Neither owner imports another
module's private model or writer.

The item starts at version one with kind `accepted_proposal`, provenance
`applications_accepted`, a reciprocal typed source binding, and one private
working revision. Creation advances the edition control once. Organizer-core
creation remains restricted to its original kinds and cannot fabricate this
source. The same creation initializes all seven closed readiness concerns as
required: public copy, host confirmation, technical needs, accessibility
delivery, media consent, schedule availability, and required files.

There is no satisfaction evidence, delivery fact, approved rendition, or inferred
consent. Public-copy dependency starts at the initial working revision; other
dependencies start at zero. Later separately authorized readiness commands may
explicitly mark a concern not applicable or append evidence normally.

### Commit reciprocal evidence together and retain truthful history

Applications orchestration writes its own transition and invokes the documented
Programme command. Deferrable foreign keys and exact reciprocal guards permit
transactional assembly but reject a committed half-conversion. Programme's
creation receipt validates the source, item, initial working revision, and
complete initial readiness. Both owners append minimized audits, registered
events, and outbox evidence. Any writer, audit, event, outbox, or deferred-guard
failure rolls back the complete success. Failure audits omit protected source
and result identifiers and all private values.

Exact actor-owned retry rechecks current identity and adoption and returns only
the original transition/item identifiers and versions, before reacquiring fresh
write scope. It grants no content or fresh source authority. Reusing the key
with different intent or another Applications workflow conflicts in both
directions. A different key targeting an already converted exact revision
conflicts rather than creating another item, including under concurrency.

Later withdrawal, a newer seal, acknowledgement, recusal, or owner retirement
preserves historical conversion. Programme is independent owned work, not a
mutable Applications mirror. No source change silently edits or deletes its
item. Conversion grants no host access, approved public copy, placement, or
release; those successors establish current evidence and change-impact rules.
A new accepted revision is not an implicit edit to a previously converted item.

### Preserve dormancy and recovery

Neither existing manifest, root, route, API, UI, worker, schedule, nor delivery
handler is expanded. Generic review and `ApplicationTargetRecord` paths still
reject Programme. New Applications relations and every Programme relation stay
SELECT-only for production runtime. Existing two-factor isolated-test guards
remain mandatory for substitute policy adapters; actual source, database,
audit, event, and outbox execution is never substituted.

Additive owner migrations preserve organizer-core items and fabricate no
accepted source. Readiness fingerprints new relations, constraints, reciprocal
references, functions, triggers, and ACLs. An unused conversion boundary
reverses exactly. Durable conversion fences downgrade before reciprocal
references, evidence, or kinds can be removed. Recovery fixes forward or
restores Applications, Programme, Identity, Organizations, Events, Workforce,
Authorization, Audit, Effects, and migration history from one consistent point.

## Consequences

- Exact acceptance becomes one traceable item with outstanding readiness work,
  without duplicating private review content.
- Purpose authority, retries, freshness, and reciprocal evidence are explicit.
- Circular source/target references require transaction-level checks and
  coordinated recovery, but prevent a receipt naming a nonexistent target.
- The dormant kernel is not a usable departmental workspace. Hosting,
  Scheduling, staffing, surfaces, and integrated adoption remain successors.

## Alternatives considered

Generic acceptance bypasses exact-seal review semantics. Private cross-module
queries break ownership. Copying answers or collaborators crosses field/purpose
boundaries. An unchecked UUID permits forged provenance. Combining conversion
with hosting or publication hides separate authority and consent. Deleting
converted items after source changes erases independent work and history.

## Requirements affected

PRG-005 and PRG-008 gain atomic conversion and initially unresolved readiness.
PRG-003, PRG-004, PRG-009, and PRG-011 retain source and ownership proof.
PRG-006 and IDN-014 retain private/public and purpose separation. Audit,
recovery, input, runtime, and modular-adoption requirements apply to both owners
without implying profile activation or production approval.
