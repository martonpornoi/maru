# Applications Programme import migration and recovery

Status: Implemented dormant-schema procedure; protected-PR and deployment
acceptance remain separate, with no production activation or personal-data
approval
Last updated: 2026-09-01

This runbook covers PRG-010 and ADR 0083's preview-first Programme call and
proposal import staging. It does not activate
`applications.import.programme_call_proposal@1` or
`programme_operations@1`, mount an import surface, configure a production
retention period, or authorize production personal data. Use synthetic data
until retention, deployment, recovery, continuity-owner, and protected
pull-request acceptance are complete.

## Boundary

The installed migration graph is:

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

Applications integrity deliberately does not depend on Workforce `0017`;
whole-deployment readiness checks that independent successor.

The additive Applications schema contains exactly seven UUID-keyed relations:

- `applications_programmeimportbatch`;
- `applications_programmeimportitem`;
- `applications_programmeimportpreviewrevision`;
- `applications_programmeimportpreviewitemresult`;
- `applications_programmeimportsourcebinding`;
- `applications_programmeimportappliedcommand`; and
- `applications_programmeimportcommandreceipt`.

They use no database identity, sequence, or database-generated default.
Workforce `0017` recognizes only
`applications_programmeimportbatch.owner_department_id` in the exact protected
Department-reference catalog. Authorization `0022` declares the dormant
delegable Department-scoped import and delegable Edition-scoped disposal
capabilities and retains its separate populated grant/bundle downgrade fence.
Disposal authority does not grant staged-content read authority.

No migration creates an import batch, item, preview, source binding, call,
proposal, answer, identity match, grant, role, profile selection, event, outbox
row, Programme item, Shift, schedule, or publication. Both current exact
adoption profiles remain unchanged.

## Before upgrade

1. Keep every import route, API, UI, worker, job, schedule, and profile member
   absent. Schema installation is not writer activation.
2. Stop web and worker processes that can write Applications, Authorization,
   or Workforce state.
3. Take one complete PostgreSQL backup and retain the exact application
   revision, migration plan, runtime-role provisioning artifact, retention
   configuration, and deployment settings.
4. Run `python src/manage.py showmigrations applications authorization workforce`
   and verify the expected source leaves. Never infer compatibility from a
   migration number alone and never fake recorder rows.
5. Run `python src/manage.py migrate --plan`. Confirm the independent
   Applications, Authorization, and Workforce branches converge in the order
   above and that no unrelated migration or data operation appears.
6. Verify that the reviewed retention-policy provider is either deliberately
   unconfigured and fail-closed or supplies an exact versioned synthetic policy
   for rehearsal. A source package can never provide its own policy or expiry.

## Retention policy configuration

The default provider reads exactly
`MARU_APPLICATIONS_PROGRAMME_IMPORT_RETENTION_POLICY_JSON`. An absent or empty
setting is intentional fail-closed behavior: staging returns the stable generic
operation-failed boundary and creates no batch or item. Configuring this setting
does not pin the dormant adapter, create a route, or authorize production data.

Use one reviewed, non-secret JSON object with exactly these four keys; this is a
synthetic example, not an approval record:

```json
{"approved_at":"2026-08-31T12:00:00Z","approved_by_reference":"privacy-review.2026-09","period_seconds":604800,"policy_code":"applications.programme-import-staging.v1"}
```

The UTF-8 setting is limited to 4,096 bytes. Duplicate, missing, or additional
members fail closed. `policy_code` and `approved_by_reference` must each match
`^[a-z][a-z0-9_.:-]{2,119}$`. `period_seconds` must be an exact JSON integer,
not a boolean, from 1 through 31,536,000 inclusive. `approved_at` must be a
valid timezone-aware instant no later than the authoritative staging instant.
Malformed Unicode scalar content, invalid JSON, invalid grammar, naive/future
approval, and out-of-range lifetime all produce the same sanitized
configuration failure.

Do not place credentials, personal data, source identifiers, rationale, or
approval narrative in this setting. Retain the actual approval record and
change review in the deployment system; the setting stores only its stable
reference. Treat a policy change as reviewed deployment configuration and
rehearse expiry/disposal with synthetic data before adapter activation.

