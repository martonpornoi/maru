# ADR 0090: Risk-based PostgreSQL acceptance

- Status: Accepted
- Date: 2026-09-07
- Requirements: NFR-001, NFR-002, NFR-003, NFR-008
- Supersedes: ADR 0060, ADR 0061, ADR 0063 and ADR 0066 only for test
  selection, indivisible-file scheduling and compulsory exhaustive local runs

## Context

The owner explicitly approved separating routine PostgreSQL behavior from
exhaustive historical migration testing after PR #82's hosted shards 5, 6 and 7
exceeded two hours. Earlier timing rebalancing had not made that suite reliable.
The exact same head passed local certification; a timeout is incomplete evidence,
not a demonstrated assertion failure or permission to merge.

Historical tests repeatedly traverse a growing migration graph. File-level
balancing cannot bound either that growth or one very expensive mixed file.
Moving all PostgreSQL testing to releases would instead defer current workflow,
tenant, authorization and transaction regressions until too late.

## Decision

1. Every code PR runs the complete current-schema PostgreSQL behavior suite,
   unit tests and existing quality/security/frontend/documentation gates.
   Documentation-only changes retain their database-free path. Combined
   branch-aware coverage remains at least 90 percent with unchanged exclusions.
2. A reviewed test inventory names individual historical test functions and
   their migration owners. Unlisted tests are current behavior, never implicitly
   excluded by their filename or duration. Mixed files retain their current
   authorization, raw-SQL, concurrency and readiness cases on every code PR.
   Missing files/functions, duplicate entries and unsafe grouping fail closed.
3. Domain model/migration changes additionally run owner and dependent-owner
   historical cases, directly changed historical test files, and a representative
   committed whole-graph reverse/forward recovery test. Resolve migration
   dependencies from Django's real graph; unknown or removed nodes require the
   exhaustive lane. Global authorization, identity, audit, runtime settings,
   database/dependency, workflow, inventory and test-harness changes, as well as
   destructive changes, require every historical case before merge.
4. Full acceptance remains mandatory for manual certification and releases.
   A nightly default-branch run performs full acceptance only when that exact
   revision lacks a successful or active full run. A failed run is actionable
   repair evidence, not a nightly automatic retry loop. A new revision may run;
   deliberate manual dispatch can recheck an existing revision. Release
   certification always runs against the exact release revision, independently
   of nightly deduplication. No publishing authority is added to CI.
5. Keep eight concurrent isolated PostgreSQL services at most. Exhaustive hosted
   runs use sixteen smaller work groups with matrix concurrency capped at eight
   and the existing 120-minute per-job limit. Routine runs use eight groups.
   Reviewed independent historical functions may be distributed across isolated
   databases; parameterized variants stay together. Shared module-scoped
   historical baselines stay indivisible. No tests run concurrently in one
   database, and no migration, guard, commit fence or assertion is faked or
   removed. Local certification uses eight isolated databases with the same
   inventory and selection policy.
6. The default local pre-review command resolves its scope from the branch diff
   against an explicit base. Explicit full mode remains available. Receipts
   record the exact head, base and selected scope; a current-only diagnostic run
   cannot be presented as exhaustive or as evidence for a higher-risk diff.
7. Preserve cheap draft feedback, the protected exact-candidate `PR gate`,
   independent CodeQL, immutable inputs, no bypass actors, fail-fast policy and
   unchanged coverage. Record executed selection and JUnit diagnostics. Validate
   the union and disjointness of every scheduled work group before execution.

## Consequences and accepted tradeoff

Routine feature work no longer waits for every historical compatibility path.
An unanticipated historical interaction can be discovered after a lower-risk
merge; nightly failures require triage and repair before release or work that
depends on the broken boundary. They must not become ignored background noise.
High-risk changes still wait for exhaustive evidence, including this CI redesign
and PR #82's migration-harness changes. Neither is granted a bootstrap bypass.

The initial 20–35-minute routine feedback estimate is a target, not measured
acceptance. Compare exact collection, coverage, total runner time and end-to-end
duration after implementation. Historical execution is amortized across ordinary
PRs, not eliminated; two shorter hosted waves also incur additional setup cost.

## Alternatives

Release-only PostgreSQL checks defer essential current safety evidence. Another
timing-only refresh or a higher timeout does not address graph growth. Additional
simultaneous database workers would spend more concurrent resources. The selected
policy retains current safety evidence, regularly checks history and makes the
remaining expensive work bounded without increasing database concurrency.
