# Programme decision and hosting workspace protected delivery

Date: 2026-09-14
Outcome: Second #108 guided increment merged under #48; not activation.

## Exact delivery boundary

- PR: [#114](https://github.com/martonpornoi/maru/pull/114).
- Base: `f64c96ed7e1912121de476d6ad4332b4c330b448` (PR #112).
- Certified head: `41e189177f7ce4ddeb1b0c2374387dbfd8bb6173`.
- Protected squash: `bf990ff66714b568c9c59dbb6768ea0cc5ddf708`.
- Merged: 2026-09-14 01:16:20 UTC.
- Certified and squash tree: `5a50ba70e049ba84e5e520ad86e6b134b4c202f5`.

The exact head had CLEAN/MERGEABLE state, no review threads or further review
pages, and green protected PR gate and CodeQL before the head-matched squash.
The clean main checkout was fast-forwarded only; local main and origin/main
equal the protected result. The primary feature worktree was clean; the unrelated
repair worktree, stashes and containers were untouched. No reminder or subagent
was started.

## Verification

Fresh schema-4 local certification passed all eight retained gates in
979.338 seconds (16m19s), completed at 2026-09-14 00:47:31 UTC. Full units passed
6,020 cases in 38.39s; JUnit reports zero failures, errors or skips and 38.258s.
The two Django URLField deprecation warnings are existing warnings. Full-source
mypy passed 596 modules. Full frontend, warning-fatal Sphinx, generated/API,
packaging, dependency/security and static/docstring gates passed. The earlier
`4dd0e7e18da3b71625799d3b9eeec2c22f9bc199` typing failure and its five-call-site
repair remain honestly documented in the
[implementation checkpoint](2026-09-14-programme-decisions-and-hosting.md).

Hosted Pull request run `34793853271` passed at the exact head:

- Python unit job `103823117790`: 6,020 tests in 65.61s; total job 1m24s.
- Quality job `103823117798`: 25m34s; documentation build succeeded and frontend
  passed 76 cases across five files.
- PR gate `103827055896`: four seconds, success.
- Workflow: 00:48:34 through 01:14:45 UTC, 26m11s overall.
- CodeQL run `34793851752`: all three language analyses passed.

Hosted quality was faster than PR #112's 28m07s and PR #111's 27m54s, without a
CI change in this increment. It is an observation, not guaranteed future
headroom. #113 remains the separately documented quality-latency follow-up.

Six exact evidence files were copied and SHA-256 compared against their source
under `.tools/certification-evidence/issue108-41e1891-deferred/`, including the
receipt, plan, unit report and package artifacts. Receipt SHA-256:
`3da3da3d27ff8a4a911907858ab529aee763449ce9a4fba9c9b80e8226819e71`.
The receipt binds policy SHA-256
`36354f14eabc58fa31ae7b2d7ec0e9a5e7afb8ab2c4b48bfa02a1edeff5f528d`.

Its result is truthfully `postgresql_deferred`: false PostgreSQL execution,
zero databases and null combined coverage/measured headroom. No database suite
or schema-only check was run. Local receipt success is distinct from independent
hosted acceptance; neither is Programme activation or production approval.

## Delivered and remaining outcomes

Department discussion, independently readable typed evidence references, exact
reasoned public-copy withdrawal, organizer host invitation/reinvitation/removal,
and person-owned invitation response/availability/history are dormant adapters
over the existing owners. The synthetic browser/HTTP/JavaScript evidence and
corrected timezone, pending-row and explicit-evidence behaviors are retained in
the implementation checkpoint and page contracts.

Four maintained native cases remain unexecuted #102 debt (comment 5657375804).
Representative human, genuine zoom, keyboard, screen-reader and native-discard
acceptance stays explicitly unchecked under #92 (comment 5657375935). The fixture
servers and tabs were stopped/closed. No current profile, production route,
schema, runtime privilege or invitation email delivery was activated.

#108's matching guided-delivery checkbox is complete; #108 and #48 remain open.
#48 comment 5657705300 records the delivery and next priority. Continue dedicated
Applications calls/proposals/collaboration/review/conversion, then authorized task
connections and accountable setup. #109/#102/#97/#92 still gate final promotion.