Production commands always use this configured default provider. The injectable
provider seam is accepted only when both the explicit test setting is enabled
and Django is connected to an auto-created `test_` database; either fact alone
fails closed.

The timezone-aware server clock is independently authoritative for staging,
expiry, freshness, disposal, and retained command times. Production callers
cannot supply `now`. The explicit clock seam is accepted only when both
`MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_CLOCK` is enabled and Django is
connected to a database whose name begins with `test_`; either condition alone
fails closed. This clock guard is separate from the injectable retention-
provider guard, and enabling one does not enable the other.

## Upgrade procedure

1. Apply the reviewed migration plan with the migration-owner credential.
2. Confirm the seven relations are empty and have their exact UUID, scope,
   foreign-key, state, version, payload, digest, evidence, constraint, and index
   definitions from ADR 0083.
3. Confirm Applications `0008` installs the consolidated old-plus-new guard
   catalog. Required protections include exact tenant/edition coherence, closed
   state/action catalogs, one-step versions, contiguous preview and nested
   receipt sequences, immutable terminal nested-command counts, strict
   definition-order answer lineage, source-system/call/Department binding
   coherence, append-only evidence, permanent source uniqueness, receipt-backed
   state changes, writer latches, three-table retry collision, and truncate
   refusal.
4. Confirm all seven relations have their exact deferred contract trigger and
   truncate guard. Every import function must use the reviewed trusted search
   path, be owned by the migration owner, and grant no direct `EXECUTE` to
   `PUBLIC` or the runtime role.
5. Confirm the dedicated import writer latch is separate from the ADR 0082
   Programme writer latch. Nested commands must still pass their own latch and
   receipt-backed guards.
6. Reconcile the least-privilege runtime role from
   `postgresql-runtime-role-provisioning.sql.example`. It receives `SELECT`
   only on all seven relations and no insert, update, delete, truncate,
   sequence, ownership, trigger-control, or function-execute authority.
7. Run Django deployment checks and the public readiness probe. Applications
   must require integrity source `0008`, terminal fence `0009`, and the exact
   33-relation all-schema catalog. Authorization must recognize the two dormant
   capabilities, and Workforce must recognize the one batch owner-Department
   foreign key.
8. Verify the exact current-profile fingerprints remain their accepted values
   and no current profile pins the adapter, import/disposal capability, event,
   destination, handler, or writer.
9. Resume ordinary services only after the complete release's normal checks
   pass. Do not enable import through a feature flag or temporary grant.

The frozen readiness catalog generated from fresh PostgreSQL 17 contains 33
relations, 442 columns/collations, 367 constraints, 263 indexes, 87 triggers,
and 22 owner-only functions. Its constraint SHA-256 is
`c20c6cd829ddc9045d6e07bfcfb39cda7e75a21a7070f4f0ad3b3b2e96aa3ecb`;
its index SHA-256 is
`501634da18934c04c6234533fac4f01987fb5ddcc3db3a14f76d5c837097425f`.
A public health response returns only the stable Applications dependency
category and never a relation, function, source system, source key, email,
payload, digest, rationale, or database definition.

## Runtime retry and writer proof

Generic Applications, ADR 0082 Programme, and Programme import receipts share
one logical `(edition, actor, retry_key)` namespace. Before reading any of the
three receipt tables, every database guard acquires the same transaction
advisory lock derived from:

```text
maru:applications:retry:<lower-edition-uuid>:<lower-actor-uuid>:<lower-retry-uuid>
```

The exact same intent replays its retained result. A changed intent or a key
already used by another receipt family is a stable conflict. Never recover a
collision by deleting a receipt or changing a key in stored evidence.

Import apply acquires the outer import retry advisory, then all deterministic
nested retry advisories in sequence, and only then batch/edition/Department/item
row locks. Preserve this order. A direct Programme command may already own one
nested retry key; taking row locks first recreates an edition/advisory deadlock.

