# Checkpoint: Required PostgreSQL acceptance restored

- Date: 2026-09-20
- Phase: Programme Operations, before remaining integrated exit/stop-use work.
- Related requirements: NFR-001/002/003/008/013, PRG-009, HR-012, EVT-007,
  INT-007, QRY-006/007/008, AUD-001/003 and PRI-001/003.
- Related ADRs: 0090, 0098, 0100 and 0108.

## Outcome and protected identity

[PR #195](https://github.com/martonpornoi/maru/pull/195) restores the tracked
PostgreSQL policy to `required` and closes #102. The prepared archive authority
component and accumulated native-contract repairs are delivered together.

- Certified head: `c018d99d71baa230c1bf2edd942c034740e995c7`.
- Certified and protected tree: `f62cb1f840aabdbac21d1002d9e4154c4bd66d1f`.
- Base: `42c50e497bc6cfffa399725ad5845617149709c0`.
- Protected squash: `b056aa253a39df2648752daf35ac5a158a9950d7`.
- Merge: 2026-09-20 11:14:26 UTC, with exact-head matching and no bypass.
- Clean main worktree and origin/main equal that protected squash.

## Verification

Fresh complete local certification passed all ten gates in 13,677.874 seconds
(3h47m58s). All 11,806 units and 103 frontend cases passed. All 4,592 native cases
passed exactly once across 351 groups, including 106 historical groups, in 53
isolated shards with at most eight concurrent databases. There were no native
failures, errors or skips. Combined branch-aware coverage was 91.53% against the
unchanged 90% floor. Local shard durations including cleanup ranged from 472.469
to 2768.485 seconds; every shard passed the conservative timing projection.
All owned databases were removed. Three earlier failed exhaustive attempts and
their diagnostics remain preserved; no partial result became a success receipt.

Independent [hosted full acceptance](https://github.com/martonpornoi/maru/actions/runs/35495202765)
passed on the same exact head and base. Its independently generated exhaustive
plan fingerprint matches local evidence:
`bf33935f08b6eb3deb38a098ddc98e96f5b4972bad7420bc53a03e1f3a50651d`.
All 53 database reports contain 4,592 cases and zero failures, errors or skips;
selection reports contain 351 unique groups and 4,592 unique node IDs. All 11,806
unit cases passed without failures, errors or skips. Combined coverage was
91.54%. Hosted PostgreSQL jobs ranged from 6m50s to 57m03s, below the unchanged
120-minute cap. Full workflow latency was 4h21m02s; bounded waves reduce timeout
risk, not total exhaustive migration work.

Full CI gate and exact-head PR gate passed. All three CodeQL analyses for
`refs/pull/195/head` report the certified commit and zero results/errors/warnings:
Python `1806255880`, JavaScript/TypeScript `1806255098`, Actions `1806254609`.
This is not a statement about pre-existing default-branch findings. There were
no unresolved review threads, and up-to-date mergeability was verified before
the protected squash. Runtime, timeout, history, coverage and repository
protection settings were not weakened.

Complete local evidence is preserved under
`.tools/certification-evidence/programme-postgresql-c018d99-full`; downloaded
hosted reports/coverage and run metadata are under the corresponding
`programme-postgresql-c018d99-hosted` directory. These ignored artifacts are
local evidence, not cryptographic attestations or public data stores.

## Changed areas and recovery

The [restoration checkpoint](2026-09-19-postgresql-restoration.md) preserves
the actual failures and focused repairs: optional-answer clearing, exact
Department-reference inventory, downgrade preflight ordering, database-clock
evidence and stale native fixture/guard probes. The
[archive authority checkpoint](2026-09-19-programme-archive-authority-boundary.md)
records the purpose/recipe boundary, not a completed archive workflow.
Used retained evidence stays fix-forward; existing published migrations were
not rewritten. Only disposable synthetic databases were used. No deployment,
release, current-profile change or Programme activation was performed.

## Remaining work and delivery bundles

Keep #48, #108 and their incomplete children open. Ordinary full PostgreSQL
certification does not execute every host-only fixture, logical restore,
browser or representative-human acceptance scenario. Those remain explicitly
owned by #108/#109, #97 and #92, respectively; older component notes reporting
unexecuted #102 debt are historical, not evidence that these checks passed.

The maintainer requests larger coherent bundles to avoid expensive certification
for every small component. The next outcome is complete #189 archive generation,
owner collection/coherence, execution/download authorization, private custody,
preview/request/download UI, tests, documentation and P11 composition together.
Then deliver #190 accountable stop-use with related P11 work, followed by
integrated isolation/recovery and P12. Preserve genuine human acceptance and
final separately gated profile promotion. Close issues only when their own full
acceptance is met, not merely because a component was included in a bundle.

Use focused feedback during development, freeze each final bundle for complete
risk-selected local and hosted acceptance, and retain unchanged coverage,
selected history, bounded concurrency and measured headroom. This delivery
record is prepared on the next bundle branch; it does not claim a new feature
or certification of that later branch.
