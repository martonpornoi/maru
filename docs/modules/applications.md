# Applications module

Status: mounted generic application portfolio plus implemented dormant
Programme-call, acknowledged-proposal, Programme-import, and Department-
ownership-continuity, staged-review and accepted-conversion kernels;
production remains gated
Last updated: 2026-09-15

## Purpose and boundary

`maru.applications` implements REG-023, PRG-001, PRG-002, PRG-009, IDN-014,
and a bounded intake/review slice of KNO-009. PRG-010 and ADR 0083 define the
implemented dormant preview-first Programme-import boundary; PRG-011 and ADR
0084 add its race-safe Department ownership and retirement continuation.
Protected-PR and deployment acceptance remain separate. Applications owns edition-scoped,
versioned contribution and service
applications built from one typed field vocabulary. Attendee registration
remains owned by `maru.registration`; the Registration starter is a
navigation/catalog entry and cannot be copied into this module. An application
never creates a second registration or grants a ticket, payment state,
convention role, or access. Configurable staff answer-correction windows,
public answer renditions, retention execution, and real downstream target
adapters remain outside this slice.

ADRs 0081 and 0082 preserve this ownership for the accepted but not executable
`programme_operations@1` profile. Applications owns the dormant Programme-call
and collaborative-proposal kernel as facets of its existing definitions and
submissions. It also owns reviewer assignments and conflicts, review evidence,
decisions, and the idempotent accepted-transition receipt under ADRs 0085 and
0086. The dedicated [Programme conversion](programme-conversion.md) consumes
one explicit, effectively accepted revision to create exactly one private item.
It does not copy the answer sheet into
Programme, make private review material public, grant a proposal collaborator
host access, or create attendee Participation.

The dormant foundation covers calls, acknowledged proposals, preview-first
import, Department ownership continuity, staged review, accountable decisions,
and explicit accepted conversion. Hosts and co-hosts remain a separate
Programme-owned successor; collaborator inclusion or proposal acceptance
never grants a host relationship.

The dedicated adapter binds `applications_accepted` provenance through a real
reciprocal foreign key and `programme.accepted-application-source@1`. Neither
current profile pins it. The generic `programme_item` review, decision,
acceptance, target-record, query, discovery and adapter seams still deny or
omit Programme; only the dedicated conversion command understands this
source contract. It atomically creates private working copy, seven required
readiness concerns and both owners' receipts/audits/events/outboxes.

ADR 0047's governed-writer rules apply: route scope is untrusted, commands use
closed inputs and expected versions, API retries use canonical UUID keys, and
successful mutations commit minimized audit, domain-event, and outbox evidence
in the state transaction.

## Definition lifecycle and starter catalog

An `ApplicationDefinition` is owned by one organization and edition and has a
stable code plus an immutable schema version. Its lifecycle is:

```text
draft -> active -> retired
          |
          +-> explicit copy-on-write successor draft
```

Drafts may change sections, questions, owner Departments, assigned reviewer
role versions, and optional named reviewers. Activation requires a complete
owner/reviewer/question graph. Active definitions and their child rows are
immutable; retirement changes lifecycle evidence only. A successor copies the
schema and assignments into a new independent draft.

The code-owned catalog contains one external Registration entry plus the ten
application-owned starters below. Only the application-owned starters can be
copied, and copies are never shared mutable templates:

| Starter | Target adapter |
| --- | --- |
| T-shirt and merchandise submission | `merch_submission` |
| DJ application | `dj_set` |
| Fursuit Dance Competition | `fursuit_dance_competition` |
| Maid Cafe | `maid_cafe` |
| Adult Fursuit Striptease | `adult_fursuit_striptease` |
| Volunteer application | `volunteer` |
| Feedback | `feedback` |
| Idea submission | `idea` |
| SecOps damage report | `damage_report` |
| Time-bounded helper | `helper` |

The helper starter sources the account display name and registration Telegram
contact through explicit read adapters and collects an explicit availability
interval. Source-bound questions are applicant-visible but not
applicant-writable.

Edition-scoped catalog and provider selection resolves the persisted adoption
profile code and version before disclosure or execution. `full_convention@1`
pins all eleven current catalog entries, all five eligibility providers, the
account-display-name and Registration-Telegram source providers, and the
Applications self-workspace purpose provider. It also pins an independent
versioned adapter key for each of the ten accepted target kinds.
`workforce_only@1` pins none of them, so it exposes no Applications starter,
self workspace, or target transition even if an unrelated grant or durable
Applications row exists. An unsupported exact profile pair, a later unpinned
starter, an unknown provider discriminator, or an incompletely pinned starter
dependency fails closed. Every non-external starter requires its accepted-target
adapter before catalog disclosure or copy. Copying a starter and activating or
evaluating a definition recheck the exact edition manifest; catalog growth
therefore cannot silently widen an existing profile version.

Reviewer queues apply the same exact-pair rule to each complete immutable role
version. The configuration selector omits a role when any capability in its
bundle is unpinned, the command rejects crafted role identifiers, activation
rechecks retained draft relationships, and every queue read or review decision
rechecks the configured role before accepting an organization-, edition-, or
Department-scoped assignment. Independent `applications.review` authority does
not make an incompatible role a valid queue relationship. Explicit named-person
reviewers remain a separate purpose relationship and still require the normal
edition capability decision before any submission is disclosed or changed.

## Dormant Programme calls

