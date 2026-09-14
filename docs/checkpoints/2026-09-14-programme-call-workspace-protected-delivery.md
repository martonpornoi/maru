# Programme call workspace protected delivery

Date: 2026-09-14
Outcome: First Applications manager increment of #108 delivered under #48.

## Exact boundary

- PR: [#115](https://github.com/martonpornoi/maru/pull/115).
- Base: `bf990ff66714b568c9c59dbb6768ea0cc5ddf708` (PR #114).
- Certified head: `5d5aa6d502f00fa8ae23e0cdcdfed19f34639840`.
- Protected squash: `ae97565ff03005a730ef8d492e2a1f72b04318e7`.
- Merged: 2026-09-14 03:22:08 UTC.
- Certified and squash tree: `0d59086a54efc807d0245bd721a093e99e1cb512`.

The exact candidate was CLEAN/MERGEABLE with no review threads or further pages,
green PR gate and all three CodeQL language analyses before head-matched squash.
The clean main checkout fast-forwarded only; local main and origin/main equal
the protected squash. The unrelated repair worktree, stashes and containers were
untouched. No subagent, reminder, production route or profile was enabled.

## Verified evidence

All eight retained local gates passed in 957.328s (15m57s), completed at
2026-09-14 02:48:54 UTC. Full Python units passed 6,171 cases in 37.58s; JUnit
records 37.315s, zero failures, errors or skips. Two existing Django URLField
deprecation warnings remain. Full frontend acceptance contains 81 cases across
six files. Static, typing, NumPy documentation, warning-fatal Sphinx, packaging,
generated/API and security gates passed.

The first candidate `06fca34fb38dc02e2ec26d1cc8083daeb449956c` failed the historical
kernel-only template-containment assertion with 6,165 passing units and one
failure. No success receipt was created. The narrow exact-template allowance and
new whole-production-URL-tree/non-spreading guards passed 58 targeted cases;
all 6,171 full unit preflight cases then passed in 37.28s before fresh exact
certification. The [implementation checkpoint](2026-09-14-programme-call-workspace.md)
retains the detailed scope and synthetic-browser evidence.

Hosted Pull request run `34800556323` passed the exact candidate:

- Python job `103842255178`: 6,171 tests in 77.70s; total job 1m42s.
- Quality job `103842255272`: 29m36s.
- PR gate `103847168360`: two seconds, success.
- Workflow: 02:50:37 through 03:20:37 UTC, 30m00s overall.
- CodeQL run `34800554382`: all three language analyses passed.

Quality had only 24 seconds remaining against its 30-minute limit. This is a
concrete near-limit observation, not guaranteed headroom. #113 comment 5658538278
records it alongside earlier latency and early-unit ordering evidence. No CI
policy or timeout was changed in this feature increment.

Five receipt/plan/unit/package files were copied and SHA-256 compared against
their sources in `.tools/certification-evidence/issue108-5d5aa6d-deferred/`.
Receipt SHA-256:
`15f9336d612abe1680fa037be63c8825fee70f796dfc4c86ba06f45d50c231ea`.
Policy SHA-256:
`36354f14eabc58fa31ae7b2d7ec0e9a5e7afb8ab2c4b48bfa02a1edeff5f528d`.

The schema-4 result is `postgresql_deferred`: no PostgreSQL execution, zero
database instances and null combined coverage/measured timing headroom. No
schema-only check ran. The local receipt is not the independent hosted gate,
and neither is activation or production approval.

## Delivered and remaining

Exact-Department labelled inventory and complete configuration now have explicit
metadata/policy, deadline, ordered catalog and lifecycle tasks over existing
owner commands. Lossless reconstruction preserves untouched typed graphs;
original cursors, retry intent and edition-zone versions remain fenced.

Two maintained native cases remain unexecuted under #102 (comment 5658319886).
Human widths, genuine zoom, keyboard, screen reader, touch, native discard and
operator comprehension remain unchecked #92 tasks (comment 5658320007). The
synthetic database-refusing fixture servers and tabs were stopped.

#108 comment 5658537975 and #48 comment 5658538111 reconcile delivery. Both issues
remain open; the Applications checkbox remains unchecked. Next are call creation
and full section/question/condition editing, then Department selection and
reassignment, proposals/collaboration/review/decisions/conversion, connections
and accountable setup. #109/#102/#97/#92 still gate final promotion.
