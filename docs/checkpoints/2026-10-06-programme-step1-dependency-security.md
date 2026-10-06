# Programme step 1 dependency-security repair

**Date:** 2026-10-06\
**Status:** Focused repair applied; fresh certification and protected delivery pending\
**Scope:** PR #208 transitive frontend dependency, NFR-011 and ADR 0064

## Failure and preserved evidence

Clean source `64d08a35cf1e298f237a7a9960c07750ea6ff38f` passed required Auto
local certification against `dec2ca5f52613eb7706f37388ba0283a9596481c` on October 5
at 19:26:55 UTC. All ten gates passed in 1h04m47s: 18,491 Python cases,
103 frontend cases, all 30 required current-history PostgreSQL shards, 91.61%
combined branch-aware coverage, measured headroom and owned cleanup. The ordinary
4,762 artifact files and three wrapper files are archived under
`.tools/certification-evidence/programme-local-64d08a3-success`; all 4,765 hashes
were reverified before preparing this repair. That receipt certifies its old head.

[Hosted run 37366816960](https://github.com/martonpornoi/maru/actions/runs/37366816960)
attempt 1 could not acquire a hosted runner during GitHub's October 5 incident.
After service recovery, all jobs were rerun on the unchanged head at
2026-10-06 15:00:11 UTC. Attempt 2 acquired runners but its dependency-security
job `112338565846` failed on the high-severity
[GHSA-68fv-2mgg-jv7q advisory](https://github.com/advisories/GHSA-68fv-2mgg-jv7q).
Python auditing passed; the frontend audit found `source-map-js` 1.2.1 through
PostCSS and css-tree. Required unit, PostgreSQL and combined coverage stages
did not run, and both acceptance and PR gates correctly failed.

Two normal cancellation requests for the remaining documentation job returned
HTTP 502. The attempt then finished normally; its completion was confirmed before
editing tracked source. Seven original failure, completion, gate and local-audit
evidence files are SHA-256-manifested under
`.tools/certification-evidence/programme-hosted-64d08a3-attempt2-security`.
The earlier runner-failure archive remains separate. No failed evidence or
unrelated worktree was discarded.

## Bounded repair

Pinned pnpm 11.9.0 regenerated only the affected lockfile package entry and its
PostCSS/css-tree references, moving `source-map-js` from 1.2.1 to the upstream
patched 1.2.2 release. The direct dependency manifest, existing bounded overrides,
Actions, vulnerability thresholds and application source are unchanged. This
implements the existing NFR-011/ADR 0064 supply-chain contract; no new ADR,
migration, runtime permission or production setting is required.

The current audit reproduced the finding on the original lock. The repaired lock
reports zero vulnerabilities. An isolated preliminary frontend run omitted the
backend static assets that six test files read and consequently failed with
missing-file errors; its log is retained, not counted as acceptance.

Real-checkout frozen installation and auditing passed, followed by all
**103 frontend cases** in **16.53s**, TypeScript checking and the production build.
No generated browser artifact changed. The first inexpensive Python unit run
encountered Windows access denial in the shared `pytest-of-TheMw` temporary
directory: 13,067 cases passed and 492 fixture setups errored. The log and JUnit
report remain preserved. A fresh workspace-owned `--basetemp` then passed all
**13,559 units in 73.14s** with three existing Django URLField deprecation warnings
and no failures or errors; no tests, fixtures or permissions were changed.
Documentation validation passed for 718 Markdown files, four repository skills
and 215 unique requirements, and whitespace validation passed. These focused
checks do not replace the new exact-commit certification.

## Delivery boundary

PR #208 remains the same pull request and has returned to draft while the repair
is certified. Fresh ordinary exact-head Auto certification must pass before
marking it ready, followed by independent current-head hosted acceptance, PR gate,
CodeQL, current-base mergeability and resolved conversations. Use the authorized
exact-head squash into `main`, verify equal trees, and synchronize only a clean
main checkout. Do not overlap the eight-database pool with a populated rehearsal.

The maintainer already reported the core journey, browser print preview and
generated `initial.html` displayed correctly and the instructions were followable.
Those bounded observations remain recorded; no repeat is requested. Step 2 under
#92 still requires representative people, accessibility and operational acceptance.
Keep #48, #92, #109 and #108 open; this repair does not activate production.