The [edition task entry](../product/page-contracts/programme-applications-entry.md)
adds a dormant read-only chooser without requiring a selected Department anchor.
`list_programme_department_tasks` in `programme_department_tasks` uses exact
active-person, edition and profile proof, Workforce's bounded current ID-only set,
and seven independently evaluated code-owned capability/field combinations before
resolving any label. The shared-shell route groups labelled calls, review setup,
reviewer management, own reviews, moderation, decisions and accepted conversion
by Department/code. Conversion additionally proves both exact adapter pins and
Programme's public `resolve_programme_item_entry_reference`: exact independent
edition item-management policy without inventory or source-content access.
Both policy sources are explained. Missing conversion permission/adapters omit
only that task; invalid owner/policy evidence withholds the complete catalog.
The source comparison includes adapter state and the Programme owner decision.
It borrows no Workforce structure or sibling-purpose authority, loads no private
application content, and revalidates the complete source around audit and rendering.
Empty results contain no hidden count or invented grant. Profile/owner/policy
incoherence, overflow and required audit failure release no partial catalog.
Current profiles/menus and production routing remain unchanged. Accountable setup,
other owner launchers and integrated acceptance remain #108 work.

The public `programme_department_tasks.can_enter_programme_tasks` supplies optional
metadata-only navigation admission through the same complete seven-purpose owner,
Department-ID, policy and conversion-adapter snapshot. It uses the default sealed
adapter with no public substitute parameter and reads no Department label, answers
or application inventory. False includes denied/unavailable/changed sources and
does not assert completeness. The shared Programme workspace navigation uses this
query for independently admitted Applications return links; the entry reciprocates
with separately admitted item, timetable, release and notice links. Repeated
post-render observations remove moved links without invalidating saved commands
or replacing pending input. This never replaces the labelled query's audit.

The [guided call workspace](../product/page-contracts/programme-call-workspace.md)
adds a dedicated, unmounted #108 manager adapter over the existing Programme
commands and complete managed projections. It provides exact-Department call
selection and configuration review, metadata/policy editing, separately confirmed
deadline replacement, explicit catalog ordering/removal and lifecycle actions.
Explicit creation collects metadata, policy references, edition-local deadlines,
an initial track/format and confirmation of the disclosed title/description and
lead-name starting form. Structured section/question controls cover all seventeen
closed types, typed conditions, bounded option rows, ordering and confirmed
removal. Cross-section moves validate the complete final graph atomically;
empty mandatory sections and broken dependencies are refused, not repaired.
Creation fences the displayed edition version and zone under the canonical lock;
editing preserves the original call cursor. Adding an option row saves no domain
state. A separate complete Department chooser and confirmed Draft transfer reuse
independent exact-Department authority and the dedicated dual-scope owner command.
The separate proposal, review and conversion journeys remain unfinished #108 work.
The generic studio and discriminator exclusions are unchanged.

The separate [personal proposal workspace](../product/page-contracts/programme-proposal-workspace.md)
reserves unmounted personal inventory, available-call discovery, explicit private
draft creation and relationship-filtered overview routes. It reuses the existing
self queries and `start_programme_proposal`, with labelled track/format choices,
bounded duration, only configured subject-owned profile values, explicit
publication intent and exact consent-policy acknowledgement. A blank non-public
profile remains possible; hidden fields and contradictory choices are refused,
not silently cleared. The displayed call schema/version and original proposal
creation cursor/retry key fence the input. Existing proposal history never depends
on new-call availability or current owner Department membership. Invitees receive
only the minimal field ceiling; leads and accepted collaborators may additionally
read only their own configured profile. Reauthorization surrounds rendered release.
The personal continuation adds separate editing/collaboration/seal/submission
tasks below; organizer review/conversion remains separate unfinished #108 work.
Neither increment activates the Programme profile.

The personal continuation has explicit non-persisted self-view fields
`workflow_context` and `frozen_revision`. The former supplies existing-proposal
lifecycle/source versions and role-minimized task choices without new-call entry
or current Department checks. Only leads receive track/format catalogs and the
collaborator limit; invitees receive no answer, roster or profile content.
The latter requires current relationship and exact seal inclusion, returns frozen
selection/shared answer revisions and only the actor's included frozen profile,
and never substitutes latest mutable values. Both queries revalidate scope and
audit atomically; bounded overflows or incomplete safe joins return no partial
projection. Personal forms and dedicated unmounted action routes preserve original
proof fields, explicit consent and offset-aware invitation input. Selection,
typed shared answers, own profiles, invitations/roster, sealing, reopening, exact
acknowledgement/decline, submission and withdrawal call only existing owner
commands. Submission carries an explicit seal identity, while responses also
carry exact included contributor and own-profile identities. Editing uses the
inclusive edit deadline; responses/submission use the exclusive close; withdrawal
does not require a current call/edit window. Each task proves independent read
and mutation authority and revalidates prepared content around rendering.
Forms retain stale original proofs, distinguish incomplete readiness from stale
state, and never infer that a lost response means a failed write. Leaving or
declining returns to own inventory; other commands return to the original
proposal, not a child revision returned by the command. Authorized reference/file
choices and later organizer review/conversion remain unfinished #108 work.

The shared integer normalizer enforces configured inclusive numeric limits and
signed-32-bit shape. HTML bounds use the corresponding whole-number limits,
including fractional source bounds. Before a new Programme seal, retained
non-null integer answers are checked against that same normalizer; invalid
answers require a new answer revision. Existing immutable seals/history are not
rewritten or retrospectively invalidated by this correction.

`programme_call_editor` reconstructs every typed question, condition, option,
policy, catalog and duration bound without querying or writing. It refuses stale
or non-draft source cursors and validates the complete resulting graph after a
small task edit. Its inputs are not authorization: `configure_programme_call`
still checks the exact current actor, Department, lifecycle, version and receipt
under the existing canonical locks. The HTTP adapter retains the original cursor
and retry key after refusal, including the possibility that an earlier request
committed before its response was lost; it never silently rebases an edit.

Metadata edits do not parse or round the existing deadline instants. The separate
window form deliberately replaces all three dates with whole-minute edition-local
input. It refuses ambiguous/nonexistent daylight-saving minutes and checks the
displayed Events aggregate version again under the shared canonical edition lock
through owner-command completion, preventing a concurrent zone change from
reinterpreting the editor's original local-time intent.

