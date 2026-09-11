# ADR 0096: Publish exact Programme releases with governing invalidation

- Status: Accepted; dormant contract, protected delivery remains separately gated
- Date: 2026-09-11
- Extends: ADRs 0081, 0087, 0088, 0093, 0094 and 0095
- Requirements: SCH-004, SCH-007, SCH-010, SCH-012, PRG-008, HR-014,
  HR-015, AUD-001 and NFR-001/002/005/008/009/013
- Issue: [#96](https://github.com/martonpornoi/maru/issues/96), child of #48

## Context

At the #94 baseline, complete trusted preflight did not retain an
independent timetable approval or publish a Programme release. Private draft
conflict evidence and warning acknowledgements cannot authorize publication.
That baseline collection reread Venue facts without establishing the
transactional closure needed to publish against concurrent owner changes.

Once publication exists, cancelling a room, withdrawing host sharing or losing
future staffing cannot leave an old artifact advertising a valid placement.
Rewriting old releases would destroy accountable history. Taking foreign
edition pointers after narrower owner locks would introduce inversion and make
privacy withdrawal depend on unrelated operational locks.

## Decision

### Independently approve exact current evidence

Scheduling owns immutable release-warning acknowledgements and approvals,
separate from planning acknowledgements. An acknowledgement records one exact
current warning fingerprint, complete source fingerprint, reason and actor.
Approval independently recollects all mandatory owner sources and authenticates
the retained warning evidence. No caller boolean, arbitrary artifact provider,
hard-constraint waiver or missing source may substitute for a check.

The approver must differ from the candidate's retained authors and selected
placement authors, including exact copy/restore provenance. Former authors need
not remain active; their authorship remains an exclusion. Publication requires
its own current capability and an actor distinct from the approver. The
publisher may also be a planner when independently authorized. Exact retries
reauthorize and return the retained receipt without changing history.

### Persist review and release state separately

The additive schema separates release-only warning acknowledgements from
planning warnings. An approval retains exact candidate/source fingerprints,
explicit warning IDs, complete placement/public-rendition selections and typed
captured dependency uses. Its source generation and immutable operational end
define each governing consequence. Publication references that immutable
approval and retains the previous release plus bounded added/changed/removed
counts; verified canonical bytes are a separate retained artifact. Reasoned
withdrawal has its own receipt. One edition pointer advances monotonically for
both publication and withdrawal; a null pointer after withdrawal is not the
initial never-published state. Schema alone proves none of command independence,
complete source capture or atomic publication: native and application guards
must establish those contracts together.

### Prepare and publish one canonical release

Publication repeats current source, authority, independence and expected-prior-
release checks under the complete canonical owner/person/physical closure.
Scheduling owns a closed mandatory canonical artifact contract containing
minimized exact occurrence, placement, source-rendition and dependency identity,
not private planning or calendar data. Artifact generation, complete shape and
checksum validation finish before pointer mutation. Later role-specific formats
must derive from this release and preserve its serving boundary; an empty
artifact registry cannot make publication eligible.

The release, exact approval and warnings, artifact manifest, dependencies,
superseded release, bounded change summary, receipt, audit, domain event and
outbox commit with one active-pointer update. Failure changes none of the prior
release. There is no network operation in this transaction. Deliberate whole-
release withdrawal is a separate reasoned command, not an empty candidate.
Publication never silently edits, cancels or reconfirms accepted volunteer work.

### Preserve history while invalidation governs current use

Use a Scheduling-owned immutable dependency-change journal. Each release
retains exact typed owner dependency identities and captured generations.
Source-owner changes append governing invalidation evidence in their transaction;
normal projections resolve the consequence for each exact release dependency.
This avoids enumerating or locking unrelated release pointers during a privacy
exit. It must provide ADR 0081's same-transaction exact-release safety consequence,
not merely compare an old digest on a best-effort background refresh.

The source owner retains authority and mutation evidence. Scheduling records only
closed minimized cause/reference evidence; it gains no authority to change that
owner. Application receipt/audit/event attribution and raw-DML enforcement are
mandatory. A generic caller-provided source key or rationale is
not proof of an owner mutation. Missing, partial, stale or unsupported dependency
evidence blocks normal serving; stored bytes never grant ongoing permission.

The current attribution implementation lends exact native Audit evidence inside
an already active owner transaction. A frozen lexical lease rejects copied,
expired, cross-thread and rolled-back references. An opt-in Audit INSERT trigger
also retains a database-owned witness for that exact new audit, using the full
top-level transaction identifier plus backend/server-start context. This avoids
the demonstrated savepoint failure of comparing row `xmin` with a top-level XID,
and changes no historical Audit row schema or sealed semantic digest. See the
[Audit attribution contract](../activity-audit-and-history.md#same-transaction-native-mutation-attribution).

Native owner joins now use a narrow Scheduling SECURITY DEFINER journal function
without generic runtime table DML. It creates no tracking or release state,
validates current native source proof, locks source before key, and revalidates
before the consecutive journal append. Exact same-transaction duplicate
notification is harmless; a later transaction cannot reuse its Audit UUID.
The explicit v4 runtime closure includes the native read helpers and the
existing read-only linked-booking validator reached by ordinary Venue writes.
It grants no Programme or Scheduling feature activation. Genuine-login focused
tests exercise Identity, Events, Workforce, Venue property and cancellation with
SELECT-only journal and Audit-witness relations.

Native guard readiness now composes explicitly pinned full migration sources,
their actual SQL operations and required recorders, rather than treating a
recorder alone as proof. It retains literal trigger arguments and supporting
owner attachments, set-returning function shapes, exact bodies, owners and
search paths. The original owner-only builder remains unchanged. The additive
composition explicitly names the two SECURITY DEFINER exceptions and the narrow
runtime helper set; it does not infer permission from a function-name prefix.
The separate execution-boundary migration revokes default PUBLIC execution and
grants no runtime permissions or profile activation. After provisioning, the
catalog accepts only owner plus the exact configured runtime login for those
declared helpers, with no delegated grant option or additional grantee. An
unconfigured runtime keeps the owner-only boundary. The complete role-safety
probe remains separately mandatory; helper ACL checks do not substitute for
its table, membership, ownership and session checks.

The database witness still proves only native insertion in this transaction,
not the actor's authority or a source mutation by itself. Each owner must prove
the exact closed operation, source scope and native receipt/effects; source and
journal guards and runtime SELECT-only witness containment remain necessary.
Recovery must finish in a separate committed maintenance transaction before
ordinary commands resume. Native attribution, role containment, readiness and
complete source joins require their own evidence; an isolated stamp experiment
or passing Audit tests cannot establish the entire release contract.

The current native integration uses source-before-key locks, immutable typed
key identities and consecutive journal generations. Every generation advance
requires its exact immutable change before commit. SQL supplies the actual
recording time; caller backdating cannot turn future invalidation into historical
completion. Identity's tracked eligibility changes require the current native
emergency-deactivation audit and revoked sessions. Programme resolves source
identities through its closed native receipt/result mapping, including the exact
host revision; a host UUID or an item-targeted audit alone is insufficient.

Relevant native mutations and first tracking require `READ COMMITTED`, checked
before relying on key visibility. Otherwise a repeatable-read transaction can
miss the first tracking key committed while it waits on the source lock. Eight
committed Identity tests observed actual PostgreSQL lock waits in both orders,
including rollback and a raw writer discovering the new key. A source-first
test verifies the subsequent tracker sees the newly inactive account; tracking
identity is deliberately not approval eligibility, so the eventual publisher
must still reject that fresh inactive source. Additional actual publication
races cover copy withdrawal, shared physical-property changes, booking cancellation
and reciprocal host/Workforce obligations, independently of first-key tests.

Differentiate approval-only dependencies from ongoing operational safety and
disclosure. A later reviewer departure does not rewrite a historically valid
approval, but a new publication requires its current eligibility. Completed
past work stays truthful history and cannot count as future coverage. Deliberate
copy or relationship withdrawal governs retained artifacts, including historical
bytes, independently of private draft edits. The following temporal dependency
rules govern the complete indexed native journal.

Any dependency generation change stales an unpublished
approval. Normal serving ignores changes to approval-only attribution; operational
changes govern a retained obligation only when recorded before its immutable
half-open end. An invalidation before that end remains an invalidation afterward.
Disclosure changes govern historical and future output without an operational
expiry. Missing or non-contiguous journal evidence is unavailable. The owner
reader may aggregate a complete indexed journal rather than copy its history,
but must prove its exact generation range and count before interpreting it.

Invalidating a room does not silently free a host's still-retained time commitment.
Operative published host presence remains protected until its governed source
relationship ends or a deliberate release replacement/withdrawal changes that
commitment. These consequences must be tested separately from normal visibility.

Every normal public, personal, room, export, print and future cached consumer
must use the checked release boundary. Safety invalidation removes the unsafe
claim or renders it withdrawn/relocation-pending; it cannot continue to advertise
the old approved room. Disconnected downloaded copies cannot be remotely erased;
bounded freshness and correction procedures remain mandatory in the continuity
successor. No last-published fallback bypasses known invalidation.

### Complete canonical locking and reciprocal person protection

The minimized cross-edition work/rest source also needs a monotonic person
obligation generation. Comparing only the currently active work rows would
miss an intervening claim and withdrawal that restores the same visible set.
A closed global `workforce_person_obligations` key therefore references only
the already-authorized account, never a foreign demand, edition, organization,
calendar or label. Workforce's exact native commitment receipt remains the
attribution authority; its ordinary scoped Audit event is not relabelled as a
global action. The validator permits this one typed scope transformation only
after proving that receipt's exact account and Audit scope. Capture is
approval-only; independent ongoing staffing and disclosure dependencies retain
their own consequences. The generation is not a substitute for reciprocal
published-host conflict prevention.

The reciprocal seam resolves only overlap/rest booleans and an opaque
retained publication/pointer/host-version fingerprint for an already authorized
person interval. It returns no foreign organization, edition, calendar or reason.
Private draft placements are not operative. A confirmed host's current published
presence remains a commitment despite room or copy invalidation; ending the host
relationship or deliberately replacing/withdrawing its release ends that claim.
Only the owning candidate composer excludes its own edition during replacement;
Workforce claims exclude none. Retained publication and monotonic pointer history
also change the source fingerprint after an intervening publish/withdraw cycle,
even when the currently visible obligation set returns to its previous state.
The existing Workforce generation remains specifically Workforce-owned.

Both native commitment writes and release pointer changes enforce reciprocal
work/rest checks under account serialization. Replacement collects the complete
new and prior person union before narrower source locks; raw inverted writers
fail a non-waiting account guard. The minimized source checks acquire no foreign
edition locks. Real native-command races cover both publication/claim orders,
two foreign Programme publications for the same host, and rollback. These
focused results are not complete certification or production guarantees.

Native Shift commands must collect and canonically lock their complete affected
person set after owning parents but before demands, commitments or availability,
then reauthorize at a fresh time. Former/inactive commitment principals can be
locked for cleanup without making them eligible for new work. A raw commitment
writer must establish the same account serialization; a non-waiting lock guard
fails closed on an inverted raw write instead of waiting while holding a narrower
row. Real two-connection acceptance must prove first-capture and native mutation
ordering, not merely sequential generation arithmetic.

Publication resolves all selected workers, hosts, current copy reviewers,
approver and publisher before taking narrower person locks. It uses documented
owner seams for complete physical property/member/configuration locking, in an
order compatible with real catalog and booking writers. It does not acquire a
new foreign edition or person late, introduce a blanket global mutex, or deny
voluntary withdrawal merely to avoid a proper dependency boundary.

Prove both race orders for publication versus owner mutation, including a release
invisible before a waiter acquires its lock and the first creation of dependency
tracking. Require the supported transaction isolation and fresh post-wait source
checks. PostgreSQL's [function snapshot rules](https://www.postgresql.org/docs/17/xfunc-volatility.html)
and [transaction isolation](https://www.postgresql.org/docs/17/transaction-iso.html)
inform this design; documentation is not a substitute for real concurrency tests.

Published host presence becomes an operative person obligation. Both Programme
publication and Workforce claim/confirmation must consult a purpose-bounded
owner seam for combined overlap/rest protection under the person lock. Private
alternative drafts remain non-operative. Foreign calendars and tenant identity
must not enter another department's result, and existing Workforce-only profile
meaning must not be widened by an unrelated disclosure or activation requirement.

### Keep the boundary dormant until all successors pass

Programme supplies separately governed Ready/Live public-copy revalidation and
withdrawal without reopening private working-information editing. Preserve old
self-curated renditions as history; new release evidence must still meet ADR
0095's independent-copy requirements. Source and ongoing-safety semantics must
be explicit rather than silently relaxing preflight to publish past work.

Additive owner migrations, exact readiness fingerprints, runtime SELECT-only
containment and populated fix-forward fences remain mandatory. No current
profile, route, writer or release worker activates here. Shared role-specific
outputs/change delivery, continuity, guided setup and integrated acceptance are
successors. Genuine human checks remain #92, deferred rather than waived.

## Acceptance and evidence boundaries

An isolated PostgreSQL 17.11 experiment passed six SQL hypotheses: both
publication/withdrawal lock-wait orders, rollback of each side, atomic rollback
on invalidation failure, and one journal entry governing 100 exact retained
dependencies. The first-publication case explicitly observed a real lock wait
before the waiting source trigger discovered the newly committed tracking key.
This supports the journal mechanism only. It does not prove Maru's owner
commands, attribution, authorization, runtime roles, migration or serving safety.

Inventory all relevant owner writers and their SQL protection; settle dependency
journal attribution and exact temporal/disclosure semantics. Prove first-key,
publication/withdrawal, cross-edition physical and reciprocal person races in
both orders, with no inverted foreign locks. Cover permission/field/tenant
denial, independent authorship, stale replay, artifact/audit failure rollback,
runtime/direct-DML containment, exact recovery and prior-history retention.

The implementation now has focused native owner, independent review/publication,
checked-read, past-history, real concurrency and genuine-runtime containment
evidence. Scheduling 0020 refuses contraction at the top of the release extension
when retained native evidence exists. Ordinary unused reverse/reapply and used
refusal preserving all migration records passed. A same-image physical backup
clone passed exact readiness, retained release/artifact, new native invalidation
and exact retry while the original synthetic source remained unchanged.

Logical dump/restore instead exposed an existing catalog-rendering mismatch for
array-cast CHECK expressions. Exact schema readiness correctly refuses it;
native functions, triggers, ACLs and recorders passed the diagnostic. #97 owns
logical compatibility and weakened-constraint negative tests before activation.
Physical recovery does not waive that gate or prove production backup/PITR.
See the [recovery contract](../../operations/programme-atomic-release-migration-and-recovery.md)
and CURRENT for certification/delivery status. No current profile is activated.

## Alternatives considered

- Mutating immutable released content: rejected because it erases history.
- Async invalidation while serving known-invalid bytes: rejected by SCH-012.
- Locking every affected foreign pointer from a source writer: risks inverted
  owner order and unbounded privacy-exit coupling.
- Per-release append-only invalidations: viable only if complete affected-set
  and first-publication races can be proven without that coupling.
- Dependency-generation journal: implemented dormant mechanism; complete native
  owner attribution and checked serving consumers remain mandatory. It does not
  make disconnected downloads revocable or activate unfinished consumers.
