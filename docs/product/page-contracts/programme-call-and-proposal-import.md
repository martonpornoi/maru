# Programme call and proposal import staging contract

- Status: Implemented dormant service/non-surface contract; protected-PR
  acceptance remains separate
- Route: none reserved by issue #66
- Requirements: IDN-014, PRG-001, PRG-002, PRG-006, PRG-009, PRG-010,
  PRG-011,
  AUD-001, AUD-003, AUD-005, PRI-001, UX-005 through UX-008, UX-019,
  UX-020, UX-027, UX-029, NFR-002, NFR-003, NFR-008 through NFR-010, and
  NFR-013
- Decisions: ADRs 0041, 0051, 0081 through 0084

## Purpose and current boundary

Let a Programme Department prepare one deterministic incumbent-system package,
review whether it is safe to apply, commit only complete Draft calls, and let
each proposal lead privately adopt only their own staged proposal. Temporary
private payload can then be removed explicitly without deleting the governed
call or proposal created from it.

Issue #66 contracts a dormant Applications service kernel. It does not mount a
page, upload control, API operation, OpenAPI component, serializer, template,
navigation destination, search result, dashboard card, Django admin writer,
worker, connector, queue, scheduled cleanup, notification, or delivery route.
No URL is reserved. A future organizer or lead interface requires a separately
accepted surface contract and an exact `programme_operations` profile member.

Neither current adoption profile pins
`applications.import.programme_call_proposal@1`, so every real current-profile
invocation fails closed before source or identity data is disclosed. The
dormant service implementation is present. This contract is not evidence of
migration/recovery rehearsal, browser acceptance, profile activation,
production retention approval, or permission to use production personal data.

## Roles and authority

- **Importer:** an active verified person with exact current-Department
  `applications.import_programme` authority in an exact coherent edition whose
  private-planning writes are open. The import adapter must be pinned
  independently; its pin alone admits staging and organizer preview, not a
  protected Programme target mutation.
- **Call manager:** the importer also holds an independently successful
  `applications.manage_programme_calls` decision for the same exact current
  Department. Import authority alone cannot create a call.
- **Proposal lead:** an active verified person whose authenticated account is
  re-resolved from the exact staged login email and who holds the existing
  exact-self Programme edit relationship. Importer or organizer authority
  cannot impersonate the lead.
- **Continuity disposer:** an active verified person with exact-Edition
  delegable `applications.dispose_programme_import` authority and the adapter
  pin. Delegation grants disposal, not staged-content read authority. A current
  Department and open planning writes are deliberately not required.
- **Batch reassigners:** the same active verified person must hold exact
  current-Department `applications.import_programme` authority at both the
  source and destination. This is a normal clean-staging operation, not orphan
  recovery, and grants no additional preview/content visibility.

Account existence, a staged email, import authority, call-management authority,
or disposal authority creates no attendee, member, applicant, collaborator,
host, volunteer, reviewer, or broader Programme relationship. Version one
admits no service or system actor.

## Closed workflow

The only service sequence is:

1. `stage_programme_import` receives raw UTF-8 JSON bytes plus trusted Maru
   scope, source system, actor, rationale, correlation, and retry metadata. A
   reviewed server-side provider supplies the retention-policy decision.
2. It parses, validates, canonicalizes, and stages one bounded package. It
   creates no call, proposal, invitation, identity match, or external effect.
3. `preview_programme_import` records one immutable batch-scoped organizer
   preview whose results bind every exact item version and digest.
4. `commit_programme_import_call` adopts the exact immutable organizer
   preview-result identifier together with its opaque item identifier and
   expected item version, rechecks both exact-Department decisions under locks,
   and calls `create_programme_call`. The resulting call is complete and Draft.
5. A proposal dependency remains safely blocked until its exact permanent call
   binding exists and the referenced call is independently active.
6. `preview_programme_import_proposal_claim` accepts the trusted request
   correlation ID and source channel, re-resolves the exact staged email,
   audits the sensitive read, and releases only that actor's proposal plus a
   fresh adoption digest. It remains available after planning writes close
   while the staging payload is unexpired and exact-self authority remains.
7. `claim_programme_import_proposal` repeats the self and dependency decisions,
   accepts the lead's own contributor profile, proposed-public choice, consent,
   and adopted digest, then calls `start_programme_proposal` followed by
   answer commands in strict
   `(section.position, question.position, question.id)` definition order in one
   transaction. Every linked answer question belongs to that call's exact
   definition.
8. `reassign_programme_import_batch` may move one unexpired, wholly staged,
   payload-intact, source-unbound batch while planning is open. It advances the
   batch version and invalidates older organizer previews without changing any
   item version, payload, source identity, or permanent binding.