`get_managed_programme_call_department` uses Workforce's exact current name-only
reference after call-management authorization, then reauthorizes and appends
required protected-read audit before returning. It lists no other Departments,
holders, proposal counts or contributor values and does not require broader
Workforce structure permission. Ordinary ownership reassignment remains a
different dual-Department command; no orphan discovery or recovery UI is added.

`list_managed_programme_call_departments` in `programme_call_departments` starts
from an independently admitted exact Department. It obtains Workforce's complete
bounded ID-only current set, evaluates each exact call-management decision before
resolving an ID/code/name choice and rechecks membership, all candidate decisions
and current admitted scopes before audited disclosure. Only ordinary
`permission_absent` removes a choice. Incomplete/unsupported policy, overflow,
incoherent references, revocation or required audit failure discard the whole
projection. No hidden names, counts, hierarchy or holder references escape.
The supported management decision retains exactly its `reason`/`audit`
obligations; this restricted read records its coded purpose through the existing
protected-read audit contract, not a new free-form read-reason prompt.

The reserved `departments/` task supplies ordinary labelled links distinguished
by stable code. A Draft's `reassign/` task excludes its current owner from the
closed destination field and confirms the current and destination scope, reason,
original aggregate cursor and retry identity. Only `reassign_programme_call`
writes; it retains canonical locking, both independent authorities and current
private-planning checks. Configuration and retained evidence are not rewritten.
After success, the destination overview authorizes afresh. After a lost response,
the old source may be unavailable: the adapter supplies nondisclosing current-
inventory guidance, never an orphan directory or a promise of no earlier commit.
Read-only transfer pages load no other Department labels; ordinary chooser links
remain available for admitted inventories after planning closes. Accountable
setup still owns first entry. No edition-wide call-management grant is invented.

A `ProgrammeCall` is a one-to-one facet over an `ApplicationDefinition` whose
target kind is `programme_item`. It reuses the existing definition sections,
questions, eligibility window, answer types, field policies, and immutable
schema version rather than introducing a second form engine. Applications also
owns typed ordered children for tracks, formats, and contributor profile
fields. The closed contributor-profile vocabulary is public display name,
biography, pronouns, and website; consent is revisioned with the contributor's
own proposed-public values.

Exactly one current-edition Department owns a call. Cross-module validation
uses public identifier/reference seams; Applications does not import Workforce,
Identity, or Events model implementations. The call lifecycle is:

```text
draft -> active -> retired
          |
          +-> copy-on-write successor draft
```

Only draft content may change. Active and retired call configuration and
children are immutable; an editor creates an explicit successor draft. Domain
activation is not product activation: it does not select
`programme_operations@1`, publish or discover the call, widen either current
profile, or mount a route. Exact caps bound a call to 64 tracks, 32 formats,
four contributor fields, 16 collaborators per proposal, and 1,440 minutes per
format.

Ownership is not ordinary call configuration. `reassign_programme_call`
requires the exact current source and destination Departments, current call-
management authority at both scopes, an expected call version, retry key, and
reason. It may move only a Draft call and writes an immutable source-to-
destination transition in the Programme command receipt. An Active call must
instead use the ordinary retirement command. Historical calls whose owners
were retired before this boundary landed are reachable only by the exact-ID
`recover_orphaned_programme_call_reassignment` and
`recover_orphaned_programme_call_retirement` commands described below; no
recovery command discovers or lists an orphan.

## Dormant collaborative Programme proposals

A `ProgrammeProposal` is a one-to-one facet over one
`ApplicationSubmission`. The submitting person is the accountable lead. An
active, verified person is sufficient for call eligibility; no Participation,
Registration, payment, attendance, Workforce, membership, or other edition
relationship is created or required.

The existing append-only `ApplicationAnswerRevision` relation remains the only
answer history. Accepted collaborators may edit shared applicant-writable
answers. The lead alone changes the selected track and format and the included
contributor roster. Each contributor alone appends revisions of their own
proposed-public profile and consent; the lead cannot write those values for
them. Each included collaborator alone acknowledges or declines the exact seal;
the lead's attributable sealing action does not create a response row.

Collaborator membership is a purpose relationship with append-only transitions
through `invited`, `accepted`, `declined`, `left`, and `removed`. Invitation
expiry is derived from an unaccepted invitation and its deadline rather than
stored as an actorless transition. Expired invitations cannot be accepted and
do not block a later seal. Reinvitation appends a reasoned new invitation with
a new expiry and does not rewrite the old transition. Proposal collaborators
are not Programme hosts or co-hosts.

Every proposal mutation advances the owning `ApplicationSubmission`'s
`aggregate_version`. That is the only optimistic cursor for shared answers,
selection, roster, profiles, invitations, sealing, responses, reopening,
submission, and withdrawal. A stale expected version fails without a partial
child update, receipt, audit, event, or outbox row.

### Exact seal, acknowledgement, and submission

The lead seals a draft only after required answers and included contributor
profiles are valid and no unexpired invitation remains unresolved. One
immutable `ProgrammeProposalRevision` captures:

- the exact definition, call schema, and selection revision;
- the exact `ApplicationAnswerRevision` for every applicable question, or an
  explicit absence where no answer applies;
- the exact included contributor roster and profile revision for each person;
- the governing policy versions, predecessor when present, and canonical
  digest; and
- the resulting submission aggregate version.

Sealing blocks answer, selection, roster, profile, and invitation changes. Each
included collaborator acknowledges or declines only for themselves, against
that exact sealed revision and the exact included profile revision. Responses
advance the same submission aggregate version without changing the sealed
snapshot. The lead cannot respond on another person's behalf.

Lead submission requires the current seal, an acknowledgement from every
included collaborator, and no decline. It records that exact proposal revision
only. Reopening is explicit, preserves the previous seal and responses,
invalidates it as the current candidate, and requires a new seal before another
submission. The lead may withdraw a draft, sealed, or submitted proposal while
retaining all history. None of these transitions creates a review, decision,
target record, Programme item, host relationship, public rendition, occurrence,
Shift, schedule, or publication.

## Dormant Programme review and decisions

