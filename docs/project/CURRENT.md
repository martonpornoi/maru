# Current project state

Last updated: 2026-10-19
Phase: CI calibration and migration-history isolation are protected-delivered.
The next bounded outcome adds Catalog creation retry and rollback conformance
evidence. Workforce acceptance remains at the human password boundary.

Maru is a Django/PostgreSQL modular monolith under synthetic evaluation, not a
production-ready service. Follow [ROADMAP](ROADMAP.md) and owning requirements.
Keep one active delivery; preserve unrelated worktrees, stashes and evidence.

## Last completed outcome

[PR #218](https://github.com/martonpornoi/maru/pull/218) delivered conservative
current-group cost calibration, committed empty-database history isolation,
one-history-per-batch capacity and verified shared-history database ownership.
Protected squash `ff1dc989f63d8a67cfa510d065aa04bb15abeb5c` has exact certified tree
`eabeeb7b21a8e4a07cd4bfdba981ef2486c877ac`. Designated clean main was synchronized
with a fast-forward only and verified equal to the protected result and origin.

The final `77e88268` source passed all ten ordinary Auto exhaustive local gates
in 21,430.714 seconds: 14,314 units, 5,270 native cases, 386 groups including all
111 histories, 111 batches, at most eight workers, 91.247876% combined coverage
and unchanged headroom. All 111 exact owned containers were independently absent;
5,761 evidence files and 14 metadata files are hash-preserved. Nine earlier full
failures remain failed and preserved. The older successful `77525db` receipt
certifies only its own source; its hosted run was cancelled for the valid
database-ownership review finding. The repair and its native standalone/mixed
ownership proof are documented in the
[ownership checkpoint](../checkpoints/2026-10-19-shared-history-database-ownership.md).

Exact-head hosted run `39256627764` attempt 1 timed out on one original
activation-history test at the unchanged 120-minute limit. All 113 artifacts,
4,527 extracted files and 500 log files were preserved. Comparison supported an
isolated slowdown but did not establish its root cause. After diagnosis, one
targeted unchanged-source retry and its dependent jobs succeeded. Attempt 2
finished at 20:32:58 UTC: 122 successful jobs and three normal alternative skips;
14,314 unit and 5,270 native tests passed, with zero failures/errors/test skips
and 91.252849% combined hosted coverage. All 112 unit/native coverage artifact
IDs and digests reconciled, with 118 successful jobs carried at their original
execution times. Only the timed-out shard, combined coverage and both aggregate
gates executed again. The two new artifacts and complete retry logs are preserved.
The first failure remains part of the evidence, not retroactive acceptance.

Protected merge followed exact-head PR gate, final CodeQL acceptance and all
three clean analyses, resolved conversations and a fresh no-open-issues review.
No assertions, history bodies, permissions, schema guards, isolation, resource
limits, worker limits, timing limits, coverage or protected checks were weakened.
See the [calibration history](../checkpoints/2026-10-17-current-group-cost-calibration.md)
and [delivery and follow-up checkpoint](../checkpoints/2026-10-19-ci-delivery-and-catalog-retry-conformance.md).

The earlier `e7f5c4d` current-only diagnostic measured native elapsed from
5,254.017 to 3,615.559 seconds: 31.18% in one local before/after observation.
It skipped static gates and predates the isolation repairs. It is not a
repaired-source benchmark or a promise of hosted runtime savings.

PR #217's 20 Catalog adapter baseline cases remain delivered. PRs #210–216 also
remain delivered; issues #35, #36 and #42 stay open. The unexplained home archive
audit-guard rejection remains unreproduced, not fixed. Preserve its evidence and
investigate any recurrence precisely. Older paused monitors remain paused.

## Current bounded outcome

The [Catalog conformance plan](../development/catalog-edition-api-conformance-plan.md)
adds 12 native cases for existing creation behavior: original receipt metadata
and version, actor/key collisions, edition and tenant separation, invalid retry
rationale, evidence-write rollback and three controlled competing requests.
Both concurrent requests must reach an observed PostgreSQL edition-row lock
wait. Fault injection occurs after real evidence writes and checks full rollback
before the same key creates a fresh result. No command or policy is mocked.

All 28 earlier cases and their original definitions remain. Runtime, schema,
authentication, permissions, generated clients and product behavior are unchanged.
This is executable evidence for INT-001, NFR-009 and AUD-001, not adoption of a
new compatibility policy. Reason identity, strict scalar/currency validation,
concurrent authority changes, read completeness/audit and public dependency
failure semantics remain owner decisions. The API client supplies synthetic
authenticated principals in process; this is not real sign-in, CSRF, restricted
database-role, browser or independent-human acceptance. Demos are unaffected.

All 40 native cases passed in 243.83 seconds (250.329-second wrapper), with zero
failures/errors/skips. All 3,240 before/pre-run/after/live source entries, 25
artifact hashes and 18 original definitions matched; exact owned-container absence
was independently verified. Complete unit feedback passed 14,314 cases in 86.63
seconds before a test-only fault-helper keyword correction; the native run includes
that correction. Scoped lint/format, 765-file documentation validation and whitespace
checks passed. Ordinary clean-source Auto certification and independent hosted
acceptance remain pending. No result from PR #218 certifies this new source.

## Preserved Workforce blocker

Issue #42's tutorial, route checks, inspector, empty browser launcher and evidence
remain uncommitted in `codex/workforce-rehearsal`. Eight owner native cases, four
inspector cases, 70 focused units, startup smoke and standard Sphinx passed there.
Browser work reached platform sign-in, three invitation deliveries and setup;
223 unadopted model counts were zero only at that intermediate point.

Human entry/submission of recipient passwords was required and not completed
before the four-hour lease ended at 18:40:20 UTC on October 16. Exact container/
listener absence and all 3,239 unchanged source files were verified; the expired
tab and obsolete monitor were closed. Partial public and private evidence remains.
No account activation, role grant, Workforce lifecycle, final absence or human
acceptance is claimed. Do not restart or seed accounts to evade that boundary.

## Smallest next actions

1. Review and commit the coherent tests/documentation outcome.
2. Run ordinary Auto certification
   against current main, and reconcile the exact receipt and cleanup evidence.
3. Push normally, complete exact-head review and hosted acceptance, protected-squash
   with head matching, verify certified-tree equality and ff-only main synchronization.

Preserve unrelated checkouts, stashes, stopped fixtures and private credentials.
No deployment, external mail, credential/authority workaround, weakened safety,
test/coverage/timing gate or additional agent is part of this slice.
