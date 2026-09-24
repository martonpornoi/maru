# Programme logical schema comparison and populated component recovery

- Date: 2026-09-20
- Scope: #97 within #48, bundled with Programme exit/integrated work
- State: local correction and component evidence; genuine-runtime restore pending

[ADR 0113](../architecture/decisions/0113-logical-restore-enum-cast-canonicalization.md)
maps only PostgreSQL's exact enum constant varchar-array/text cast reparse back to
the original migration-built spelling. It applies to CHECK/exclusion definitions
and indexes, preserves all other metadata and does not update any expected hash.
No migration, stored-data repair, guard disabling or runtime privilege is added.

The first schema probe compared all 297 public relations and found 90 raw
differences. CHECK-only comparison left 15 differences, revealing the same cast
in partial indexes, exclusions, uppercase classification codes, versioned codes
and definitions with ordinary regex literals. The bounded final rule reconciles
87 relations. Three unrelated physical dropped-column layouts remain different
and deliberately unnormalized; none belongs to a currently pinned relation-shape
catalog. The full probe passed in 6.28s after checking those explicit limits and
source preservation, using one temporary UUID-named database inside the owned
synthetic test container. The clone was dropped, not the original database.

Thirty-six units and eleven PostgreSQL cases passed together in 11.53s. The
native cases reparse actual constraints and indexes under rollback for all five
current owner catalogs (Authorization, Events, Workforce, Scheduling, Venues),
retaining the original hashes. Weakened, unvalidated and changed CHECK/index
predicates remain rejected. Lint and documentation validation pass.

The retained populated #96 reproducer was adapted to the current exact synthetic
container. Its first attempt failed at import/collection before database work.
With the repository helpers on its import path, the populated logical restore
passed in **13.86s**: all five catalog hashes and Scheduling integrity matched;
the release/artifact survived; actual public-copy withdrawal and exact retry
committed; the native dependency journal contained one corresponding entry;
current disclosure became invalidated while the original artifact bytes stayed
unchanged. The original source remained operational and its schema unchanged.
This component uses the existing test-authorizer fixture, not genuine runtime
authority, and cannot close #97 by itself.

Evidence: `.tools/programme-logical-schema-probe-3.xml`,
`.tools/programme-logical-schema-native-1.xml`, and
`.tools/programme-logical-populated-component-2.xml`.
The failed earlier reports remain separate. The maintained recovery runbook now
documents the narrow representation rule and clone-only recovery procedure.
The complete fast suite first found one outdated mock omitting the collector's
required constraint/index fields (12,723 passed, one failed in 74.78s). Correcting
that fixture, rather than weakening the collector, and adding expired-lease,
oversized-input and malformed-URI transport cases yields **12,728 passed in
75.75s**, with three existing URL-field warnings. Focused changed-file lint passes.
Evidence: `.tools/programme-exit-bundle-units-17.xml` (failed) and
`.tools/programme-exit-bundle-units-18.xml` (passed).

Genuine restricted-runtime restore, post-restore authority denial and partial
restore/journal/function/ACL negatives still need completion before exact-head
certification and protected delivery. #97/#109/#108/#48 remain open.