The [independent decision composer](../product/page-contracts/programme-decision-composition.md)
adds decider-only discovery, all-stage readiness, pinned recipient-message
preview separated from private rationale and exact signed confirmation. Retained
outgoing history is independently protected without exposing recipient lists or
others' receipt state. Original receipt recovery precedes private reads. This
does not activate Programme, grant conversion or create host/publication state.

The [review setup workspace](../product/page-contracts/programme-review-setup.md)
adds reserved manager call discovery, explicit structured policy composition and
immutable policy history. Its independent `review_setup` field ceiling exposes
configuration only, never submission answers or private review evidence. Unsaved
stage/template changes make no database record; final confirmation uses the
existing append-only owner command. Exact-seal selection and case opening now
connect to separately authorized [named-reviewer management](../product/page-contracts/programme-review-management.md):
complete retained rosters, known-email preview and exact-person confirmation or
reasoned removal. Assignment grants no review capability or content access.
The independently admitted [own reviewer workspace](../product/page-contracts/programme-reviewer-work.md)
adds own conflict declarations/recusal, complete reasoned rubrics, permitted
discussion and independently field-scoped sealed content/history. Its original
assignment-stage metadata supports uncertain receipt replay without loading
now-denied content. Moderator/decision/conversion and dedicated safe structured
answer viewers remain #108; no production route or profile is activated.

The [personal decision workspace](../product/page-contracts/programme-decision-receipts.md)
adds reserved unmounted history and exact-message tasks with explicit own receipt.
It uses exact-seal recipient queries and the dedicated review writer, not current
proposal membership or generic Applications decisions. Read/acknowledgement
capabilities remain separate. Historical decisions do not imply current effective
acceptance, conversion or hosting. Organizer review/moderation/conversion and
ordinary navigation remain unfinished #108 work.

The separate [Programme review and decisions contract](programme-review.md)
implements PRG-003/PRG-004 and ADR 0085. Explicit policies pin stage question
allowlists, rubrics, quorum, anonymity, discussion, and decision templates to an
exact submitted, contributor-acknowledged seal. Dedicated commands and audited
queries separate manager, reviewer, moderator, decider, and recipient authority.
They create neither a target receipt nor a Programme item. Generic review and
target seams remain closed, and no current profile or HTTP surface admits this
workflow. See its [migration and recovery runbook](../operations/applications-programme-review-migration-and-recovery.md)
for Authorization `0024` and Applications `0013` through `0015`.

## Dormant Programme import staging contract

PRG-010 and ADR 0083 define one implemented Applications-owned adapter,
`applications.import.programme_call_proposal@1`. It stages only strict JSON
schema version 1 and invokes the protected
Programme commands above; it never writes a call, proposal, answer, or ADR 0082
Programme receipt directly. It does own the seven import evidence models,
including `ProgrammeImportCommandReceipt`. The service catalog is closed to:

- `stage_programme_import`;
- `preview_programme_import`;
- `preview_programme_import_proposal_claim`;
- `commit_programme_import_call`;
- `claim_programme_import_proposal`;
- `reassign_programme_import_batch`; and
- `discard_programme_import`.

Pinning this import adapter is sufficient only for staging, organizer preview,
retry, and continuity disposal. Protected call/proposal application and
lead-self access independently require their purpose-specific Programme target
or self adapter gates; importing never widens those relationships.

The parser starts from raw bytes and caps the package at 8 MiB, 1,000 items,
depth 16, and 250,000 parsed values. One object has at most 32 members, one
generic array at most 1,000 elements, and one generic string at most 65,536
Unicode scalar values before narrower ADR 0082 limits apply. It rejects
alternate encodings, invalid Unicode, duplicate or NFC-colliding keys, unknown
shape, ambiguous numeric/time values, and lossy coercion. Canonicalization
creates separate private lowercase SHA-256 document and item digests.

A call item supplies a complete definition/configuration without Department
identity; the trusted batch Department becomes owner. Its apply path requires
both exact-Department `applications.import_programme` and an independently
successful `applications.manage_programme_calls` decision under locks, and may
create only a complete Draft through `create_programme_call`.

A proposal item supplies one exact lead login email, call source dependency,
track/format/duration, and applicant-writable answers whose exact
`question_key`/`field_type`/`value` shape is bound into canonical evidence and
must match the resolved call schema. Organizer preview may
persist and release only source-independent operational facts. It never reveals
the email, identity-match state, source key, answer, profile, consent, payload,
or digest. Lead-self preview re-resolves the active verified account from that
email for every disclosure, accepts trusted request correlation/source facts,
audits allow and denied outcomes, stores no Account/Person match, repeats the
authority/identity checks under locks immediately before release, and returns
only that actor's normalized typed answers and a fresh adopted digest. That
read remains available after planning writes close while staging is unexpired.
Claim
requires the active referenced call and invokes `start_programme_proposal`
followed by definition-order answer commands in one outer transaction. The lead
supplies their own contributor profile, proposed-public choice, and consent.

The accepted persistence contract contains exactly seven Applications-owned
models: `ProgrammeImportBatch`, `ProgrammeImportItem`,
`ProgrammeImportPreviewRevision`, `ProgrammeImportPreviewItemResult`,
`ProgrammeImportSourceBinding`, `ProgrammeImportAppliedCommand`, and
`ProgrammeImportCommandReceipt`. Batch state is only `staged` or `discarded`;
application and expiry are derived. A batch starts at positive version 1 and
advances monotonically for each ownership transition and final disposal.
Organizer preview binds the current batch version, so reassignment makes every
older preview stale without changing item versions or payloads. Each item
independently moves from staged version 1 to applied or discarded version 2.
Successful application or disposal nulls its private canonical payload in the
same transaction.