Applying a call links exactly one nested `call_created` receipt. Applying a
proposal links `proposal_started` and then definition-order
`proposal_answer_revised` receipts with contiguous aggregate versions. Nested
retry UUIDs are the raw UUID form of MD5, used for deterministic naming only,
over:

```text
maru:applications:programme-import:nested:v1:<lower-outer-retry-uuid>:<lower-item-uuid>:<one-based-sequence>:<programme-action>
```

`call_created` is sequence 1. `proposal_started` is sequence 1 and answer
revisions begin at sequence 2. Answer links must belong to the target call's
exact definition and increase in the strict tuple
`(section.position, question.position, question.id)`. Actor, scope,
correlation, and normalized administrative rationale must agree across the
chain.

The outer receipt freezes immutable `applied_command_count`: exactly one for a
call, and proposal start plus every imported answer for a proposal, with a
maximum of 1,001. Deferred checks require both the number of linked commands
and the terminal sequence to equal that stored value. Do not derive completion
from the target's later current aggregate version: a legitimate later proposal
answer must never extend an already completed import chain.

The permanent source binding is equally exact. Its source system matches the
parent batch source system; a call target belongs to the batch's owner
Department; and a proposal target uses the exact call resolved from its
same-source-system dependency, with the proposal submission and call sharing
one definition. Never recover a mismatch by repointing the immutable binding.

The import receipt retains a private request digest only for replay/collision
equality. Source, item, preview, dependency, result, and adopted-preview digests
remain in their explicitly classified database evidence. A fresh
`adoption_digest` is the only digest returned, only to the exact lead as private
claim material; claim supplies it as `adopted_preview_digest`. No stored
request/source/item/dependency/result digest or administrative rationale is
copied into organizer/lead projections, and no digest or rationale is copied
into audit metadata, event/outbox payload, logs, metrics, health, or errors.

## Payload lifecycle and disposal

Stage retains canonical private bytes per item, never the raw root document.
The item stores the exact size and digest and the application boundary verifies
both before use. A successful apply changes only that item from staged version
1 to applied version 2 and nulls the payload in the same transaction. Sibling
versions and payloads do not move. A same-digest duplicate is only a permanent
preview no-op and remains staged with payload until explicit disposal.

Expiry is a derived check against the exact configured `expires_at`; it is not
a database transition and does not clear data. It blocks preview and apply.
Authorized `discard_programme_import` remains available after expiry,
private-planning closure, or owner-Department retirement. In one transaction it
changes the batch from staged version 1 to discarded version 2, records the
actor/time/reason, moves every remaining staged item to discarded version 2,
and nulls every remaining payload. Applied items and their created domain
records remain untouched.

There is no automatic cleanup job in ADR 0083. Operators must monitor the
bounded count and oldest age of undisposed expired batches without logging
source systems, keys, emails, answers, payloads, digests, identity state, or
rationales. Production activation requires a reviewed policy, continuity
owner, alert threshold, legal-hold behavior, subject-rights handling, backup
aging, and rehearsed disposal operation.

## Empty reversal

Routine reversal is supported only while all seven import relations are empty.
Discarded, payload-cleared, receipt-only, preview-only, or otherwise minimized
rows still count as populated evidence.

1. Stop all writers and workers and take a new complete backup.
2. Review `migrate --plan`. Reverse Applications `0009` before `0008`.
   `0009` takes `ACCESS EXCLUSIVE` locks across all seven relations and repeats
   the emptiness decision transactionally.
3. Reverse `0008`; its reverse must remove the import functions/triggers and
   restore the exact Applications `0005` consolidated guard catalog, including
   owners and ACLs.
4. Reverse dependent Workforce `0017` before removing Applications `0007`.
   Its reverse restores the exact Workforce `0016` Department-reference
   function. Do not fake it as unapplied.
5. Reverse Authorization `0022` only through its own empty grant/role fence.
   It is not evidence that the Applications relations are empty.
6. Reverse Applications `0007` last. Its final schema operation takes
   `ACCESS EXCLUSIVE` locks over all seven relations and refuses if any row
   appeared after the earlier check.
