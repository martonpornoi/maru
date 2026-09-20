# ADR 0114: Restore-stable exact Identity trigger predicates

- Status: Accepted
- Date: 2026-09-20
- Requirements: IDN-014, NFR-001, NFR-008, NFR-013 and AUD-001
- Issue: #97 within #48
- Supersedes: raw parse-tree hashing only for the two conditional invitation triggers

## Context

The same-image PostgreSQL 17 logical restore retains the exact readable
definitions of `identity_page10_delivery_version` and
`identity_page10_hardened_delivery_update`, but changes their internal
`RelabelType.relabelformat` from implicit to explicit cast rendering (2 to 1).
Their `tgqual::text` hashes therefore differ. A data-free round-trip comparison
isolated three and five such fields respectively; this was not a source-location,
predicate, operator, literal, OLD/NEW reference or attachment change.

The migration's implicit varchar-to-text coercions appear as explicit text casts
when PostgreSQL emits and reparses the trigger DDL. Pinning internal parse-tree
serialization treats this ordinary supported restore as a changed guard even
though its complete deparsed definition remains identical.

## Decision

For these two conditional triggers only, compare the complete exact pretty
`pg_get_triggerdef(oid, true)` output to reviewed literal definitions derived
from Identity 0018's `FINALIZE_V8_PROVIDER_GUARDS`. Do not infer an expected value
from a live restore. Retain the exact trigger name, table, function identity,
row/event/timing bits, enabled state, deferrability, initial deferral, absence of
arguments, ordered UPDATE columns and presence of the WHEN clause as independent
metadata checks. Other invitation triggers still require no WHEN clause.

The literal definitions retain the old/new provider-reference comparison, empty
reference exclusion, disposed-provider regex and negation. Neither stripping
casts nor deleting parse-tree fields is used. Any changed predicate, trigger
attachment, function, operator, literal, regex, event, timing or unexpected
formatting fails closed. All independent function fingerprints, ACLs, migration
recorders, retention policy and worker/activation checks remain required.

This replaces two internal representation hashes with stronger reviewable whole-
definition contracts. It changes no database object, runtime privilege, stored
history, retention decision, approved policy or operational command. Physical
restore and the broader Identity boundary are unchanged. No production restore
or profile activation is implied.

## Verification and alternatives

Require fresh-catalog and actual drop/reparse checks under rollback, followed by
the same-image full logical round-trip and genuine restricted-runtime worker.
Negative cases alter each predicate, its function, timing and event, and verify
the original contract after rollback. Existing invitation runtime and retention
tests remain required alongside these representation regressions.

Normalizing arbitrary parse-tree fields would depend on PostgreSQL internals and
could hide semantic differences. Accepting both arbitrary observed hashes would
make an unexplained restore its own authority. Recreating triggers during recovery
adds an unnecessary privileged repair. Exact reviewed deparsed definitions avoid
all three while preserving strict readiness.