Source binding permanently keys exact organization, edition, source system,
item kind, and case-sensitive source key. The same identity and applied digest
is a no-op forever; a changed digest is a conflict forever, regardless of later
legitimate domain edits. A same-digest duplicate has no apply action and remains
staged/private until explicit disposal. One outer import receipt links the exact
ordered ADR 0082 receipt chain and freezes its immutable
`applied_command_count`. Call apply stores and links exactly one command;
proposal apply stores and links its start plus every answer. Deferred integrity
requires the linked-row count and terminal sequence to equal that frozen count,
so later legitimate proposal revisions cannot extend an older import chain.
Answer links belong to the target call's exact definition and increase in
strict `(section.position, question.position, question.id)` order. Generic,
Programme, and import receipts share one advisory-serialized
edition/actor/retry namespace. Apply pre-locks every deterministic nested retry
key in sequence before any batch/edition row lock, so direct Programme commands
cannot form a retry/edition deadlock. A nested or evidence failure rolls back
the whole outer mutation.

Replay reads those immutable receipt families without `FOR UPDATE`. The shared
transaction advisory lock (also held by native receipt-insert guards) serializes
the namespace, including the absence of a row. A row lock would require runtime
UPDATE permission even for an empty lookup and conflicts with the deliberate
append-only/read-only receipt ACLs. Aggregate and mutable-input locks remain
unchanged; this does not widen database grants or weaken retry collision checks.

A source binding must match its applied item's parent batch source system. At
binding creation, a call target must be owned by the batch's exact Department.
A later draft-call reassignment never rewrites the batch or binding; a
contiguous immutable Programme command-receipt chain from that original owner
to the current owner proves the transition. A proposal target
must use the exact call resolved through the proposal item's same-source-system
call dependency, and the proposal submission and call must share the exact
definition. Service checks and deferred database guards enforce each link;
matching shape or tenant scope alone is insufficient.

Each protected service wraps its atomic work with a minimized failure-audit
boundary. A failed validation, authorization, freshness, dependency, or nested
command leaves no success receipt/event/outbox/domain mutation, then records one
best-effort outer `deny` or `error` outcome without a target identifier or any
source, identity, answer, digest, rationale, or database detail.
Unexpected dependency/evidence exceptions become the stable
`applications_programme_import_operation_failed` boundary with only the safe
request correlation available to the caller. Corrupt or incompatible retained
canonical bytes use the same boundary and never re-expose parser diagnostics.

Staging expiry comes only from a reviewed, versioned server-side policy
provider; the default provider fails closed and no source document may select a
policy. A substitute provider is rejected outside the explicit two-factor
isolated-test guard. The timezone-aware server clock is authoritative for
expiry, freshness, and retained command times. An explicit `now` is accepted
only when `MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_CLOCK` is enabled and
the connected database name begins with `test_`; either condition alone fails
closed. Expiry blocks preview/application and does not dispose data. Exact-
Edition `applications.dispose_programme_import` remains available after expiry,
planning closure, or owner-Department retirement without current Department
authority. It clears remaining payload and never compensating-deletes an
applied call or proposal. There is no automatic cleanup job or service/system
actor in this outcome.

`reassign_programme_import_batch` is narrower than disposal. It requires open
planning, an unexpired wholly staged batch whose payload is intact, no applied
item or source binding, exact current import authority at both the source and
destination Departments, and the current batch version. It acquires the shared
edition write scope, locks both Departments in UUID order, advances only the
batch version and owner, and writes one minimized source-to-destination
receipt. A partial, applied, source-bound, expired, or closed-planning batch is
disposal-only. Expiry never disposes content and an unresolved expired batch
continues to block Department retirement until disposal succeeds.

The adapter, its import/disposal capabilities, and
`applications.programme_import.changed.v1` remain dormant and absent from both
current profiles. There is no HTTP/admin/browser/worker surface. The public
Applications retirement seam probes calls and imports independently and
returns only `clear`, `blocked`, or `unavailable`; a known block wins over an
unavailable sibling probe, otherwise unavailability fails closed. It never
returns a dependency kind, count, name, identifier, source fact, payload, or
digest. Workforce consumes only that closed result under the shared edition
mutex.

## Shared field contract

The [Programme person-reference contract](../product/page-contracts/programme-person-references.md)
defines #108's dormant `person_reference` / `programme.person` control and viewer.
It uses exact known-email selection, original-account confirmation/replay and
independent current/frozen/nonanonymous-review answer authority before minimized
Identity labels. It creates no collaborator or host relationship. Anonymous review
continues to omit reference rows before lookup. Selection and clear are previewed
before explicit confirmation; the existing answer command revalidates fresh person
eligibility after canonical replay. Its optional paired call/schema fences are
included in new intent digests and checked under the existing source locks; omitted
fences preserve legacy digests. No migration or generic reference resolver is added.
The [same-call domain-reference contract](../product/page-contracts/programme-domain-references.md)
adds closed `programme.call-track` and `programme.call-format` questions with
complete bounded native choices, original-target confirmation and independently
admitted current, sealed and nonanonymous review viewers. These additional private
answers never change the lead-owned selection or review routing. Shared source
admission is target-neutral; person eligibility remains owned by Identity and domain
membership by Applications. Fresh canonical writes validate same-call membership;
successful retained replay precedes fresh checks. No schema or generic resolver is
introduced. Native, integrated and human acceptance remain gated; safe-file controls
and unknown reference kinds are separate unfinished work.

Sections contain ordered questions using a closed vocabulary: short and long
text, integer, decimal, boolean, single and multiple choice, date, time,
instant, email, phone, URL, address, person reference, domain reference, and a
safety-checked file receipt. Each question records:

- stable key, label, help, purpose, and classification;
- required and closed conditional-display rules;
- length, numeric, option, choice-count, and reference constraints;
- applicant/staff/reviewer visibility and writer policy;
- public-after-approval and API-projection policy; and
- field or definition retention policy.

Question classification cannot exceed definition classification at
activation. Only separately reviewed C1 renditions may be marked public.
Safety-checked files reference an immutable clean scanner receipt; arbitrary
paths, unscanned uploads, and client-declared scan status are rejected.

