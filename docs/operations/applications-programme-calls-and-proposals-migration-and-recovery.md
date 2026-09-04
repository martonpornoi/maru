# Applications Programme calls and proposals migration and recovery

Status: Dormant schema procedure; no production activation or personal-data
approval
Last updated: 2026-09-02

This runbook covers the Applications-owned Programme-call and collaborative-
proposal schema plus ADR 0084's ownership-continuity successors. It does not activate
`programme_operations@1`, mount a writer, approve production personal data, or
authorize manual proposal creation. Use synthetic data only until the separate
retention, deployment, recovery, and owner-acceptance gates are complete.

## Boundary

The change is additive:

- `applications.0004_programme_calls_and_proposals` adds empty call, proposal,
  collaborator, selection, profile, sealed-snapshot, response, and dedicated
  receipt relations;
- `workforce.0016_programme_call_department_fk_contract` recognizes the exact
  protected Programme-call owner reference in Workforce's Department-deletion
  catalog without adding the issue #64 retirement workflow;
- `applications.0005_programme_integrity_guards` is the terminal consolidated
  old-plus-new Applications function/trigger catalog required by readiness;
  and
- `applications.0006_programme_populated_downgrade_fence` refuses an unsafe
  downgrade before protected Programme-call or proposal evidence can be
  removed;
- `authorization.0023_programme_department_ownership_recovery` declares one
  unpinned, nondelegable, break-glass exact-Edition recovery capability;
- `applications.0010_programme_department_ownership_persistence`,
  `0011_programme_department_ownership_integrity`, and
  `0012_programme_department_ownership_downgrade_fence` add receipt-backed
  source/destination ownership transitions, exact chain/database guards, and
  the post-cutover reversal fence; and
- `workforce.0018_programme_department_ownership_contract` recognizes all four
  transition-receipt Department references and installs the reciprocal
  retirement backstop, bringing the exact catalog to 19 references.

Applications `0004` depends on Workforce only at
`0006_edition_structure_schema`, the earliest complete Department shape it
uses. It does not depend on the later Workforce or Registration tail. The
separate Workforce `0016` successor depends on Applications `0004` and
Workforce `0015`, so it can recognize the new owner-Department foreign key
without coupling the Applications schema to that later graph.

Applications `0010` depends on the import terminal `0009`; `0011` also depends
on Authorization `0023`; `0012` fences the resulting evidence. Workforce
`0018` follows Applications `0012` and Workforce `0017`. Follow the migration
plan rather than manually reordering these nodes.

Do not infer a compatible range by migration number alone. Authorization's
paired additive migration adds the closed Programme-call/proposal capability
vocabulary and its own populated downgrade fence without creating authority.

The change creates no edition profile, definition, submission, answer,
collaborator, receipt, grant, role, event, outbox row, target record, Programme
item, host, schedule, Shift, or publication. Both current exact-profile
fingerprints must remain unchanged.

## Upgrade procedure

1. Stop all web and worker writers that use the Applications schema.
2. Back up the complete PostgreSQL database and retain the exact application
   revision, migration plan, and role-provisioning artifact.
3. Run `python src/manage.py showmigrations applications authorization identity workforce`
   and verify the expected source state. Do not fake migration-recorder rows.
4. Run `python src/manage.py migrate --plan`, review the exact Applications,
   Authorization, Identity, and Workforce steps, then apply the normal migration
   command with the migration-owner credential.
5. Reconcile the least-privilege runtime role from
   `postgresql-runtime-role-provisioning.sql.example`. Every new
   `applications_programme*` relation must be `SELECT`-only for runtime and all
   Programme integrity functions owner-only.
6. Run Django deployment checks and the public readiness probe. The
   Applications Programme dependency must validate the exact relation,
   constraint, index, function, trigger, owner, and ACL fingerprint.
   Workforce readiness must recognize the exact 19-reference Department
   catalog, including call/import owners and both receipt families' source and
   destination references.
7. Verify that `full_convention@1` and `workforce_only@1` still have their
   previously accepted literal fingerprints and that no Programme member is
   pinned by either manifest.
8. Resume ordinary services only after the complete release's normal checks
   pass. Do not enable a route, job, writer, grant, or handler as part of this
   schema procedure.

Readiness reports one minimized unavailable dependency on drift. Never log the
object name, SQL definition, call, proposal, person, answer, invitation, or
profile value to make a public health response more diagnostic.

## Empty reversal

Routine Applications reversal is supported only while every Programme-call or
proposal relation and dedicated receipt is empty, no generic definition uses
the reserved target, no Programme-versioned generic answer remains, and no
reserved Programme target record exists. Stop writers and workers, take a
backup, and use the normal migration owner. The reverse path takes same-
transaction `ACCESS EXCLUSIVE` locks over that exact Applications-owned set and
repeats its emptiness preflight immediately before protected objects are
removed.

Authorization's paired migration has its own grant/role downgrade fence and
must be planned and reversed separately. The Applications fence deliberately
does not query Audit or Effects tables. Preserve and assess those cross-module
records from the consistent backup even when the Applications-owned set is
empty; a minimized failure audit may legitimately exist without a successful
Programme aggregate or receipt.

Before targeting Applications `0004` for reversal, reverse its dependent
Identity `0020_programme_proposal_person_guard` and Workforce
`0016_programme_call_department_fk_contract` migrations, as well as the normal
Applications descendants shown by the migration plan. Do not fake those
dependent migrations as unapplied. Reversing Workforce `0016` while the
Programme-call table still exists deliberately restores the prior exact
Department-reference function. Its catalog no longer matches the live foreign
key, so Department deletion fails closed until Applications `0004` is removed
or Workforce `0016` is reapplied.

