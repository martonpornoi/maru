# Programme exit preparation: remaining private history paging

Date: 2026-09-19. Necessary #189/#108/#48 preparation, not a complete exporter.
Prepared separately while PR #191's immutable head ran hosted checks.

## Contract

EVT-007/INT-007 and ADR 0081 require authorized retained history, not just a recent
screenful. Add optional keyset cursors to the remaining core Programme readers:
discussion sequence, private public-copy rendition number and compound readiness
position. Existing callers still receive their newest bounded page, with the same
field ceiling, exact tenant/edition/item, pre/post authorization and audit before
return. No new permission, profile, route, table, migration or runtime ACL.

Readiness position comprises existing visible item version, concern, history
kind and sequence. Native item/concern uniqueness plus each kind's concern-local
sequence makes that compound position unique; no private stable row ID needs to
be added to the projection. The SQL compares the whole tuple and explicitly
orders the returned rows by it, preserving ties and deterministic continuation.
Positive bigint, closed concern/kind and exact cursor-type validation rejects
malformed inputs before any history read. SQL values remain bound parameters.

Private review pages retain the already authorized historical withdrawal facts
and copy; they do not resurrect public sharing. Missing scoped items remain
unavailable, whereas exhausted existing histories return audited empty tuples.
Each page rechecks current authority, but only an eventual collector can prove
archive-wide consistency, final authorization and completeness. Retained histories
and ordinary screens are unchanged; rollback needs no data migration.

## Evidence and remaining debt

Focused database-free feedback passed 193 cases in 1.77 seconds. Fake-storage
tests cover discussion beyond 200 entries, compound ties across concern/kind/
sequence, exact scoped parameters and stable SQL ordering, private withdrawn
reviews, empty pages, malformed cursors, initial/final denial and audit failure.
Ruff, strict typing, NumPy and semantic documentation checks passed the modified
query contract. Complete unit feedback and exact certification remain pending.

Maintain one additional parameterized discussion PostgreSQL case using real
commands, plus paged readiness and withdrawn private-review assertions inside
existing fixtures. No expensive new database fixture is introduced. All remain
uncollected/unexecuted under ADR 0100/#102; mock SQL composition is not real SQL,
runtime, concurrency, isolation or native acceptance.

Full owner collectors/schemas, source and permission rechecks, file linkage,
usable archive selection/download, supported volume and P11 composition remain
#189. #190 stop-use, #97 logical recovery, P12 inventories/denials, restored #102,
genuine-person #92 and integrated #109 remain necessary before completing #48.

Complete database-free feedback subsequently passed all 11,633 units in 82.16s,
with three existing Django URL-field warnings and an owned temporary directory.
Repository documentation passed 642 Markdown files, four skills and 215 requirement
identifiers. Exact clean-commit certification and protected delivery remain pending.