ADR 0104 defines the Programme supporting-file boundary. The first dormant
`programme_file_preparation.prepare_programme_pdf` seam supports exact PDF bytes
up to 10 MiB, preserving them through an exact framed ClamAV INSTREAM exchange.
A dedicated disabled-by-default loopback-only scanner configuration has no
unscanned test/rehearsal override. One whole-operation deadline, bounded chunks
and reply bytes, and reading through connection close prevent partial or extra
responses from becoming clean evidence. No ORM, storage, authorization, receipt,
answer or profile write is performed; the prepared value is never a permission
token or caller-supplied proof. This does not activate the safe-file editor.
ADR 0105 adds dormant private database custody: `ProgrammeFileIntake` binds exact
proposal/question/uploader, scan time, original proposal/call/schema versions and
the canonical first-answer retry; separate `ProgrammeFileContent` holds bytes.
There is no second answer cursor or receipt namespace. Deferred integrity requires
content plus the first existing answer and its canonical success receipt in one
transaction. New non-null Programme file answers require same-purpose custody;
generic receipts alone no longer suffice. A proposal retains at most 64 intakes
and 64 MiB including historical versions; each PDF remains capped at 10 MiB.
These limits serialize on the existing edition/proposal boundary. Both new
relations remain runtime SELECT-only, with owner-only guard functions.

Migrations 0019–0021 install schema, integrity and a populated downgrade fence.
The preflight refuses unproven legacy Programme file answers or reserved
`programme-db/` receipts rather than inventing custody for old data. Exact metadata
was observed in an approved disposable schema-only check; native behavioral
acceptance remains unexecuted #102 debt.

`programme_file_commands.upload_and_use_programme_file` now owns dormant intake:
it admits the exact contributor, applicable private question, original versions,
lifecycle and capacity before invoking a bounded transport reader. Scanner settings
must be valid before reading; scan occurs outside an enclosing transaction.
Afterward, canonical retry/edition/proposal locks protect repeated read and write
authority, source/version/applicability and exact quota checks. Receipt, intake,
bytes and the existing answer command commit together; only that command advances
the submission. Its routine rationale is the explicit upload-and-use intent, not
an additional collected private explanation. Failure retains no partial custody
and uses the existing minimized answer-command failure audit.

`get_programme_file_upload_result` accepts no body and resolves only the original
canonical outcome. A used key rejects another upload before body reading. A
concurrent winner may be replayed only with matching bytes and original intent;
different bytes conflict. Result lookup is not attachment-read authority and never
creates a missing answer. Fresh canonical file-answer selection also validates
exact intake scope before its native guard. Clearing an answer needs no file lookup.

`programme_file_queries.get_self_programme_file` and
`programme_review_file_queries.get_programme_review_file` independently authorize
an exact current/sealed or stage-allowed review answer before custody lookup. The
former requires genuine shared/included-contributor view fields; the latter retains
separate reviewer/moderator/decider, assignment, conflict and sensitive-content
ceilings. Anonymous review omits file lookup entirely. Neither accepts a receipt
identifier as caller authority or infers permission from upload/result recovery.
Metadata returns only presence/size alongside authorized question text; explicit
`include_bytes=True` verifies exact bounded length and digest before final source
comparison and required protected-read audit. Bytes and source proof are hidden
from diagnostic repr. Shared access does not relax uploader selection restrictions.

The dormant [supporting-file tasks](../product/page-contracts/programme-supporting-files.md)
now provide native local-PDF selection, explicit upload-and-use, original-result
recovery, deliberate clear and independently authorized personal/review viewers.
`programme_file_transport` accepts bounded raw-PDF PUT with normal CSRF header
protection; no multipart upload or exemption is introduced. Signed original intent
binds actual actor/scope, all three versions and retry identity, not authority.
Only the upload/recovery page permits same-origin fetch in its otherwise default-deny
CSP. An attempted file cannot be silently replaced or resent; a retained page reload
offers body-free recovery only. Ordinary clear uses the canonical answer command,
fixed routine rationale and explicit confirmation; retained bytes/history survive.
Attachment responses have fixed code-owned filenames, no inline preview, no-store
and nosniff; after response preparation the adapter repeats independent source and
authority admission before releasing bytes. Anonymous review exposes no file link
or custody lookup. Reserved routes remain absent from production. No scanner
deployment, runtime grant or current profile activation is provided. See the
[file-handling contract](../operations/programme-supporting-file-handling.md).

## Applications, revisions, and review

Eligible people create bounded ordinal drafts during the configured window.
Eligibility is closed to authenticated people, edition participants,
registered attendees, confirmed attendees, or active volunteers. Cardinality
and applicant edit deadlines are enforced server-side. Programme invitation
expiry cannot extend beyond the inclusive applicant edit deadline, preventing
an unexpired invitation from permanently blocking a draft after cutoff.

Answers are append-only `ApplicationAnswerRevision` rows. Every revision keeps
the question identifier, stable key/type/classification snapshots, sequence,
normalized value, source, actor, and time. Applicant, authoritative source,
and future reasoned staff-correction provenance are distinct. Current answers
are a projection over revisions, not a mutable response row.

Review queues combine an exact immutable `RoleBundle` version with optional
named people. A reviewer must have the current review capability and match the
definition's assigned queue. Sensitive definitions additionally require
`applications.review_sensitive`. Review decisions are append-only, reasoned,
sequenced, and retain whether authority came from the exact role version or a
named-person assignment.

Acceptance creates one immutable `ApplicationTargetRecord` whose adapter kind
must equal the definition's closed adapter discriminator. It is transition
evidence for the target-domain adapter, not a generic answer sheet. Downstream
typed modules consume that explicit adapter transition; they do not treat the
application answer projection as their source of truth. Activation checks the
definition's versioned target-adapter pin, and acceptance checks it again
immediately before creating the typed target. A legacy definition or future
same-namespace adapter absent from the exact manifest cannot cross that
boundary.

## Sensitive policy fence