On a current ownership-continuity schema, reverse Workforce `0018` before
Applications `0012` through `0010`; reverse Authorization `0023` only after its
own populated grant/role-bundle fence is clear. Applications `0012` refuses
reversal when any post-cutover source/destination ownership evidence exists.
An empty reverse restores the exact prior integrity catalog and Workforce's
15-reference Department helper; it never deletes or rewrites an orphan.

After an empty reversal, reconcile runtime ACLs and verify that the Applications
Programme readiness dependency fails in the expected old-release shape. Do not
run a new application binary against the old schema or an old binary against a
partially reversed schema.

## Populated refusal and recovery

Any durable Programme definition, call, proposal, collaborator transition,
selection revision, contributor profile revision, sealed revision or snapshot
link, response, dedicated receipt, Programme-versioned generic answer, or
reserved target evidence makes the Applications downgrade refuse. A durable
Programme capability grant or role makes the separate Authorization downgrade
refuse. Audit and Effects rows do not independently trip either fence; a
successful Programme event is normally coupled to a fenced receipt, while a
minimized failure audit may be the only retained record. Successful reversal
therefore does not authorize deleting cross-module evidence.

An Applications refusal is success for its safety fence: it must leave tables,
triggers, functions, ACLs, migration history, Audit, and Effects evidence
intact.

When reversal refuses:

- keep writers and workers stopped;
- capture the exact release, migration state, minimized readiness result, and
  sanitized failure category;
- fix forward with a reviewed additive migration whenever possible; or
- perform a mutually consistent whole-database restore, explicitly including
  Applications, Authorization, Identity, Workforce, Audit, Effects event/outbox,
  and migration history from one backup point, together with the matching
  application release.

Never delete rows, disable triggers, grant runtime DML/function execution,
truncate evidence, rewrite a seal or response, fabricate an acknowledgement,
clear a target discriminator, or edit `django_migrations` to force rollback.
Recovery must not invent a review, decision, Programme item, host relationship,
schedule, staffing record, or publication.

## Later activation

Preview-first import and Department ownership continuity are now installed as
dormant command boundaries. They do not authorize generic review or target
creation. Structured review and decisions, the accepted Programme adapter,
Programme hosts, Scheduling, staffing, and publication remain separate
children.

A later mounted writer must introduce a reviewed profile member, capability and
relationship policy, exact route/API contract, handler/delivery route where
needed, narrowed DML/function grants, readiness update, migration fence, and
recovery rehearsal. It cannot turn this dormant schema on with a feature flag or
copy the generic Applications receipt privileges.

## Department retirement sequencing

Before a Workforce Department retires, the structure command acquires the
shared exact-edition mutex and calls Applications' public dependency seam.
Call and import probes run independently and return only `clear`, `blocked`, or
`unavailable`; any known block wins, otherwise unavailability fails closed.
No category, count, name, identifier, source key, email, payload, or digest
crosses into Workforce. A refused command changes no structure cursor or
success evidence.

While the source Department is current, reassign each Draft call through
`reassign_programme_call` with exact current call-management authority at both
source and destination, current call version, retry key, and reason. Retire
each Active call through `retire_programme_call`; Active calls cannot move.
Reassignment preserves every imported source binding and appends the exact
source-to-destination receipt needed by the contiguous owner chain. A replay
returns the original receipt without reacquiring the edition mutex or writing
duplicate evidence.

Department retirement blocks discovery and new proposal starts for the owned
call. It does not erase a retained proposal relationship or its immutable
history. Existing leads, live invitees, and accepted collaborators keep only
their lifecycle-permitted self projections and commands, subject to the call
window, call lifecycle, edition write state, current identity, and exact
adoption contract.

For a call orphaned by historical pre-continuity state, use only
`recover_orphaned_programme_call_reassignment` for one exact Draft or
`recover_orphaned_programme_call_retirement` for one exact Active call. Both
require the dormant exact-Edition, nondelegable, break-glass recovery
capability, caller-supplied call and retired-source identifiers, expected
version, retry key, and reason. There is no orphan list or content-read query.
Because no current profile or root activates that capability, a production
operator must use only a separately accepted future recovery ceremony or a
reviewed fix-forward/whole-database restore. Never use raw DML, a temporary
grant, a disabled trigger, a fabricated receipt, or migration-recorder edits.

Use the exact operational decision tables in
[`applications-programme-department-ownership-recovery.md`](applications-programme-department-ownership-recovery.md).

## Verification checklist

- fresh upgrade and empty reverse/reapply;
- exact Applications `0004` dependency shape and dependent Identity `0020` /
  Workforce `0016`, Applications `0010` through `0012`, Authorization `0023`,
  and Workforce `0018` reversal planning;
- Workforce Department-reference successor install, fail-closed reverse, and
  reapply behavior;
- populated reversal refusal at each protected evidence class;
- exact old-plus-new trigger/function fingerprint, 19-reference Department
  catalog, and drift rejection;
- runtime and `PUBLIC` ACL matrix, including dedicated-receipt containment;
- unchanged current-profile fingerprints and no selectable Programme profile;
- legacy review/acceptance/target denial in Python and PostgreSQL;
- atomic state/receipt/audit/event/outbox rollback and retry conflict;
- cross-tenant, cross-edition, stale-version, actor-attribution, and immutable-
  snapshot rejection;
- Draft reassignment, Active retirement, exact-ID orphan recovery, shared-
  mutex races, idempotent replay, owner-chain integrity, and generic
  dependency refusal; and
- consistent backup/restore with no fabricated cross-module record.