9. `discard_programme_import` clears every remaining staged payload and records
   attributable disposal. It does not delete or compensate an applied call or
   proposal.

An importer may apply items independently. Applying one sibling never advances
or stales another item. A batch remains persisted as only `staged` or
`discarded`; partial application, full application, and expiry are derived
states. Its own positive version advances for reassignment and disposal, and
every organizer preview binds that current batch version.

The timezone-aware server clock is authoritative for expiry, freshness, and
retained command times. A caller cannot choose command time. The explicit
`now` seam is isolated to deterministic tests and requires both
`MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_CLOCK` and a connected database
whose name begins with `test_`; either condition alone fails closed.

## Source-package contract

The root document has exactly three members: `schema` equal to
`applications.programme_import`, integer `version` equal to `1`, and `items`
containing one through 1,000 closed call/proposal objects. It cannot supply
organization, edition, owner Department, source system, actor, rationale,
retry key, correlation ID, source channel, retention policy, or expiry. The
resource ceilings are exact:

| Resource | Maximum |
| --- | --- |
| Raw strict UTF-8 package | 8 MiB |
| Call/proposal items | 1,000; at least one is required |
| JSON nesting depth | 16 |
| Parsed values | 250,000 |
| Members in one object | 32 |
| Elements in one generic array | 1,000 before a narrower field bound |
| Unicode scalar values in one generic string | 65,536 before a narrower Programme bound |

The byte and lexical-depth ceilings are checked before decoding. The remaining
graph ceilings are checked immediately after the strict, non-streaming decoder
and before typed values or persistence; the transient graph remains bounded by
the 8 MiB byte ceiling. UTF-8 BOM, alternate Unicode encodings, invalid Unicode, duplicate raw or
NFC-colliding keys, trailing data, unknown fields/discriminators, fractional or
exponent-form JSON numbers, `-0`, ambiguous times, and every ceiling breach are
rejected. Decimal-domain values are non-exponent strings canonicalized before
evidence. Errors use fixed
codes and safe fixed field/index locations; they do not quote source values or
database details.

Canonicalization uses NFC, normalized line endings, UTC `Z` instants,
canonical decimal strings, sorted object keys, and stable semantic ordering.
Root item order, proposal-answer order, and multiple-choice selection order do
not change meaning. Ordered call arrays retain their meaning.
Every case-sensitive source key matches the exact ASCII grammar
`^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$`.

### Call item

A call item contains only `kind: "call"`, one case-sensitive stable
`source_key`, one complete ADR 0082 definition, and one complete configuration
without a Department UUID. The trusted batch Department is the owner. Version
one rejects `safe_file`, `person_reference`, and `domain_reference` questions.
Commit creates one Draft through the protected call command and never activates,
publishes, retires, or succeeds it.

### Proposal item

A proposal item contains only `kind: "proposal"`, stable `source_key`,
same-source-system `call_source_key`, exact lead login email, track and format
codes, requested duration, and applicant-writable answers. Every answer has
exactly `question_key`, `field_type`, and `value`; the declared type is digested
and must equal the resolved call question type. It rejects Maru identifiers, collaborators, invitations, contributor
profiles, consent or acknowledgement, lifecycle/review/decision state,
Programme records, hosts, reference/file answers, staff-only answers, explicit
null revisions, and inapplicable answers.

| `field_type` | Closed version-one value |
| --- | --- |
| `short_text`, `long_text` | NFC string with normalized line endings; only long text admits line feeds. |
| `integer`, `decimal`, `boolean` | Signed 32-bit JSON integer; canonical decimal string; exact JSON boolean. |
| `single_choice`, `multiple_choice` | One stable option code; or at most 100 unique stable codes sorted canonically. |
| `date`, `time`, `instant` | Exact calendar date; offset-free wall time; or explicit-offset instant normalized to UTC `Z`. Civil offsets are limited to +/-14:00 and `-00:00` is rejected. |
| `email`, `phone`, `url` | Valid email; 3-through-40-character phone; valid HTTPS URL. |
| `address` | Closed normalized postal-address object with upper-case country code. |

Decimal strings may use an equivalent non-exponent spelling at input and are
canonicalized before digesting. Null, reference types, and safe files are not
admitted.

The lead supplies their own contributor profile, publication choice, and
consent at claim. Imported answers need not satisfy later seal completeness;
ADR 0082 validates that when the lead explicitly seals.

## Organizer preview

An organizer preview is complete or unavailable: one immutable revision covers
all exact batch items and contains exactly one result per item. The envelope may
disclose only its opaque batch, revision, and receipt identifiers, revision
number, and replay flag. Each sanitized item may disclose only:

