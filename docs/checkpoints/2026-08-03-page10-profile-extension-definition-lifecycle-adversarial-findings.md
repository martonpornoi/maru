# Page 10 profile-definition lifecycle adversarial findings

Date: 2026-08-03

## Verdict

The first profile-extension definition lifecycle core is **not accepted**.
Its author-side focused and adjacent suites remain useful baseline evidence, but
an independent fresh-PostgreSQL review reproduced three high-severity
correctness defects and one populated-downgrade limitation. This checkpoint
supersedes the stability implication of the earlier lifecycle-core checkpoint;
it does not rewrite that historical record.

## Confirmed defects

1. Historical source retirement can strand lifecycle transitions. Model
   validation requires a linked source template to remain published on every
   later save. Retiring that source makes both direct field retirement and
   successor activation fail even though source provenance is historical and
   the successor has independent content.
2. Replay does not validate the action-specific receipt target. A raw database
   update changed approval evidence from the reviewed target/digest/schema to an
   activated target with an unrelated schema version and digest; the command
   still returned the old result as a successful replay. Setup targets have no
   PostgreSQL update/delete/truncate immutability boundary in this generation.
3. Optional source provenance identifies only a template or prior-edition
   container, not one exact source definition identity, version, and digest. A
   caller can select an empty published template while supplying arbitrary new
   field content, producing a false source claim.
4. Empty migration `0034` reverse/reapply is exact, but reversing after a
   `profile_field_successor_started` receipt leaves the row while the historical
   application model no longer recognizes that action choice. Populated
   downgrade therefore needs a fail-closed preflight or an explicit compatible
   recovery generation.

Each failed command reproduction left field state, setup version, receipts,
targets, audits, events, and outbox rows unchanged. That rollback behavior is
preserved but does not close the defects above.

## Independent evidence

- Focused lifecycle/migration baseline: **24 passed in 54.21 seconds**.
- Adjacent clean regression baseline: **23 passed in 40.44 seconds**.
- Reviewer deactivation durability, unrelated aggregate changes, current-actor
  authorization, stale/changed retry refusal, rollback, concurrency, ordinary
  active immutability, and value-history preservation remained green.
- The review used a unique fresh PostgreSQL database and only synthetic data.

## Required repair gate

- Permit eligible source retirement after exact immutable import evidence is
  recorded; never weaken source eligibility at initial import.
- Persist and verify an exact source definition generation, or reject source
  selection until such evidence exists. Container-only provenance is not
  acceptable.
- Validate exact action-specific target kind, identifier, change kind, schema,
  and digest on every replay, and make receipt/target rows immutable at the
  PostgreSQL boundary.
- Fence populated migration reversal once successor action or lineage evidence
  exists.
- Add direct regressions for every finding, rerun the focused/adjacent matrices,
  and obtain a new independent verdict before mounting lifecycle adapters.
