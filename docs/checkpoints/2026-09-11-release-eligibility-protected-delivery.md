# Programme release eligibility: protected delivery

Date: 2026-09-11\
Issue: [#91](https://github.com/martonpornoi/maru/issues/91), child of #48\
Pull request: [#93](https://github.com/martonpornoi/maru/pull/93)

## Delivered boundary

ADR 0094 and SCH-012 now define the ten-category complete release-eligibility
policy. Scheduling's pure evaluator rejects missing, foreign, contradictory,
malformed and over-bound evidence, preserves hard failures and permits only
exact current warning acknowledgements. It authenticates no caller or source
and creates no approval, release, route, profile, runtime grant or artifact.

The candidate also carries #87's truthful post-delivery handoff. Unchanged
browser acceptance was not repeated. Human integrated acceptance remains
separately pending in [#92](https://github.com/martonpornoi/maru/issues/92).

## Exact provenance

- Base: `d9dcd5074af494689912dc1524095b85343f5f2c`.
- Tested head: `a6a9e6b28f985aa0172a0c077732c842e4301717`.
- Protected squash: `60dc9aeb15e306e3d64abd0e76c5a455540402f7`, merged
  2026-09-11 at 00:22:18 UTC.
- Both trees: `604684a42d3cc066ae976cab3fa1889e2772bdce`.
- Clean local main was fast-forwarded to that exact `origin/main` result.
- #91 closed automatically; only its #48 delivery checkbox was completed.

## Verification

Focused regression passed 265 tests; the new rule's 137 cases cover all category
states, exact snapshot identity, hard-failure non-waiver, limits, deterministic
output and immutable results, with 100% statement/branch coverage for the module.

Exact-commit local certification passed all ten gates in 30m01s, using the
selected current-schema scope and eight isolated PostgreSQL databases:

- 7,947 Python tests: 4,391 unit and 3,556 PostgreSQL;
- all nine Python reports had zero failures, errors or skips;
- 64 frontend tests;
- 90.40% combined branch-aware coverage, with the unchanged 90% threshold;
- security, static analysis, Django/API/artifacts, documentation and builds;
- a successful version-2 receipt for the exact head/base, without a split-run
  exception. `CI=true` allowed non-interactive dependency installation.

The [ready-state hosted workflow](https://github.com/martonpornoi/maru/actions/runs/34544298347)
passed the full CI gate and required PR gate. All eight current PostgreSQL jobs
passed in 7m22s–21m46s; complete workflow latency was 24m17s. This is current-path
evidence, not a full-history timing claim. The prior draft-state gate was
superseded by successful ready-state acceptance on the same commit.
[CodeQL](https://github.com/martonpornoi/maru/actions/runs/34542266636) passed all
three languages. Final review found the exact head up to date and mergeable,
with no unresolved conversations. No bypass, rerun or threshold reduction was
used. Existing Django URLField deprecation and OpenAPI enum warnings remain.

Task-owned certification containers were removed and the active CLI watcher
exited successfully. The receipt, reports, logs and coverage parts were retained
under the local ignored evidence archive. No schedule was created, and no
unrelated container, worktree, stash or data was removed.

## Remaining work

#94 implements trusted owner-source collection and missing exact owner evidence.
Persisted independent approval, atomic publication and same-transaction safety
invalidation, shared outputs/change impact, continuity, guided surfaces and
integrated acceptance remain successors. #48 stays open. No deployment,
production readiness, operational owner acceptance or activated profile is
claimed by this delivery.
