# Applications module

Status: mounted generic application portfolio plus implemented dormant
Programme-call, acknowledged-proposal, and Programme-import kernels; production
remains gated
Last updated: 2026-09-01

## Purpose and boundary

`maru.applications` implements REG-023, PRG-001, PRG-002, PRG-009, IDN-014,
and a bounded intake/review slice of KNO-009. PRG-010 and ADR 0083 define the
implemented dormant preview-first Programme-import boundary; protected-PR and
deployment acceptance remain separate. Applications owns edition-scoped,
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
submissions. It will also own later reviewer assignments and conflicts, review
evidence, decisions, and the idempotent typed target receipt. A future
Programme adapter may consume only one explicit accepted revision to create or
reconcile a private Programme item. It must not copy the answer sheet into
Programme, make private review material public, grant a proposal collaborator
host access, or create attendee Participation.

Issue #63 deliberately stops before import, review, decision, target creation,
or Programme ingestion. Issue #66 now contracts preview-first call and proposal
import as the immediate dormant successor without mounting it. Structured
review and decisions, then the accepted Programme adapter, follow as separate
children. Host and co-host relationships begin only after that accepted
transition and remain Programme-owned.

The dormant Programme foundation now reserves a structural
`applications_accepted` source binding and declares
`programme.accepted-application-source@1`. Neither is an adapter
implementation: no current profile pins that descriptor and no Applications
command invokes it. The `programme_item` target discriminator is reserved, but
every generic review, decision, acceptance, target-record, query, discovery,
and adapter seam denies or omits it. A future child must validate one exact
immutable accepted proposal revision, preserve idempotency across both modules,
and create only the typed Programme binding and receipt in one documented
orchestration transaction.

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
- `claim_programme_import_proposal`; and
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
application and expiry are derived. Each item independently moves from staged
version 1 to applied or discarded version 2. Successful application or
disposal nulls its private canonical payload in the same transaction.

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

A source binding must match its applied item's parent batch source system. A
call target must be owned by the batch's exact Department. A proposal target
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

The adapter, its two capabilities, and
`applications.programme_import.changed.v1` remain dormant and absent from both
current profiles. There is no HTTP/admin/browser/worker surface. Issue #64 must
make unresolved staging a disclosure-safe Department-retirement dependency and
provide governed reassignment/disposal/recovery before any import/profile
activation.

## Shared field contract

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

Self capabilities resolve against the authenticated account and exact edition,
not a client-supplied subject. Organizer, applicant, and reviewer queries scope
every lookup by organization and edition. Applicant projections release only
applicant-visible answers; reviewer projections require both staff-visible and
reviewer-visible policy. Protected organizer, self, and review reads append
minimized sensitive-read audit evidence before response release.

## HTTP contracts

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
