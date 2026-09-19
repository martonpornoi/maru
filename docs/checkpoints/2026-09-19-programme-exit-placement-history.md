# Programme exit placement-history preparation

Date: 2026-09-19
Status: local #189/#108/#48 component, not complete P11 acceptance

## Retained evidence, not current source approval

EVT-007/INT-007 and ADR 0081 require retained owner decisions in the permission-
controlled exit archive. Placement decisions advance an independent sequence per
placement/kind, not the Programme aggregate version. The existing exact-history
reader already retains their private rationale, but requires a known placement
and fixed sequence ceiling; it cannot alone enumerate every retained stream.

The new owning history-head reader groups exact tenant/edition/item/kind rows by
opaque placement reference and returns their maximum retained sequence, ordered
by placement identifier. Fifty-row keyset pages use a sentinel and explicit
continuation. Existing items with no more decisions return audited empty pages;
unknown/wrong-scope items remain unavailable. It preserves placement-adapter
admission and the independent delivery-history or staffing-history field ceiling,
never substitutes current-preview authority for private history authority.

The separate placement collector traverses both kinds' heads and existing fixed-
ceiling histories within one outer canonical parent/edition transaction. Final
admission and minimized read audit are mandatory. Missing/gapped/repeated/changed
or over-bound pages yield no partial result. Current Scheduling, Venue and
Workforce sources are not dereferenced to reinterpret already retained decisions.
Historical success/withdrawal is not current operational fitness. Private stream
contents are excluded from repr.

The collector limits of 2,000 streams and 20,000 decisions are explicit refusal
boundaries, not new writer limits or real-convention volume certification. Whole-
owner/profile composition, source-reference mapping, portable schemas, larger
volume, files, UI/retrieval, recovery and stop-use remain unfinished. No schema,
migration, role/capability, profile, route, CI/dependency change, production data,
destructive operation or unrelated domain write. Removing unused read composition
requires no data migration.

## Evidence

Thirty database-free cases passed in 0.27s: exact scoped grouping/cursors,
sentinel behavior, initial/final denial, empty/unknown distinction, independent
streams sharing unchanged item versions, all pages, audit failure, corrupt
ceilings, repeated/gapped/empty continuations and bounds. Ruff, strict typing,
NumPy and semantic docs passed after correcting one annotation/docstring alias.

One additional actual-command native case extends the existing assessed fixture:
two placements, both independent kinds, paged grouped heads, retained old
decisions after a candidate move, no current-candidate dereference, field denial,
unknown item and required audit. It remains **uncollected/unexecuted** under
ADR 0100 and is #102 debt. No native SQL, lock/race, runtime, human or integrated
acceptance is claimed. Full feedback and exact certification are pending.

Complete database-free feedback subsequently passed all 11,740 units in 84.70s,
with the same three existing Django URL-field warnings and a fresh owned temporary
directory. Documentation validates 644 Markdown files, four skills and 215 stable
requirements. Exact clean-commit certification and protected acceptance are next.

## Exact certification and protected delivery

All eight retained gates passed for clean head
`78c541533f2cabb7c98f814af914e19c270e940e`, tree
`fa662f3139c87831c11aefe1d1c3232e7f6c7b3b`, against protected base
`c13c4185346014c54ce41f943859ce31c56a15f7`: 438.111s (7m18s), 11,740 units
in 81.85s and 103 frontend cases. Receipt v4 completed 18:46:22 UTC as
`postgresql_deferred`, zero databases and null combined coverage/headroom.
Receipt, plan, actual unit report, wheel and sdist were preserved with matching
hashes outside `.local-ci`; receipt SHA-256 is
`9c3f759d14f704355b9426b690fa3518fe3466d82f16062f92910195490fdf29`.

[PR #194](https://github.com/martonpornoi/maru/pull/194) merged at
2026-09-19 19:04:38 UTC as protected squash
`42c50e497bc6cfffa399725ad5845617149709c0`. Hosted run `35462336977`
passed quality job `105948352789` in 12m58s, unit job `105948352798` in
2m18s and exact-head PR gate `105950146833` in 3s. All three exact-head
CodeQL analyses (`1805005079`, `1805004071`, `1805003593`) reported zero
findings/errors/warnings. Complete reviews/threads and closing references were
empty; immediate mergeability was CLEAN/MERGEABLE. Merge used the exact head.

The protected tree equals the certified tree. Clean local main and origin/main
both equal the squash; the detached repair worktree remains untouched. Issue
comments on #189, #108 and #102 record delivery and maintained native debt.
Parents remain open for the full archive, stop-use and integrated acceptance.