7. Reconcile runtime ACLs and verify the new application binary is not started
   against the old schema. An old binary must likewise not run against a
   partially reversed schema.

Audit and Effects evidence are not queried to decide whether an Applications
schema reversal is empty. Preserve and assess them from the consistent backup;
a minimized failure audit may exist without a successful import receipt.

## Populated refusal and fix-forward recovery

Any row in any of the seven relations makes the Applications downgrade refuse.
A Programme-import capability grant or role can independently make the
Authorization downgrade refuse. A refused downgrade is successful safety
behavior: it leaves relations, functions, triggers, owners, ACLs, migration
history, private payload, and cross-module evidence intact.

When a downgrade refuses:

- keep writers and workers stopped;
- capture the exact release, migration graph, minimized readiness category,
  and sanitized failure class;
- prefer one reviewed additive fix-forward migration; or
- restore the complete PostgreSQL database from one mutually consistent point,
  including Applications, Authorization, Identity, Workforce, Audit, Effects
  event/outbox, and migration history, then run the matching application
  release.

Never truncate or delete evidence, null payload outside the disposal command,
disable a trigger, set the writer latch manually, grant runtime DML/function
execution, rewrite a source binding or nested receipt, fabricate an identity
match, edit `django_migrations`, or use an owner login to force reversal.

## Department retirement dependency

An unresolved staged batch/item owned by a Department blocks retirement even
after expiry. Applying every item is not required; explicit authorized disposal
may clear the remainder. Applied and discarded evidence does not block
retirement.

Workforce `0017` only teaches the exact foreign-key catalog about the batch
owner. It does not implement retirement preflight, reassignment, disposal, race
serialization, or orphan recovery. Issue #64 must call an Applications-owned,
fail-closed preflight and expose no batch/item count, source identity, email,
answer, payload, digest, or internal identifier. If retirement wins a race,
preview/apply must fail; if apply/reassignment/disposal wins, retirement must
observe the resolved state.

No Programme import/profile activation may occur before #64's retirement and
recovery contract is separately accepted. Do not repair an already-retired
owner with raw DML, a fabricated current grant, temporary function execution,
or a disabled guard.

## Verification checklist

The implementation pull request must provide evidence for:

- fresh install, exact migration dependencies, empty reverse, and reapply on
  PostgreSQL 17;
- all seven populated downgrade-fence cases, including payload-cleared and
  discarded evidence;
- exact 33-relation readiness catalog and negative relation/column/collation/
  constraint/index/function/trigger/owner/ACL tampering;
- runtime `SELECT` proof, `PUBLIC` `SELECT` denial, and runtime/`PUBLIC`
  write, truncate, and function-execute denial;
- exact source same-digest permanent preview no-op whose duplicate payload
  remains staged until disposal, and changed-digest permanent conflict;
- shared generic/Programme/import retry collisions and concurrent races;
- item-local apply, dependency staleness, complete nested rollback, and
  strict definition-order command lineage;
- immutable applied-command count and terminal sequence, including refusal of
  reversed answer order and post-import chain extension after a legitimate
  later proposal revision;
- source binding refusal for a foreign source system, another Department's
  call, an alternate call dependency, or a proposal/call definition mismatch;
- exactly one minimized, source-accurate outer failure audit after rollback,
  including denied lead preview and a nested command failure, with no target or
  private import value;
- per-item apply clearing, partial and complete disposal, expiry, planning
  closure, and retired-Department continuity;
- no stored identity match and identity change between self preview and claim;
- unchanged current-profile fingerprints and no route/API/UI/admin/worker/job/
  handler/schedule/system-actor activation; and
- server-clock authority plus independent two-factor refusal for explicit test
  clock and injectable retention-provider seams.

These checks are the implementation acceptance list. Record completed local and
hosted evidence in the issue checkpoint; do not infer an unrun result from this
runbook. A mutually consistent backup/restore rehearsal remains a separate
deployment-activation gate; issue #66 documents the recovery boundary but does
not claim that infrastructure rehearsal as repository-test evidence.