C3/C4 definitions and the adult and damage-case adapters cannot activate with
blank or `default`, `generic`, or `standard` policy codes. They require an
edition-approved audience and retention policy. The adult adapter also
requires minimum age 18 and an explicit age-policy version. Python validation
and PostgreSQL triggers enforce the same fence. Sensitive review requires the
non-delegable sensitive-review capability.

## Authorization

The catalog entries are:

- `applications.manage_definitions` at exact edition scope;
- `applications.review` for assigned C1/C2 queues;
- `applications.review_sensitive` for assigned C3/C4/adult/case queues;
- non-persistable `applications.view_self`; and
- non-persistable `applications.apply_self`.

The dormant Programme vocabulary additionally declares exact current-
Department `applications.manage_programme_calls` authority with no hierarchy
inheritance, plus purpose-scoped self capabilities to
view, edit, respond to an invitation, manage, and submit one's own Programme
proposal. The purpose and target descriptors are
`applications.self.programme_proposal@1` and
`applications.target.programme_item@1`. They are declarations, not current
authority: neither current v1 manifest pins them, and an unrelated grant or
role cannot bypass the manifest denial.

The dormant import vocabulary declares delegable exact-Department
`applications.import_programme` and delegable exact-Edition
`applications.dispose_programme_import`. Disposal grants continuity mutation
without staged-content read authority and deliberately does not require a
current Department or open planning writes. Neither capability is pinned by a
current profile.

The separately dormant
`applications.recover_programme_department_ownership` capability is exact-
Edition, nondelegable, and break-glass-required. It accepts one caller-supplied
call identifier and the expected retired source Department; it grants no list,
search, content read, import preview, or general Programme authority. No
current profile, root role, route, job, or UI pins it. Normal batch cleanup
continues through the independently authorized exact-Edition disposal command;
the recovery capability does not widen import reads.

Self capabilities resolve against the authenticated account and exact edition,
not a client-supplied subject. Organizer, applicant, and reviewer queries scope
every lookup by organization and edition. Applicant projections release only
applicant-visible answers; reviewer projections require both staff-visible and
reviewer-visible policy. Protected organizer, self, and review reads append
minimized sensitive-read audit evidence before response release.

## HTTP contracts

The dedicated dormant Programme proposal adapters additionally use the public
Scheduling `personal_programme_task_links` seam for fixed-label, same-person,
same-edition hosting and timetable continuations. Each owner admits its own fields;
no relationship or content is loaded for navigation, and no purpose is inferred.
Current route resolution and final optional-link observation can omit links without
repeating a command or replacing original inputs. Existing proposal source guards
run after the final render, including link recovery. This does not change the
mounted generic Applications routes or either current adoption profile.

The Programme-call and proposal kernel adds no HTTP contract. No browser route,
v1 API operation, serializer, OpenAPI schema, template, navigation destination,
Django admin writer, job, worker, or delivery handler exposes it. The mounted
generic routes below explicitly omit or deny Programme definitions and
submissions until later children implement their own reviewed surfaces.

The same Django admin shell now exposes executable organizer, applicant, and
reviewer journeys rather than read-only projections. Each view builds from
`admin.site.each_context(request)`, so navigation, pinned destinations, and the
shared Access explanation remain consistent. Applicant pages set the personal
surface flag and never inherit selected-edition staff navigation.

Personal discovery does not require an admin edition context. It bounds
distinct edition candidates before evaluating eligibility, shows only editions
where the person has an available definition or their own submission, and then
links to the exact-edition workspace:

```text
GET  /my/applications/
GET /my/organizations/{organization_id}/editions/{edition_id}/applications/
POST /my/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/start/
GET  /my/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/
POST /my/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/answers/
POST /my/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/submit/
```

Organizer pages copy a code-owned, non-external starter into an independent
draft; configure its purpose, classification, eligibility, window,
cardinality, policy, exact owner Departments, immutable reviewer role versions,
and optional exact named reviewers; add sections and questions; and activate,
retire, or create a copy-on-write successor:

```text
GET /admin/organizations/{organization_id}/editions/{edition_id}/applications/
GET|POST /admin/organizations/{organization_id}/editions/{edition_id}/applications/starters/{starter_code}/copy[/submit]/
GET      /admin/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/
POST     /admin/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/{configure|sections|questions|activate|retire|successor}/
GET /admin/organizations/{organization_id}/editions/{edition_id}/applications/review/
GET  /admin/organizations/{organization_id}/editions/{edition_id}/applications/review/{submission_id}/
POST /admin/organizations/{organization_id}/editions/{edition_id}/applications/review/{submission_id}/decisions/
```

Definition-window `datetime-local` values are interpreted only in the
persisted edition IANA time zone. Ambiguous fall-back and nonexistent
spring-forward wall times are rejected. Command versions, cardinalities, age,
length, and choice constraints require canonical base-10 integers; duplicate,
unknown, and alternate transport spellings are rejected. Applicant answer
fields remain typed according to the question definition. Every HTML mutation
uses the same idempotent command service as the v1 adapter, ignores preview
state, and returns safe validation or stale-version errors without disclosing a
foreign object.

The strict JSON API contract is documented separately in
[`applications-api.md`](applications-api.md).

```text
GET|POST /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/definitions
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/starters
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/commands
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/me
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/submissions
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/answers
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/submit
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/review-queue
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/review-decisions
```

Definition commands use the closed `operation` discriminator. Every mutation
requires a canonical `Idempotency-Key`; same-key/same-intent requests replay
the original receipt and changed intent conflicts. Unknown query or JSON
fields, client-owned scope, lifecycle evidence, and result fields are rejected.

## Evidence, migrations, and recovery

Each successful mutation appends an immutable command receipt, `allow` audit
event, minimized `applications.definition.changed.v1` or
`applications.submission.changed.v1` event, and transactional outbox message.
Event envelopes contain lifecycle/adapter facts only and never answers,
contact information, reviewer reasons, or question text.

