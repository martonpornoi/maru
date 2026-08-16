# Page 10 profile-extension value command candidate

Date: 2026-08-03

## Outcome

The working tree now has one candidate command/query boundary for
post-submission profile-extension values. It replaces the earlier unsequenced
service and API writer; it is not independently accepted until the separate
acceptance review reports an explicit verdict.

## Implemented boundary

- `RegistrationProfileExtensionValueControl` owns the current sequence and
  exact latest-revision pointer for one registration and stable field key.
- `RegistrationProfileExtensionValueCommandReceipt` owns scope-bound retry,
  actor, writer kind, request digest, expected/result sequence, correlation,
  and exact result evidence.
- `append_profile_extension_value` performs current identity and exact-tenant
  authorization, strict UUID/source/reason/JSON and typed-value validation,
  expected-sequence locking, idempotent historical replay, minimized audit,
  registered domain event/outbox publication, final authorization, and receipt
  verification in one transaction.
- `read_profile_extension_values` returns at most 128 deterministic active
  fields, filters attendee visibility/writer policy, projects only the current
  immutable value, reauthorizes, appends a sensitive-read audit, and returns a
  sequence-derived snapshot digest.
- Owner and staff HTTP adapters use the same services. Writes require a
  canonical `Idempotency-Key` header and `expected_sequence`, expose an
  `Idempotent-Replay` response header, return the bounded snapshot, and publish
  explicit RFC 9457 OpenAPI responses. Write plus response projection is one
  outer transaction.
- Staff access uses only `registration.view_profile_extensions` and
  `registration.update_profile_extensions`; the broader service-summary and
  register-on-behalf capabilities no longer authorize this data.
- Demo data uses the canonical owner command. Registration-lead and
  convention-chair demo accounts receive the dedicated exact-edition
  capabilities.
- Django admin exposes value revisions, sequence controls, and command
  receipts as read-only evidence rather than alternate writers.

## Database migration

Registration migration `0036_profile_extension_value_commands`:

- creates the control and immutable receipt relations;
- backfills only contiguous legacy histories with compatible actor/writer,
  registered source channel, active-or-retired definition, 16 KiB ceiling,
  canonical typed value, options, integer, and requiredness semantics;
- refuses incompatible legacy population atomically with code-owned
  diagnostics;
- installs DB-time, append-only, no-truncate, exact scope/sequence/pointer,
  audit/event/outbox, and deferred revision-to-receipt guards;
- retires the stale legacy PUBLIC-executable helper and pins every new
  `SECURITY DEFINER` search path while revoking PUBLIC execution;
- supports multiple sequential commands in one outer transaction and durable
  historical replay after the current pointer advances;
- permits empty reverse/reapply and refuses populated reversal after canonical
  command receipts exist.

## Verification

- New command and migration adversarial suites: 47 passed on fresh
  PostgreSQL.
- Migrated owner/staff API, typed-value, rollback, idempotency, and OpenAPI
  suite: 13 passed on fresh PostgreSQL.
- Accepted profile-definition regression repaired to use the canonical value
  command: 2 focused tests passed.
- Ruff and strict source mypy pass for the changed value, API, serializer,
  admin, service, and fixture source.

The 47-case construction suite found and drove fixes for a stale executable
helper, noncontiguous and impossible legacy population, nested sequential
appends, and historical replay after aggregate advancement. These results are
candidate evidence, not a substitute for the active independent acceptance
review.

## Remaining gates

1. Obtain an explicit independent acceptance verdict on fresh databases.
2. Run adjacent profile-definition, demo, runtime-role, migration-drift, and
   repository documentation gates after concurrent Page 10 work settles.
3. Reconcile remaining HTML/admin/fixture configuration writers before the
   Page 10 stopped-writer activation stage.
4. Implement the attendee/staff browser workflow and later registration-data
   retention execution; the API/command core alone is not the complete user
   journey.
