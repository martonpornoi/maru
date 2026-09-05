# ADR 0083: Stage Programme imports behind an exact preview and claim boundary

- Status: Partially superseded by ADR 0084 for fixed batch versions and timeless
  imported-call owner equality; all other decisions remain accepted.
- Date: 2026-09-01
- Extends: ADRs 0001, 0003, 0005, 0041, 0051, 0081, and 0082
- Requirements: IDN-014, PRG-001, PRG-002, PRG-006, PRG-009, PRG-010,
  AUD-001, AUD-003, AUD-005, PRI-001, NFR-002, NFR-003, NFR-008 through
  NFR-010, and NFR-013
- Issue: [#66](https://github.com/martonpornoi/maru/issues/66), child of
  [#48](https://github.com/martonpornoi/maru/issues/48)

## Context

A convention may already have Programme calls and proposal drafts in another
system when it first evaluates Maru. Requiring manual re-entry would make
progressive adoption costly, while importing directly into Applications would
bypass the call and proposal validation, authorship, optimistic concurrency,
audit, event, and retry boundaries accepted in ADR 0082.

The source package contains private proposal answers and an exact login email.
An organizer needs to understand whether a bounded package can be applied
without receiving that private content or learning whether the email currently
matches an account. The proposal lead, not the importer, must supply their own
proposed-public contributor profile, publication choice, and consent. A source
identity also needs a permanent answer: applying the same content again is a
safe no-op, while different content under that identity is a conflict even if
the created Maru record has since been edited legitimately.

Temporary staging is itself a privacy obligation. Expiry may stop further use,
but cannot erase data silently or prevent an authorized continuity actor from
disposing it after planning closes or the owning Department retires. Import
therefore needs a separately authorized disposal boundary and an explicit
dependency on issue #64 before any profile activation.

This ADR accepts and freezes the dormant import contract. Its models,
migrations, and services are implemented, while verification and protected-PR
acceptance are reported separately. Implementation does not activate a profile,
surface, runtime writer, retention approval, or production-data permission.

## Decision

### Declare one dormant Applications adapter

Applications owns the adapter
`applications.import.programme_call_proposal@1`. It accepts only strict JSON
schema version 1 and may call only the protected Applications Programme
commands accepted by ADR 0082. It is not a generic bulk-import framework and no
external system becomes authoritative for a Maru call or proposal.

The global catalogs declare:

- delegable `applications.import_programme` with maximum exact Department
  scope;
- delegable `applications.dispose_programme_import` with maximum exact Edition
  scope; and
- acknowledged dormant event
  `applications.programme_import.changed.v1` with no handler or delivery
  route.

Neither `full_convention@1` nor `workforce_only@1` pins the adapter,
capabilities, event, destination, or writer. `programme_operations@1` remains
unselectable. This issue adds no URL, upload endpoint, API or OpenAPI operation,
serializer, template, navigation destination, Django admin writer, worker,
queue, schedule, periodic task, or system actor.

The import adapter pin independently admits staging, organizer preview, retry,
and continuity disposal. It does not imply the separate Programme target or
self-service adapter pins: protected call/proposal application rechecks those
owning-domain gates independently.

### Accept one closed raw-byte document

The source document root has exactly three members: `schema` equal to
`applications.programme_import`, integer `version` equal to `1`, and `items`
containing one through 1,000 closed call/proposal objects. Organization,
edition, owner Department, source-system code, actor, reason, retry key,
correlation ID, and source channel are trusted command context. The reviewed
server-side retention provider supplies the policy code and expiry. Every one
of those context or retention values is rejected if supplied by the document.

The raw-byte parser enforces the byte ceiling and lexical nesting-depth ceiling
before JSON decoding. The strict decoder then immediately checks the remaining
graph ceilings before any typed import value or persistent row is constructed.
The decoder is not streaming; its transient decoded graph is still bounded by
the pre-decode 8 MiB ceiling:

| Resource | Version-one ceiling |
| --- | --- |
| Raw UTF-8 document | 8 MiB |
| Root call/proposal items | 1 through 1,000 |
| JSON nesting depth | 16 |
| Parsed values in the whole document | 250,000 |
| Members in one object | 32 |
| Elements in one array before a narrower field rule | 1,000 |
| Unicode scalar values in one generic string before a narrower Programme rule | 65,536 |

The parser rejects a UTF-8 BOM, UTF-16/32, invalid UTF-8, unpaired surrogates,
disallowed controls, empty input, malformed JSON, trailing data, duplicate raw
keys, and keys that collide after Unicode NFC normalization. Unknown fields,
missing required fields, and unknown discriminators are rejected at every
level. JSON numbers admit only exact bounded integers; decimal-domain values
are non-exponent strings canonicalized before evidence. Fractional JSON
numbers, exponent notation,
`-0`, non-finite values, oversized integers, and lossy coercion are invalid.
Instants require an explicit offset, convert to UTC `Z`, and reject naive,
ambiguous, or invalid spellings. Numeric offsets are limited to `-14:00`
through `+14:00`; `-00:00`, an offset minute above 59, and a nonzero minute at
14 hours are invalid.

Error output uses fixed codes and safe fixed field/index locations. It never
copies a source key, email, answer or policy value, payload excerpt, digest,
identity state, database message, or internal identifier.

Canonicalization reuses the ADR 0082 normalizers: NFC text, normalized line
endings, canonical decimal strings, explicit-offset instants converted to UTC
`Z`, sorted object keys, and stable semantic ordering. Root item order,
proposal-answer order, and multiple-choice selection order are non-semantic.
Call arrays that define positions retain their order and receive one-based
positions. The adapter retains separate lowercase SHA-256 document and item
digests as private integrity evidence; no user projection displays them.
Every source key is case-sensitive ASCII matching
`^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$`.

### Keep call and proposal items narrower than the Programme domain

A call item contains only `kind: "call"`, a case-sensitive stable
`source_key`, one complete ADR 0082 call `definition`, and one complete call
`configuration` without a Department UUID. The trusted batch owner Department
is injected by the adapter. Version one accepts the same tracks, formats,
contributor fields, sections, questions, options, conditions, classifications,
durations, policies, and lifecycle vocabulary as ADR 0082, subject to the same
narrower bounds. It rejects `safe_file`, `person_reference`, and
`domain_reference` questions. Applying the item calls
`create_programme_call` once and creates a complete Draft only. It cannot
activate, publish, retire, succeed, or otherwise advance the call.

A proposal item contains only `kind: "proposal"`, its stable `source_key`, a
`call_source_key` in the same trusted source system, the lead's exact login
email, stable track and format codes, requested duration, and
applicant-writable answers. Every answer object has exactly `question_key`,
`field_type`, and `value`; the declared type is included in the canonical
digest and must equal the resolved call question type. It rejects Maru
IDs, collaborators, invitations, contributor profiles, consent or
acknowledgement values, submission/review/revision/decision state, Programme
items, hosts, reference or file answers, non-applicant-writable answers,
explicit null revisions, and inapplicable conditional answers.

The admitted answer types and wire values are closed:

| `field_type` | Version-one `value` and canonical form |
| --- | --- |
| `short_text`, `long_text` | String; NFC and normalized line endings, with line feeds admitted only for long text. |
| `integer` | Exact signed 32-bit JSON integer; booleans are not integers. |
| `decimal` | Non-exponent decimal string with at most 18 digits and 4 decimal places; equivalent spellings are normalized, trailing fractional zeroes are removed, and negative zero becomes `"0"`. |
| `boolean` | Exact JSON boolean. |
| `single_choice` | One lower-case stable option code. |
| `multiple_choice` | At most 100 unique lower-case stable option codes, canonical-sorted. |
| `date` | Exact valid `YYYY-MM-DD` string. |
| `time` | Exact valid offset-free `HH:MM:SS[.ffffff]` string, fraction-normalized. |
| `instant` | Exact explicit-offset instant, normalized to UTC `Z` under the closed offset rule above. |
| `email` | Syntactically valid bounded email string. |
| `phone` | Bounded 3-through-40-character string. |
| `url` | Valid HTTPS URL string. |
| `address` | Exact required `line_1`, `locality`, `postal_code`, `country_code` object plus optional `line_2`/`region`; normalized text and upper-case country code. |

Null is not an answer value. `person_reference`, `domain_reference`, and
`safe_file` remain excluded from version one.

At claim time the lead supplies their own contributor profile,
proposed-public choice, and consent. Required-answer completeness remains the
later ADR 0082 seal invariant rather than a staging invariant.

### Expose six services with separate authority

The dormant service surface is closed to:

- `stage_programme_import`;
- `preview_programme_import`;
- `preview_programme_import_proposal_claim`;
- `commit_programme_import_call`;
- `claim_programme_import_proposal`; and
- `discard_programme_import`.

| Operation | Required decision |
| --- | --- |
| Stage and organizer preview | Active verified person, coherent exact edition, exact current Department, adapter pin, `applications.import_programme`, and open private-planning writes. |
| Commit a call | Every import gate plus an independent successful `applications.manage_programme_calls` decision for the same current Department; repeat both decisions under locks. |
| Lead-self preview | Existing exact-self Programme view and edit authority plus import/self adapter pins; re-resolve the staged exact email and require its active verified account to be the actor. Open planning writes are not required, but staging must remain unexpired. |
| Lead claim | Repeat the exact-self gates under lock, require a fresh adopted digest, an active referenced call, and open private-planning writes. |
| Continuity disposal | Active verified person, coherent exact edition, adapter pin, and `applications.dispose_programme_import`; do not require a current Department or open planning writes. |

Every expiry, freshness, and retained-evidence timestamp decision uses the
timezone-aware server clock. Callers cannot select command time. The explicit
`now` seam exists only for deterministic tests and is accepted only when both
`MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_CLOCK` is enabled and the
connected database name begins with `test_`; either condition alone fails
closed. The retention-provider substitution uses its own equivalent two-factor
test guard and does not authorize clock substitution.

Expiry blocks every preview or apply path and never blocks authorized disposal.
An absent adapter pin, unsupported profile, unavailable retention provider,
foreign scope, inactive identity, stale item, unavailable dependency, or denied
decision fails closed without disclosing source or identity facts.

### Persist exactly seven Applications-owned record types

Every relation uses an application-generated UUID primary key, application-set
timestamps, exact organization and edition foreign keys, `PROTECT` references,
and no database identity, sequence, or database-generated default. Binary and
digest fields below are private operational evidence.

| Model | Exact owned fields beyond UUID/timestamps | Required constraints and indexes |
| --- | --- | --- |
| `ProgrammeImportBatch` | `organization`, `edition`, `owner_department`, `source_system` (80), `schema_version` (exactly 1), `source_digest` (64), `item_count` (1–1,000), `retention_policy_code` (120), `expires_at`, `state`, `aggregate_version`, `staged_by`, nullable `discarded_by`, nullable `discarded_at`, and `discard_reason` (500) | `staged` is version 1 with no discard evidence; `discarded` is version 2 with actor, time, and nonblank reason. Index exact scope/owner/state and state/expiry. |
| `ProgrammeImportItem` | `batch`, `organization`, `edition`, one-based `sequence`, `kind`, `source_key` (200), `source_digest` (64), nullable binary `canonical_payload`, positive `payload_size_bytes`, `dependency_source_system` (80), `dependency_source_key` (200), `state`, and `aggregate_version` | Unique `(batch, sequence)` and `(batch, kind, source_key)`. A call has blank dependency fields; a proposal has both. `staged` is version 1 with payload; `applied` or `discarded` is version 2 with payload null. Index exact scope/batch/state/sequence and scope/kind/source key. |
| `ProgrammeImportPreviewRevision` | `batch`, `organization`, `edition`, positive `revision_number`, `source_batch_version` (exactly 1), `preview_digest` (64), `item_count` (1–1,000), and `actor` | Immutable; unique `(batch, revision_number)`; revisions are contiguous and bind the complete item set. Index scope/batch/revision. |
| `ProgrammeImportPreviewItemResult` | `preview`, `item`, `organization`, `edition`, positive `item_version`, `status`, `action`, `dependency_state`, optional `dependency_digest` (64), optional `dependency_version`, JSON arrays `safe_field_keys` and `reason_codes`, and `result_digest` (64) | Immutable and unique `(preview, item)`. `none`/`missing` dependencies have no digest/version; `draft`/`active`/`retired` have both. JSON values are closed, bounded arrays of registered strings. Index scope/preview/status. |
| `ProgrammeImportSourceBinding` | `organization`, `edition`, `source_system` (80), `kind`, `source_key` (200), `source_digest` (64), one-to-one `item`, nullable one-to-one `call`, nullable one-to-one `proposal`, and `created_by` | Immutable; unique `(organization, edition, source_system, kind, source_key)`; exactly one target matches kind and exact scope. Index scope/kind/creation time. |
| `ProgrammeImportAppliedCommand` | `organization`, `edition`, `binding`, `import_receipt`, positive one-based `sequence`, and one-to-one `programme_receipt` | Immutable; unique `(import_receipt, sequence)` and one use of each nested receipt; links one contiguous, exact-scope command chain. Index scope/binding/sequence. |
| `ProgrammeImportCommandReceipt` | `organization`, `edition`, `actor`, `aggregate_kind`, `action`, `retry_key`, private `request_digest` (64), normalized administrative `reason` (500), `correlation_id`, `source_channel` (32), `batch`, optional `item`, optional `preview_revision`, optional `preview_item_result`, optional `source_binding`, optional `adopted_preview_digest` (64), `result_kind`, `expected_version`, `resulting_version`, and immutable `applied_command_count` | Immutable; unique `(edition, actor, retry_key)` across its own table plus cross-table collision guards; unique batch/item aggregate result versions; resulting version is expected plus one; exact action/reference/result matrix. Non-apply receipts store zero nested commands, call apply stores exactly one, and proposal apply stores one through 1,001. Index scope/action/creation time. |

Physical index names are respectively
`app_prg_imp_batch_scope_idx`, `app_prg_imp_batch_expiry_idx`,
`app_prg_imp_item_scope_idx`, `app_prg_imp_item_source_idx`,
`app_prg_imp_preview_scope_idx`, `app_prg_imp_result_scope_idx`,
`app_prg_imp_binding_scope_idx`, `app_prg_imp_applied_scope_idx`, and
`app_prg_imp_command_scope_idx`. Readiness later fingerprints their complete
canonical definitions rather than trusting names alone.

The closed catalogs are:

| Catalog | Values |
| --- | --- |
| Batch state | `staged`, `discarded` |
| Item kind | `call`, `proposal` |
| Item state | `staged`, `applied`, `discarded` |
| Preview status | `ready`, `blocked`, `no_op`, `conflict` |
| Preview action | `commit_call`, `claim_proposal`, `none` |
| Dependency state | `none`, `missing`, `draft`, `active`, `retired` |
| Receipt aggregate kind | `batch`, `preview`, `item` |
| Receipt action | `batch_staged`, `batch_previewed`, `call_committed`, `proposal_claimed`, `batch_discarded` |
| Receipt result kind | `batch`, `preview`, `call_binding`, `proposal_binding`, `discard` |

Preview arrays are unique and stored in canonical catalog order. Safe field
keys are exactly `configuration`, `definition`, `answers`,
`lead_action_required`, and `selection`. Reason codes are exactly
`source_already_applied`, `source_digest_conflict`,
`definition_code_conflict`, `call_dependency_unavailable`,
`call_dependency_not_active`, and `proposal_mapping_invalid`.

The only mutable state transitions are:

```text
batch: absent -> staged(v1) -> discarded(v2)

item:  absent -> staged(v1) -> applied(v2)
                            \-> discarded(v2)
```

Applying one item does not advance its siblings or the batch. Batch
partially-applied, fully-applied, and expired states are derived projections,
not persisted lifecycle values. Preview revisions, preview results, source
bindings, applied-command links, and receipts are append-only.

### Make preview evidence complete but disclosure-minimized

Organizer preview creates one immutable batch revision and one result for every
exact item version and digest. Its envelope may return the opaque batch,
revision, and receipt identifiers, revision number, and replay flag. Each
sanitized item may return only its opaque immutable preview-result identifier,
opaque item identifier and version, kind and bounded ordinal, safe registered
field keys, fixed reason codes, bounded counts, readiness/action, and dependency
state. `commit_programme_import_call` must adopt that exact preview-result
identifier together with the item identifier and expected item version. The
preview never returns the lead email, identity-match state, Account or Person
identifiers, answers, contributor profile, consent, payload, source key, or any
stored digest.

A proposal in the same package may reference a call item. Until the permanent
source binding exists and the referenced call is independently active, only
that proposal result reports a safe dependency state. A dependency change
invalidates only that proposal item's preview; it does not stale an unrelated
sibling.

Lead-self preview is an audited protected query, not a durable identity-match
record. It resolves the active verified person from the exact staged login
email on every fresh preview and fresh claim, proves that person is the actor,
and repeats view/edit authority and identity checks under locks immediately
before release. Exact retained-receipt replay rechecks current adoption-scoped
retry authority and returns only the minimized historical result.
It accepts the trusted request correlation ID and source channel before
releasing only the caller-supplied opaque item identifier, current item
version, selection values, and each normalized
`question_key`/`field_type`/`value` answer. Its returned `adoption_digest`
binds the actor, exact source identity, item digest/version/schema, dependency
binding/digest/version, selection, and normalized answers. Claim supplies that
value as `adopted_preview_digest`; under locks the service re-resolves identity
and dependency, recomputes the fresh digest, and compares it in constant time.
No matched Account/Person foreign key or reusable match flag is stored, so no
Identity migration is introduced.

### Apply only through ADR 0082 commands

Call commit invokes exactly one `create_programme_call` command and links its
one `call_created` receipt. Proposal claim is one outer transaction containing
one `start_programme_proposal` command followed by
`append_programme_proposal_answer` in definition order for every imported
answer. Its linked receipt chain begins with `proposal_started`, continues with
contiguous `proposal_answer_revised` versions, and contains no other action.

Every nested retry UUID is the raw UUID representation of MD5, used only for
deterministic naming, over this ASCII string:

```text
maru:applications:programme-import:nested:v1:<lower-outer-retry-uuid>:<lower-item-uuid>:<one-based-sequence>:<programme-action>
```

Call apply links `call_created` at sequence 1. Proposal apply links
`proposal_started` at sequence 1, followed by `proposal_answer_revised` in
definition order from sequence 2. Definition order is the strict tuple
`(section.position, question.position, question.id)`, and every answer receipt
must name a question owned by the target call's exact definition. The outer
receipt freezes `applied_command_count`: one for call apply and the complete
start-plus-answer count for proposal apply. Deferred integrity requires both
the linked-row count and terminal sequence to equal that immutable value, so a
later legitimate proposal answer revision cannot be attached retroactively to
the completed import chain. Nested receipts have the same actor, organization,
edition, correlation ID, and normalized administrative rationale as the outer
receipt. The dedicated import receipt retains its private request digest solely
for retry equality and collision enforcement. Administrative rationale and
stored request/source/item/dependency/result digests remain absent from preview
output. The freshly computed `adoption_digest` is the sole digest released,
only to the exact lead as private claim material. Every digest and rationale
remains absent from audit metadata, event/outbox payloads, logs, metrics,
health, and errors.

Every protected service has an outer failure-audit boundary outside its atomic
work. Validation, denial, stale, dependency, and nested-command failures roll
back all success evidence, then retain exactly one best-effort minimized outcome
with trusted request correlation/source when valid, no target identifier, and
no source, identity, answer, digest, rationale, or database detail. A nested
Programme failure audit inside the outer transaction rolls back; the outer
import audit is the durable failure outcome.
Unexpected dependency, nested-command, database, or evidence exceptions cross
the service boundary only as
`applications_programme_import_operation_failed`; their implementation detail
never becomes an error message or projection.

The generic Applications receipt, ADR 0082 Programme receipt, and import
receipt share one edition/actor/retry namespace. Before looking in any receipt
table, all three guards acquire the same transaction advisory lock derived
from:

```text
maru:applications:retry:<lower-edition-uuid>:<lower-actor-uuid>:<lower-retry-uuid>
```

A collision with a different receipt family is a stable conflict rather than a
second mutation.

An import apply derives and acquires its complete ordered nested retry-key set
before locking its batch, edition, Department, item, or Programme target. The
order is outer import retry key, then nested sequence order, then row locks.
This prevents a direct Programme command that already owns a nested retry key
from forming a nested-retry/edition deadlock with the import transaction.

The import writer uses a dedicated transaction-local
`programme_import_writer_boundary.py` latch. Each nested ADR 0082 command keeps
its own writer latch and database evidence checks. Failure at any stage rolls
back the item state, call/proposal and answer revisions, source binding, nested
and outer receipts, applied-command links, audit, event, and outbox evidence.
Discard never compensating-deletes an applied call or proposal.

### Bind source identity permanently

The identity tuple is exact organization, edition, source system, item kind,
and case-sensitive source key. The first successful apply permanently binds it
to the exact applied item digest and one typed call or proposal target.

The binding cannot cross an apparently compatible target. Its source system
must equal the parent batch source system. A call binding must point to a call
owned by the batch's exact Department. A proposal item must name a call
dependency in that same source system, and its proposal binding must point to
the exact call resolved by that dependency; the proposal submission and call
must also share the exact definition. These checks are database-enforced as
well as service-enforced.

- the same identity and same applied digest is a safe no-op forever;
- the same identity and a different digest is a stable conflict forever;
- later legitimate changes to the call or proposal do not change either
  result; and
- no fuzzy source, email, person, call, or proposal matching is permitted.

A same-digest replay is permanently classified `no_op` by organizer preview.
It creates no second target and no nested ADR 0082 command, and there is no
separate no-op apply command. The newly staged duplicate item therefore remains
staged with its private payload until explicit authorized
`discard_programme_import`; after expiry even its preview is unavailable, while
disposal remains available. A different digest is a permanent `conflict` and
changes no state.

### Separate expiry from disposal

Expiry is calculated once by a versioned, reviewed, server-side retention
policy provider. The batch stores the exact policy code and derived
`expires_at`; the source document cannot choose either. The default provider
fails closed when no reviewed policy is configured. There is no automatic
cleanup job in this decision.

| Event | Batch evidence | Affected item payload | Retained evidence |
| --- | --- | --- | --- |
| Stage succeeds | `staged`, version 1 | Canonical private bytes present for every item | Document/item digest, size, scope, source identity, policy, expiry, stage actor, receipt/audit/event/outbox evidence. Raw document bytes are not retained. |
| Organizer or lead preview | Batch/item state unchanged | Unchanged | Immutable organizer preview only; lead identity match remains transient and only its sensitive read is audited. |
| Call commit or proposal claim | Batch remains `staged` | Applied item becomes null in the same transaction; siblings are unchanged | Permanent source binding, minimized outer and nested receipts, ordered command links, audit/event/outbox evidence, and created domain records. |
| Expiry passes | No state mutation | Unchanged until explicit disposal | Expiry blocks preview/apply but not continuity disposal. |
| Authorized discard | Batch becomes `discarded`, version 2 | Every remaining staged item becomes `discarded`, version 2, and null; already-applied items stay null | Digests, sizes, minimized preview/binding/receipt evidence, discard actor/time/reason, and applied domain records. |

The batch reason and receipt rationale are restricted administrative evidence;
they never copy source content. Disposal remains available after expiry,
private-planning closure, and owner-Department retirement through exact Edition
continuity authority.

### Install schema, policy, guards, and readiness in dependency order

The migration graph is:

```text
applications.0006
  -> applications.0007_programme_import_persistence

applications.0007 + workforce.0016
  -> workforce.0017_programme_import_department_fk_contract

authorization.0021
  -> authorization.0022_programme_import_capabilities

applications.0007 + authorization.0022
  -> applications.0008_programme_import_integrity_guards
  -> applications.0009_programme_import_populated_downgrade_fence
```

Names may be rebased only when another reviewed child occupies a leaf; the
dependency and reversal ordering remains the same. Applications integrity does
not depend on Workforce `0017`; whole-deployment readiness pins that successor
independently.

Applications `0008` must install exact-tenant and foreign-key coherence,
closed catalogs, version steps, immutable evidence, contiguous preview and
nested-command history, immutable terminal command counts, strict definition-
order answer lineage, source-system/call/Department binding coherence, source
uniqueness, shared three-table retry collision, writer-latch, receipt-backed
mutation, and truncate-refusal guards. All seven relations receive deferred
exact-contract triggers and truncate guards. The functions use a trusted
search path, remain owner-only, and grant no `PUBLIC` or runtime execution.

Workforce `0017` adds exactly
`applications_programmeimportbatch.owner_department_id` to the recognized
Department foreign-key catalog. It protects deletion/reference integrity but
does not implement issue #64's retirement preflight, reassignment, disposal, or
recovery. Authorization `0022` adds only the two dormant capabilities and its
ordinary populated grant/bundle downgrade fence.

The production runtime role receives `SELECT` only on all seven relations and
no import-function execution. Applications readiness advances to the exact
integrity-source and terminal-fence migrations and fingerprints the complete
generated catalog for all 33 managed `applications_*` relations, including
every column/collation, constraint, index, trigger, owner-only function,
relation flag, owner, and ACL. Fresh PostgreSQL 17 generated 442 columns and
collations, 367 constraints, 263 indexes, 87 triggers, and 22 owner-only
functions. The constraint digest is
`c20c6cd829ddc9045d6e07bfcfb39cda7e75a21a7070f4f0ad3b3b2e96aa3ecb` and the
index digest is
`501634da18934c04c6234533fac4f01987fb5ddcc3db3a14f76d5c837097425f`.
These generated values are exact-head release evidence; an older schema
snapshot is not acceptance evidence.

Reversing Applications `0008` restores the exact `0005` consolidated guard
catalog. Reversing `0009` or `0007` takes `ACCESS EXCLUSIVE` locks over all
seven relations and refuses when any row exists, including discarded or
otherwise payload-cleared evidence. A populated deployment fixes forward or
restores Applications, Authorization, Workforce, Audit, Effects event/outbox,
and migration history from one mutually consistent whole-database point. It
never deletes rows, disables triggers, fabricates receipts, edits the migration
recorder, or grants runtime write/function authority.

### Keep Department retirement as a mandatory continuation

An unresolved staged item or batch remains owned by its exact Department even
after expiry; expiry is not disposal. Issue #64 must make Workforce retirement
call an Applications-owned, disclosure-safe preflight and require authorized
reassignment or disposal before retirement. Applied or discarded import
evidence must not block retirement. Workforce must never receive source keys,
item counts, emails, answers, payloads, identity state, or digests through that
seam.

The dormant kernel may merge before #64, but no adapter/profile activation may
occur until retirement preflight, refusal, authorized disposal/reassignment,
concurrent serialization, and governed orphan recovery are implemented and
accepted.

## Consequences

- A convention can prepare deterministic incumbent data without creating a
  call, proposal, identity relationship, invitation, or unrelated module row.
- Organizer preview is operationally useful without exposing proposal content
  or identity matching, and the lead remains the only person who can adopt
  their private proposal.
- Item-local versions allow partial application without staling siblings, but
  every consumer must distinguish batch state from derived application/expiry
  projections.
- Permanent source binding gives retries an understandable result after later
  domain edits, at the cost of requiring a new source key for materially new
  source identity.
- Immediate per-item payload clearing and separately authorized disposal reduce
  exposure, but production activation still requires reviewed retention,
  backup aging, subject-rights, recovery, and Department-retirement procedures.
- Installing the schema and catalogs does not make Programme Operations usable
  or production-ready.

## Alternatives considered

### Import directly into Applications tables

Rejected because it would bypass ADR 0082 validation, authorship, versions,
receipts, audit, events, and database writer boundaries.

### Let an organizer import proposal profiles and consent

Rejected because proposed-public identity and consent belong to the exact
contributor. Importing them would manufacture another person's assertion.

### Persist an email-to-account match during staging

Rejected because identity may change between preview and claim, the match
would disclose a platform relationship, and no reusable Identity state is
needed. Exact email resolution is repeated for every self disclosure/action.

### Treat expiry as automatic deletion or disposal

Rejected because time passage is not attributable disposal and could erase
evidence while a continuity actor is unavailable. Expiry blocks use; explicit
authorized disposal clears payload.

### Add CSV/XLSX heuristics or a generic import platform

Rejected because implicit coercion and fuzzy mapping make preview and replay
non-deterministic. Larger or differently shaped exports use separately
reviewed adapters and deterministic packages.

### Compensating-delete created records when a batch is discarded

Rejected because a created call or proposal is canonical governed domain state
with its own history. Discard affects only remaining temporary staging data.

## Requirements affected

- **PRG-001, PRG-002, and PRG-010:** Calls and lead-owned proposals may enter
  staging only through one closed preview-first adapter and protected commands.
- **PRG-006 and PRG-009:** Private imported answers and proposed-public choices
  remain Applications-owned; identity, consent, sealing, review, Programme,
  and publication boundaries do not collapse.
- **IDN-014:** Import does not create an account or persist an identity match;
  lead-self authority is re-resolved for each disclosure and claim.
- **AUD-001, AUD-003, and AUD-005:** Successful mutations retain atomic,
  minimized, attributable outer and nested evidence; failed protected attempts
  retain one durable minimized outcome after rollback; disclosure channels omit
  private input and digests.
- **PRI-001:** Versioned policy-derived expiry, immediate apply clearing, and
  explicit continuity disposal define the temporary payload lifecycle.
- **NFR-013:** The dormant adapter creates no Registration, Participation,
  payment, attendance, Workforce assignment, Programme item, scheduling,
  publication, or current-profile side effect.