- its opaque immutable preview-result identifier, opaque item identifier, and
  item version;
- item kind and bounded ordinal;
- registered safe field keys;
- fixed reason codes;
- bounded counts;
- status `ready`, `blocked`, `no_op`, or `conflict` plus closed action
  `commit_call`, `claim_proposal`, or `none`; and
- dependency state `none`, `missing`, `draft`, `active`, or `retired`.

Safe field keys are closed to `configuration`, `definition`, `answers`,
`lead_action_required`, and `selection`. Reason codes are closed to
`source_already_applied`, `source_digest_conflict`,
`definition_code_conflict`, `call_dependency_unavailable`,
`call_dependency_not_active`, and `proposal_mapping_invalid`. Both arrays are
unique and canonical-order.

The immutable preview-result identifier, item identifier, and item version are
all required to adopt a ready call result through
`commit_programme_import_call`. Preview never returns a source key, login email,
identity-match state, Account or Person ID, imported answer, profile, consent,
canonical payload, request/source/item/content/result digest, stored
administrative rationale, or target/domain identifier. A change to one call
dependency invalidates only the affected proposal result.

## Lead-self preview and claim

Lead-self preview stores no match. It resolves the active verified account from
the exact staged email on every fresh preview and fresh claim, proves that
account is the actor, and repeats exact-self view/edit authority and lead
identity under locks immediately before release. Exact retained-receipt replay
rechecks current adoption-scoped retry authority and returns only the minimized
historical result. It audits the sensitive read with the caller-supplied
correlation ID and normalized source channel before releasing the
caller-supplied opaque item identifier, current item version, selection, and
each normalized `question_key`, `field_type`, and `value`. The returned
`adoption_digest` binds the actor, exact source identity, item
digest/version/schema, dependency binding/digest/version, selection, and
normalized answers. It is private command material, not a reusable public
identifier.

Lead-self preview does not create domain state and therefore does not require
open private-planning writes. Expiry, disposal, identity change, or loss of
exact-self view/edit authority still makes it unavailable.

Claim repeats the resolution and exact-self authority under lock. It requires
that value as `adopted_preview_digest`, then recomputes the locked fresh digest
and compares it in constant time. It also requires an active referenced call,
current item version, unexpired staging, and open planning writes. The complete
proposal/answer command chain is one outer transaction. Any nested failure
leaves no proposal, answer, binding, applied-command link, success audit, event,
outbox, or receipt.

## Source replay and item-local freshness

Source identity is the exact organization, edition, registered source system,
item kind, and case-sensitive source key.

The permanent binding must also preserve target lineage. Its source system
equals the parent batch source system; a call target is owned by the batch's
exact Department when the binding is created; and a proposal target uses the exact call named by its
same-source-system dependency, with one exact definition shared by that call
and proposal submission. An apparently compatible call or proposal in the same
tenant is not interchangeable.

A later valid Draft-call reassignment does not rewrite the source binding or
batch owner. A contiguous immutable Programme-command receipt chain links the
binding-time Department through every source-to-destination transition to the
call's current owner. A missing, branched, reversed, cross-scope, or
noncontiguous chain is invalid below the ORM as well as in the service.

- same identity plus the permanently applied digest is a no-op forever;
- same identity plus a different digest is a conflict forever;
- a later legitimate edit of the created Maru record changes neither result;
  and
- no fuzzy source, person, email, call, or proposal matching exists.

The same-digest no-op is a permanent organizer-preview result. It creates no
second domain target, invokes no nested Programme command, and has no separate
apply action. Its duplicate item therefore remains staged with private payload
until explicit authorized `discard_programme_import`; after expiry preview is
unavailable but disposal remains available. A call commit must adopt the exact
immutable organizer preview-result identifier, item identifier, and item
version. A lead must adopt a digest made fresh against the current call
dependency for proposal claim.

## Expiry, clearing, and disposal

The source package does not choose retention. A reviewed versioned server-side
provider returns the exact policy code and expiry; the default provider fails
closed when it has no approved configuration. Passing expiry makes preview and
application unavailable but does not mutate or dispose a row.

Successful application clears the exact item's canonical private payload in
the same transaction. Authorized disposal works after expiry, planning closure,
or owner-Department retirement, changes every remaining staged item to
discarded, clears those payloads atomically, and retains only the policy,
digests/sizes, minimized preview and source evidence, command evidence, and
attributable discard fact. There is no automatic cleanup job in this outcome.

