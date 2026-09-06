# Programme conversion migration and recovery

Status: synthetic-data deployment contract; not production approval

Last updated: 2026-09-06

## Scope and prerequisites

This is the recovery contract for [issue #77](https://github.com/martonpornoi/maru/issues/77),
PRG-008, and [ADR 0086](../architecture/decisions/0086-source-bound-programme-accepted-item-conversion.md).
Read the [owner boundary](../modules/programme-conversion.md) and the existing
[Programme review recovery guide](applications-programme-review-migration-and-recovery.md)
before operating on this graph. Use only synthetic data while production
privacy, retention and deployment gates remain open.

The additive graph is ordered as follows:

1. Authorization `0025_programme_conversion_capability` declares one
   nondelegable Department capability, without granting it.
2. Applications `0016_programmeacceptedtransition` creates the immutable source
   and retry receipt, including its deferred reference to the Programme item.
3. Programme `0004_accepted_item_source` adds the exact accepted kind/operation
   and turns the existing `source_object_id` column into a protective foreign
   key. The rename/alter sequence preserves the column's values; it is not a
   remove-and-recreate operation.
4. Programme `0005_accepted_item_integrity` extends the existing closed guards
   for this exact source-bound creation operation. Other mutations retain
   their previous version and evidence rules.
5. Applications `0017_programme_conversion_integrity` installs effective-source,
   shared-retry, append-only, reciprocal evidence, readiness and outbox guards.
6. Applications `0018_programme_conversion_downgrade_fence` and Programme
   `0006_accepted_item_downgrade_fence` close the graph and refuse contraction
   once conversion evidence exists.

Apply the complete graph using the migration-owner connection with writers
quiesced. Do not mount a route or enable a Programme profile during this
migration. The new source relation and all Programme relations remain
`SELECT`-only for the runtime role. New trigger functions have owner-only
execution; no helper is added to the runtime execution allowlist.

## Verification

Before making any acceptance claim, verify:

- model/migration state has no drift and the complete graph is applied;
- Applications and Programme integrity readiness both pass, including exact
  relation, column, constraint, index, trigger, function and privilege checks;
- the runtime-role probe accepts the updated read-only relation inventory;
- the synthetic conversion commits both reciprocal references, both success
  evidence sets and all seven initially required readiness concerns;
- stale sources/versions, missing authority/pins and concurrent source changes
  fail without partial success or private disclosure;
- an unused graph reverses and reinstalls, while a used graph refuses
  downgrade before removing either owner's protections.

Readiness reports only aggregate diagnostics. Never copy proposal content,
review messages, names, private titles, retry values, or database rows into
logs, issue comments, or migration evidence. Green readiness does not prove
that Programme Operations is usable or that production data is approved.

## Failure and recovery

A failed command is safe to retry with its exact original actor, key and
normalized intent. First refresh source and control versions for a *new*
intent; do not substitute a new key to bypass a consumed revision. A retained
retry result is historical creation evidence, not a fresh readiness check.

Do not delete a source receipt to undo conversion, change provenance by SQL,
disable triggers, relax a uniqueness constraint, or remove either side of the
reciprocal reference. A populated downgrade raises a fix-forward error.
Keep compatible application code and investigate the precise failed guard.

If a migration fails before completion, keep writers quiesced, inspect applied
migration state, and fix forward or reverse only the unused supported graph.
Any restore must recover Applications, Programme, Authorization, Audit, Effects
and the outbox from one consistent point; piecemeal restoration can fabricate
or sever provenance. Re-run integrity and runtime-role checks before resuming
the same compatible code. Backups, restore rehearsal, encryption and retention
approval remain production gates, not claims made by these synthetic tests.
