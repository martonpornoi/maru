# Programme exit archive: packaging and history preparation

Date: 2026-09-19. Scope: necessary #189 prerequisite of #108/#48, not P11
acceptance, a usable whole-profile exporter or closure of any parent.

## Outcome and contract

EVT-007, INT-007, NFR-013 and ADR 0081 already require an authorized Programme
exit archive. Timetable packs do not satisfy that contract. Necessary #189 and
#190 are explicitly listed in both parent bodies and attached as native children
of #108; existing children and parent status were preserved. This change neither
reverses an ADR nor adds a current profile, permission, route, worker or migration.

The initial pure `programme.exit-archive@1` encoder composes eight explicit owner
records/schema sections and identified Applications file bytes. It retains exact
scope and generation metadata, fixed member paths, byte lengths and SHA-256
hashes in a C3 Restricted manifest. It rejects malformed/duplicate JSON, missing
owners, unknown contracts, duplicate files and overflow without returning partial
bytes. No filesystem, database, network, import or executable extraction is added.
Its provisional 32 MiB total is not a supported real-convention volume claim.
Hashes are not authentication; ZIP mode bits do not establish device encryption,
retention authority or secure deletion. Authorized collectors remain required.

Working and delivery history now accept an exclusive positive-bigint
`before_sequence` cursor, using the existing item-unique native sequences. The
unchanged default returns the newest bounded page. Further pages retain exact
scope, original field ceiling, pre/post authorization and sensitive-read audit.
Older pages are not shifted by intervening appends. Paging does not provide an
archive-wide snapshot or final revocation check: source consistency remains a
collector obligation. No historic private field is newly made public.

## Verification and recovery boundaries

Focused database-free feedback passed 83 cases in 0.41 seconds. This includes
all 205 retained revisions across a 200-entry boundary, exclusive cursor edges,
initial/final denial, wrong scoped item and failed audit. Strict typing and
semantic documentation passed the two modified source interfaces; focused Ruff
passed after ordinary lint corrections. Repository documentation passed before
this checkpoint was added; final validation and exact certification remain pending.

The first complete unit-feedback invocation failed: 11,210 passed, 384 setup
errors in 120.89 seconds because Windows denied access to the shared
`pytest-of-TheMw` temporary directory. No source defect or database acceptance is
inferred from that result. A fresh repository-owned temporary directory is used
for the rerun, matching the existing certification procedure; no ACL or shared
directory was changed or deleted.

Two maintained PostgreSQL cases use real Programme commands and queries to cover
retained revision pages, an intervening append, foreign organization/edition,
final authorization denial and minimized audit counts. They remain uncollected
and unexecuted under ADR 0100/#102. Unit fake storage is not their substitute.
No schema, populated migration, runtime-role or restore proof is claimed.
Removing the unused encoder or optional paging call sites needs no data migration;
retained records and existing newest-page callers are unchanged.

## Still required

- Owner-specific complete collectors, explicit field schemas and file linkage;
  current authorization/source rechecks and audited generation/retrieval.
- Supported large-volume handling, clear selection/download, custody/retention
  instructions and actual P11 composition; #189 remains open.
- Accountable scoped stop-use (#190), logical recovery (#97), complete P12
  excluded-domain/effect inventories and real denial matrix.
- Restored PostgreSQL acceptance (#102), genuine-person work (#92) and integrated
  evidence (#109) before any activation, pilot or complete #48 claim.

## Complete feedback result

The fresh repository-owned temporary-directory rerun passed all 11,594 units in
81.25 seconds, retaining only three existing Django URL-field warnings. The
database URL was deliberately unreachable. Final repository documentation passed
641 Markdown files, four skills and 215 requirement IDs. This resolves the
shared-temp feedback failure, not the deferred native acceptance obligations.
Exact clean-commit certification and protected delivery are still pending.

The first exact-commit attempt stopped at NumPy docstring lint: the pure encoder
listed its helper's exception in a `Raises` section without directly raising it.
The exception contract now lives in `Notes`, preserving behavior and documenting
the same stable failure. No exemption or check was weakened; fresh certification
of the corrected exact commit is required. The earlier attempt is not acceptance.