Successful dormant Programme commands use a separate Applications-owned
Programme receipt and exact aggregate-version proof. State, dedicated receipt,
minimized allow audit, `applications.programme_call.changed.v1` or
`applications.programme_proposal.changed.v1`, and transactional outbox evidence
commit atomically. The dormant events contain action, lifecycle, and version
facts only; they contain no answer, profile value, consent, invitation address,
or contributor roster. They have no current-profile destination or handler.
The dedicated receipt is not the existing runtime-insertable generic receipt,
so installing the new schema does not widen raw-DML proof authority.

Migration `0001` creates the bounded schema. Migration `0002` installs tenant,
definition-lifecycle, activation-graph, append-only revision, contiguous review
history, exact queue-basis, IDN-011 subject, and typed-target triggers. Terminal
Applications migration `0003_integrity_function_execute_boundary` revokes the
default `PUBLIC EXECUTE` privilege from all seven Applications integrity
functions, leaving function `EXECUTE` owner-only. The functions still run
through their installed triggers for permitted table DML, but the production
runtime role receives no direct `EXECUTE` privilege. Readiness requires both
integrity migrations and proves the functions' exact owner-only ACL. Reversing
`0003` restores the prior `PUBLIC EXECUTE` behavior and therefore makes
readiness fail closed. Reversing `0002` removes triggers and functions but does
not delete domain data. A deployment must review retained applications before
reversing the app migrations; ordinary application deletion is intentionally
blocked pending a governed retention workflow.

Applications `0004` adds the empty Programme-call, collaborator, exact-snapshot,
response, and dedicated receipt relations without modifying an existing
edition, profile, definition, submission, answer, review, decision, or target
row. `0005` installs the consolidated exact Applications function/trigger
catalog across old and new relations, including scope, lifecycle, append-only,
contiguous-version, immutable-snapshot, actor-attribution, receipt, and legacy-
target-denial guards. `0006` is the early populated downgrade fence. Empty
reversal is exact; durable Programme-call or proposal evidence refuses reversal
before protected objects can be dropped.

All new relations are `SELECT`-only for the production runtime role, and all
new integrity functions are owner-only. Readiness fingerprints the complete
Applications relation, constraint, index, function, trigger, owner, and ACL
contract. Installation leaves the literal `full_convention@1` and
`workforce_only@1` manifest fingerprints unchanged and creates no domain row.
Recovery fixes forward or performs a mutually consistent whole-database
restore, explicitly including Applications, Authorization, Identity,
Workforce, Audit, Effects event/outbox, and migration history from one point;
it never fabricates a collaborator response, sealed snapshot, review,
decision, target, Programme item, or host relationship.

ADR 0083's implementation continues from Applications `0006` with
`0007_programme_import_persistence`, pairs Workforce `0017` with the new batch
owner-Department foreign key, and pairs Authorization `0022` with the two
dormant capabilities. Applications `0008` installs the consolidated
import integrity catalog from Applications `0007` plus Authorization `0022`;
it deliberately does not depend on Workforce `0017`. Applications `0009`
provides the populated downgrade fence. Reversing import integrity restores
the exact `0005` guard catalog, while any row in any of the seven import
relations refuses schema reversal and requires fix-forward or one mutually
consistent whole-database restore.

All seven import relations remain runtime `SELECT`-only and every import
function owner-only. Applications readiness covers the complete generated
catalog for all 33 managed `applications_*` relations, including exact columns
and collations, constraints, indexes, triggers, owner-only functions, relation
flags, owners, and ACLs. Fresh PostgreSQL 17 generated 442 columns and
collations, 367 constraints, 263 indexes, 87 triggers, and 22 owner-only
functions. The constraint SHA-256 is
`c20c6cd829ddc9045d6e07bfcfb39cda7e75a21a7070f4f0ad3b3b2e96aa3ecb`; the
index SHA-256 is
`501634da18934c04c6234533fac4f01987fb5ddcc3db3a14f76d5c837097425f`.
These values belong to the exact release head; an earlier schema snapshot is
not acceptance evidence.

PRG-011 and ADR 0084 continue the graph with Authorization
`0023_programme_department_ownership_recovery`, Applications
`0010_programme_department_ownership_persistence`,
`0011_programme_department_ownership_integrity`, and
`0012_programme_department_ownership_downgrade_fence`, followed by Workforce
`0018_programme_department_ownership_contract`. Applications `0010` adds the
nullable protected source/destination Department references used only by call
and import ownership-transition receipts. `0011` installs the exact-scope,
contiguous-owner-chain, monotonic-version, shared-edition-mutex, receipt-backed
writer, and raw-DML retirement guards. `0012` refuses reversal once a post-
cutover ownership transition exists. Forward migration does not invent
receipts for a historical orphan; recovery fixes that record forward through
one exact-ID command.

All Programme call, proposal, import, and ownership-continuity relations remain
runtime `SELECT`-only and every integrity function remains owner-only. The
generated readiness catalog for the exact release head—not the earlier ADR
0083 counts or digests—is authoritative. Workforce recognizes exactly 19
protected Department foreign-key references after `0018`, including the four
source/destination receipt references. Reversal and whole-database restore must
keep Applications, Authorization, Workforce, Audit, Effects event/outbox, and
migration history mutually consistent.

Focused verification covers the closed starter/event/capability catalogs and
PostgreSQL workflows for policy activation, idempotency, applicant/reviewer
visibility, exact role attribution, acceptance transition, audit/outbox
evidence, append-only enforcement, and tenant isolation.

Issue #66 adds focused parser, service, persistence, disposal, readiness, and
migration-contract checks; exact execution results belong in the current
checkpoint and protected pull request rather than this durable module contract.

The final canonical current-tree repository gate passed all 4,067 tests in
15,558.23 seconds (4:19:18) at 90.78 percent coverage. This accepts the bounded
Applications module in the repository; it is not production deployment,
retention execution, or acceptance of the still-missing downstream typed
adapters and broader KNO-009 workflow.
