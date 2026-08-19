# Page 10 invitation-retention v8 corrective candidate

Date: 2026-08-03

Status: **corrective candidate verified locally; independent acceptance and
production activation remain blocked**

This append-only checkpoint records the repair of the defect set in
`2026-08-03-page10-invitation-retention-adversarial-findings.md`. It does not
erase that finding, declare an independent verdict, select a legal retention
period, or activate production disposal.

## Resulting boundary

- Identity migration `0018_invitation_retention_v8` makes the invitation-to-
  reserved-account relationship unconditionally unique and refuses ambiguous
  populated preflight data.
- A value-minimized one-to-one assessment records the current safe result,
  terminal version, policy digest, database assessment time, and strictly
  monotonic assessment version. `disposed` is valid only with the exact
  matching receipt; every other result forbids a receipt.
- Candidate traversal persists a `retention-v2` `(last_transition_at, id)`
  cursor, wraps fairly, and uses a retention-specific PostgreSQL advisory lock.
  Blocked old rows therefore do not starve later eligible rows.
- Challenge and delivery histories are processed in bounded 128-row chunks.
  There is no fixed 32-challenge disposition ceiling.
- Successful disposition tombstones account/challenge contact and every
  non-empty parent-delivery, attempt, and late-outcome provider reference with
  random-keyed one-way non-routable values.
- Permanent receipt-aware PostgreSQL guards prevent later account, challenge,
  group/permission membership, delivery, provider-reference, receipt, or
  assessment mutation that would make retained evidence misleading.
- Policy JSON rejects duplicate members. Retention audit evidence accepts only
  exact `operator` or `scheduler` sources. Policy, hold, receipt, assessment,
  heartbeat, and cursor evidence is PostgreSQL-clocked, non-future, and
  progression-coherent.
- Invalid management-command limits become stable `CommandError` failures and
  record no success heartbeat.

## Migration and recovery

Existing v7 receipts are upgraded in place. The migration derives a fresh
ephemeral random key per receipt, replaces raw provider references across the
complete delivery graph, and creates the exact disposed assessment using one
materialized database timestamp. The random key is never persisted.

The reverse path remains available only on a genuinely unused v8 boundary.
Any receipt, assessment, or `retention-v2` scheduler/cursor evidence refuses
downgrade. After that point recovery is fix-forward or whole-database and
application restore to one reviewed pre-v8 point; deleting recorder/evidence
rows or disabling guards is not a rollback procedure.

## Readiness and least privilege

Readiness generation `page10-invitations-additive-v8` pins migration `0018`,
50 complete function fingerprints, 74 exact trigger contracts including
predicate hashes, and 16 index contracts. A fresh catalog reports all four
catalog groups ready and no uncataloged Page 10 function or trigger.

The runtime-role contract adds only the writes required by the application:
assessment rows and provider-bearing attempt/late-outcome rows may be inserted
or updated through guarded workflows; receipts remain append-only. Runtime has
no delete, truncate, references, trigger-disable, function-execute, role, or
ownership escape.

## Verification performed

- Fresh PostgreSQL full migration through identity `0018`: **passed**.
- Genuine empty identity `0018 -> 0017` reversal, `0018` reapplication, and
  post-reapply exact readiness inspection: **passed**.
- `makemigrations identity --check --dry-run`: **no changes detected**.
- Fresh additive catalog inspection: **ready**; 50 functions, 74 triggers, 16
  indexes, no uncataloged Page 10 objects.
- `tests/integration/test_platform_invitation_retention.py`: **28 passed**.
  This includes more than 32 challenges, provider graph disposal and one-way
  guards, fair wraparound, concurrent workers, exact sources, duplicate JSON,
  isolated +250 ms database-time forgeries, permanent tombstones, populated-v7
  upgrade, and populated downgrade refusal.
- `tests/integration/test_page10_invitation_readiness_contract.py`: **165
  passed**.
- database-role unit/integration matrix: **119 passed**.
- adjacent invitation commands, delivery worker, and database hardening: **69
  passed** after updating the test migration-owner helper to the v8 split
  delivery-update trigger name.
- Ruff over the changed retention/readiness/role/test boundary: **passed**.
- Strict mypy over the changed source boundary: **passed**.

## Remaining gates

1. A different reviewer must rerun the adversarial matrix and issue the
   acceptance or rejection verdict.
2. Production still requires a jurisdiction-specific approved policy, exact
   migration-owner activation, supervised daily `retention-v2` execution,
   alerting, representative load evidence, and backup-expiry/PITR rehearsal.
3. Stopped-writer cutover and the broader Page 10 lifecycle candidates remain
   separate gates. Route availability and this local result are not production
   approval.