A batch may be reassigned only while planning is open and it is unexpired,
wholly staged, payload-intact, source-unbound, and unapplied. Partial, applied,
source-bound, expired, or closed-planning staging is disposal-only. Applications
treats every remaining staged item as a Department-retirement dependency;
expiry alone does not unblock retirement. Applied or discarded evidence does
not block retirement, and Workforce receives only `clear`, `blocked`, or
`unavailable`, never a source, proposal, identity, kind, count, or digest.

## Safe failure and disclosure

- **Dormant or unpinned:** fail before reading the package or resolving source
  identity.
- **Invalid package:** return fixed code/location facts only and persist no
  batch or item.
- **No retention configuration:** stage nothing and expose no policy/provider
  internals.
- **Expired:** block preview/apply; continue to offer authorized disposal.
- **Reassignment ineligible:** disclose no item/binding detail; direct the
  authorized operator to exact-Edition disposal without weakening its separate
  authority.
- **Dependency missing/draft/retired:** return only the proposal item's safe
  dependency state; reveal no call title or owner.
- **No-op:** preview returns only the permanent `no_op` classification; it
  exposes no target detail and offers no apply action. Explicit disposal is the
  only way to clear the duplicate staged payload.
- **Digest conflict:** return one stable source-conflict category without either
  digest or target detail.
- **Identity changed:** use the same non-disclosing denied/unavailable shape and
  retain no old match.
- **Stale:** apply nothing and identify only the caller-visible item version
  conflict.
- **Nested/evidence failure:** roll back the complete outer transaction and
  return stable `applications_programme_import_operation_failed` plus a
  correlation reference only. After rollback, retain one minimized
  outer failure outcome; any nested success/failure audit in the rolled-back
  transaction is not duplicated. Corrupt or incompatible retained private
  canonical bytes use this boundary rather than exposing parser diagnostics.
- **Denied, absent, or foreign scope:** use one non-disclosing shape; never
  reveal tenant, Department, batch, item, person, or count existence.
- **Retirement dependency:** both call and import probes execute; any known
  `blocked` wins, otherwise an `unavailable` result fails closed. No staged
  fact is returned to Workforce.

Administrative rationale and private replay/content digests are retained only
in their dedicated restricted database evidence where required. They are never
copied into preview, audit metadata, event/outbox payload, log, metric, health,
or error output.

## Accessibility and future-surface acceptance

There is no browser surface to rehearse in issue #66. A later accepted surface
must preserve the service projections rather than load private payload and
filter it in a browser. It must use the shared shell, semantic `main`/`h1`,
associated labels and errors, visible focus, announced async state, keyboard-
complete item operations, non-color-only status, and touch-sized controls.

At 200 percent zoom and 320, 390, 768, 958, 1,024, 1,280, and 1,920 CSS pixels,
safe preview results must wrap without a page-level horizontal scroll. Browser
acceptance must cover dormant, empty, invalid, unconfigured policy, staged,
partial, expired, dependency-blocked, ready, no-op, conflict, stale, denied,
unavailable, disposed, and rollback states without adding a source/content-
digest or identity oracle. The exact-self lead flow may carry
`adoption_digest` as private command state but must not display source/content
digests or expose it outside claim.

## Evidence and non-goals

Every successful future mutation must atomically retain the exact batch/item
version, import receipt, minimized allow audit, dormant event, and transactional
outbox record. Apply additionally retains the exact ordered ADR 0082 receipt
chain and permanent source binding. The import receipt freezes
`applied_command_count`: one for call commit and start-plus-answer count for
proposal claim. The linked-row count and terminal sequence must equal that
immutable value, preventing later proposal revisions from being attached to a
completed import. The shared Applications retry namespace must reject
collisions across generic, Programme, and import receipts.

Batch reassignment adds one reasoned receipt with exact source/destination
Department references and the resulting batch version. It does not rewrite an
item, preview, applied-command chain, source binding, or payload. Those
Department references are restricted control evidence, remain protected after
retirement, and continue to block hard deletion without becoming live
retirement dependencies themselves.

Every failed protected command or lead-self read must leave one best-effort
minimized outer `deny` or `error` audit after its atomic work rolls back. That
record carries only safe scope, capability, operation, policy, correlation, and
source-channel facts; target identifiers, source data, identities, answers,
digests, rationale, and database details remain absent.

This outcome adds no CSV/XLSX guessing, background import, account creation,
collaborator or invitation import, import-driven call activation/retirement/succession,
proposal seal/submission/review/decision, accepted Programme adapter, Programme
item, host, occurrence, Venue placement, Shift, timetable, release,
publication, export, automatic cleanup, or compensating domain deletion. It
mounts no batch-reassignment or recovery route, API, UI, job, or worker and
pins no current profile or platform root.
