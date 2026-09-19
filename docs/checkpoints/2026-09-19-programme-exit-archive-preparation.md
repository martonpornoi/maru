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

## Exact certification and hosted outage

Corrected head `5b97bf1a222b07a680870660d650b141087667f2`, tree
`bc98245eacaeff62497427afc2ea0f75d7622bf4`, passed all eight retained local gates
in 414.405s, completed 2026-09-19 17:05:12 UTC: 11,594 units in 82.10s and 103
frontend cases. Receipt v4 is `postgresql_deferred`, zero databases and null
combined coverage/headroom. Five artifacts were archived and hash-matched in
`.tools/certification-evidence/programme-exit-5b97bf1-deferred/`; receipt SHA-256
`123562291198721C219235EDA8E2DC82E939F079ABDA00128C7A85C331F85564`.

PR #191 opened at that head after read-only origin/account/#48 verification
resolved an initial safety-review destination rejection. Hosted run `35457123554`
passed units in 1m41s. Exact-head CodeQL analyses `1804807119`, `1804806432` and
`1804806091` have zero findings, errors and warnings. Quality job `105934321039`
failed after 13m26s: the final frontend vulnerability audit received repeated
npm HTTP 503 maintenance responses. Python audit passed. A direct pinned-pnpm
audit reproduced HTTP 503. The PR gate failed; no merge or main sync occurred.

[npm status](https://status.npmjs.org/) listed 17:00–19:00 UTC maintenance on
2026-09-19, not a guaranteed recovery time. Its Security Audit badge still read
operational; actual requests remained unavailable. Resume with a successful direct
audit, then rerun failed hosted checks and verify exact-head acceptance. No audit,
dependency, coverage or protection was weakened, and no scheduled watcher exists.

GitHub parsed the initial negated closure phrase as a closing reference. The PR
body was reworded and the complete GraphQL closing-reference list verified empty;
reviews and threads are also empty. #189/#108/#48 remain open. The separate tested
history follow-up is retained on unpublished `codex/programme-exit-history`, not
part of this certified head. Its named stash has already been applied once.

## Protected delivery after service recovery

The direct pinned-pnpm audit passed on resume. Only failed hosted jobs were
rerun at the unchanged head, run `35457123554`, attempt 2. Quality passed in
12m04s and the aggregate gate in 4s; passing units remained 1m41s. All three
processed CodeQL configurations still have zero findings/errors/warnings.
Complete review/thread/closing-reference pagination was empty and mergeability
was CLEAN/MERGEABLE. No bypass or policy change was used.

Exact-head squash merged as `4f0aae675124beedf77b0b77535094d9a6942222` at
2026-09-19 17:51:10 UTC. Its tree is the certified
`bc98245eacaeff62497427afc2ea0f75d7622bf4`. Clean local main was fast-forwarded
and verified equal to origin/main and that protected commit; the repair worktree
remained at `aa1ede69fb880dcb12d627bbfc049fba23166e68`.
The two unpublished history/core follow-up commits were rebased onto the squash
and their tree remained `b5985f410a2e64b0d22c8e783479e0f789f34ba2` before
this delivery documentation update. #189/#108/#48 remain open. Native tests remain
uncollected/unexecuted; this is development delivery, not P11 acceptance.
