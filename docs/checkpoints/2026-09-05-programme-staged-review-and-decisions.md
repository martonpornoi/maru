# Programme staged review and accountable decisions

Date: 2026-09-05
Issue: [#71](https://github.com/martonpornoi/maru/issues/71), child of
[#48](https://github.com/martonpornoi/maru/issues/48)
Foundation: protected main `ed1ea859ea23cd75796690e0e1baf600a95d0668`

## Outcome and contract

Applications implements a dormant exact-submitted-seal review kernel under
PRG-003/PRG-004 and accepted ADR 0085. Explicit immutable policies pin ordered
stages, question allowlists, rubrics, quorum, discussion/anonymity rules, and
decision templates. Named assignments require self-cleared conflicts;
independent scores, discussion, moderation, stage reopening, decisions, and
individual recipient acknowledgements retain attributable evidence.

Manager, reviewer, moderator, decider, and recipient projections have separate
field ceilings. Managers receive assignment context, not answers or scores.
Anonymous review is a documented projection, not guaranteed de-identification
of submitted prose. Restricted content requires independent sensitive-review
authority. Recipients see only the pinned template plus deliberately addressed
message and their own acknowledgement, never private rationale or peer state.
Exact recipient history survives subsequent contributor removal, withdrawal,
and Department retirement.

Acceptance is review-side evidence only. New seals require new cases; late
recusal, withdrawal, reopening, or supersession cannot silently preserve an
effective acceptance. No target receipt, Programme item, host, occurrence,
Shift, publication, UI, API, profile, root role, or delivery handler is created
or activated. Generic review/target fences remain closed. Umbrella #48 and its
integrated Programme-only browser/on-site acceptance remain open.

## Integrity, recovery, and race repair

Authorization `0024` and Applications `0013` through `0015` add the closed
capability vocabulary, seven runtime SELECT-only relations, 32 new triggers,
four new functions, and a populated downgrade fence. Every successful command
couples state, immutable receipt, minimized audit, domain event, and outbox in
one transaction. The shared retry namespace excludes collisions among generic,
Programme intake, import, and review commands.

Applications readiness composes all earlier guards with the new closure:
40 relations, 134 triggers, 27 functions, 437 constraints, and 303 indexes.
Constraint and index fingerprints were collected from a freshly recreated
PostgreSQL 17 schema. Real migration execution verifies empty reversal and
reinstallation; retained evidence refuses downgrade before any guard or table
is removed. Helper volatility and PUBLIC-execute drift fail readiness and
transactional restoration recovers the original contract.

Forced separate-connection source/decision races exposed an existing inversion:
proposal self-write authorization could lock an edition before the organization,
opposite to review's canonical chain. Self writes now acquire shared barriers,
Organization, ConventionSeries, EventEdition, and the edition mutex before actor
and relationship locks. The self path requires no current Department. Both
source-first and decision-first withdrawal/reopening cases execute real commits
and retain the exact historical decision without deadlock or false acceptance.

Recovery is compatible fix-forward or a reviewed consistent-point restore of
source, authority, audit, effects, and migration evidence. No review purge,
partial history rewrite, production retention executor, or production-data
approval is introduced. The owning runbook documents this boundary.

## Verification evidence and delivery boundary

- All 2,824 unit tests pass; the latest run took 11.18 seconds.
- The final transition/race group passes all 41 cases in 111.63 seconds,
  including both source/decision orders, exact new-seal cases, immutable policy
  versions, a maximum-sized deliberately addressed message, and refusal to
  manufacture acknowledgements when the template does not require them.
- Focused real PostgreSQL groups also cover 20 raw-SQL/evidence rollback cases,
  12 disclosure cases, two service journeys, and four migration/readiness cases.
  Earlier comprehensive focused evidence passed 115 tests in 227.07 seconds;
  additional boundary cases were subsequently added and verified separately.
- Strict mypy passes all 425 source files. Repository-wide Ruff formatting/lint,
  maintained-document navigation, semantic Python docstrings, NumPy docstrings,
  and a fresh warning-fatal Sphinx/AutoAPI build pass.
- Django reports no migration drift. Local system checks retain only the
  existing unavailable invitation-encryption warning; invitation delivery stays
  fail-closed, and no deployment secret was supplied for this kernel test.
- All 191 integration files have measured scheduling weights. The six new
  file weights come from completed passing file groups, not guessed duration
  values. No test selection, coverage floor, or timeout was weakened.

This checkpoint records focused implementation evidence before delivery, not a
substitute for acceptance of the final commit. The PR must carry successful
default eight-shard exact-head local certification and independently green
protected hosted checks. Its final receipt and PR record identify the exact
certified commit; browser acceptance is deliberately not claimed for a kernel
with no mounted surface.

After protected merge, synchronize clean main, reconcile #71 in umbrella #48,
and stop. The next separately authorized child is exact accepted-item conversion,
before hosts/co-hosts and availability, Scheduling, interactive timetable editing,
staffing, release/continuity, and composite adoption rehearsal.
