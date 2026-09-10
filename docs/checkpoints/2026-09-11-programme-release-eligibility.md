# Programme release eligibility prerequisite

Date: 2026-09-11

## Outcome and decision

Issue [#91](https://github.com/martonpornoi/maru/issues/91), a native child of
[#48](https://github.com/martonpornoi/maru/issues/48), separates complete
release eligibility from the intentionally partial planning conflict report.
ADR 0094 and SCH-012 define ten mandatory current-source categories, explicit
applicability, exact-snapshot warnings and the protected publication successors.

The Scheduling-owned pure evaluator requires typed immutable bounded evidence,
preserves unavailable/stale/blocked states and deterministic results, and refuses
unknown, duplicate, over-bound, mismatched or contradictory input. Acknowledged
warnings cannot waive hard failures. It performs no database or external work,
authenticates no owner evidence, and confers no approval or publication authority.

## Focused evidence

- 265 new/existing release, conflict, catalog/authorization and owner-seam unit
  cases passed in 1.64 seconds; the new rule module had 100% statement and branch
  coverage at the unchanged 90% threshold.
- After correcting the docstring validator's exception-factory ambiguity, all
  137 rule tests passed again in 0.76 seconds with 100% statement/branch coverage.
- Focused strict type checking and documentation validation passed. Lint found
  stylistic no-argument exception parentheses after that correction; these are
  normalized before the clean candidate is certified.
- No browser journey changed, so this child requires no new manual interaction.
  These focused results do not claim full certification or hosted acceptance.

## Scope and recovery

There are no migrations, runtime-role changes, mounted adapters, profiles,
routes, APIs, workers, artifacts or release records. No unrelated module is
queried or changed. Code rollback has no newly created durable state to undo.
The earlier #87 post-delivery handoff remains part of this branch's initial
documentation commit; its completed browser checks are not repeated.

## Successors and remaining gates

The next release child must resolve and authorize complete owner sources,
including explicit no-staffing decisions and exact accessibility-fit evidence,
persist independent approval and publish/invalidate atomically. Shared
release-derived outputs and change impact follow. On-site continuity must be
honest about disconnected and printed-copy freshness; guided activation and
integrated acceptance remain mandatory. No part of #48 is declared production
ready by this rule-only prerequisite.

The maintainer authorized sequential protected delivery without routine
confirmation. Genuine human acceptance remains a separately tracked later
subtask, not a waived gate. Exact-head local certification and independent
GitHub acceptance are still required before merge; delivery provenance belongs
in the later protected-delivery checkpoint and maintained current handoff.
