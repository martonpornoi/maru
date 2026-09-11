# Programme release-source certification corrections

Date: 2026-09-11
Issue: [#94](https://github.com/martonpornoi/maru/issues/94), child of #48

## Failed candidate and retained evidence

Exact candidate `a4cdc7a6d8390f6ec554db1deace1366f5df69ce`, based on protected
`60dc9aeb15e306e3d64abd0e76c5a455540402f7`, did not certify. Its full unit report
contained 4,496 passes and seven failures, with no errors or skips. Exact older
catalogs omitted the new operation/relation/model/guard entries; the maintained
runtime-role provisioning SQL also omitted the new relation from its explicit
SELECT grant and write revocations. The latter is an operator-artifact omission,
not merely a stale test expectation.

Fresh warning-fatal Sphinx passed, as did 64 frontend tests and the non-database
command stages. The eight PostgreSQL workers were deliberately stopped after
the conclusive unit failure to avoid continuing a candidate that could not
certify. Their parent reported failure and removed its own disposable services.
No completed PostgreSQL result, combined coverage or success receipt is claimed.
Failure logs, selection evidence and the unit report are preserved outside the
disposable certification directory. Unrelated resources were not stopped.

## Correction boundary

The exact inventories now include the new placement relation, both closed
operations, the model's owner-managed relation names, 59 triggers and 24 guard
functions. The SQL grants only SELECT and explicitly revokes writes from both
PUBLIC and the runtime role. No runtime writer, execute allowlist, profile,
route, threshold or test exemption is expanded.

Recovery tests also enumerate the exact unused 0013–0015 successors that normal
Django reversal may remove before reaching an older populated owner fence.
The staffing case preserves exact retained data, recorder state and the older
guard contract; it distinguishes partial-graph unreadiness from a successful
return to current readiness after normal reapplication. The runbook documents
this existing migration-executor behavior rather than promising whole-graph
rollback after a later fence refuses contraction.

## Verification and next action

All 4,503 unit tests pass after correction, with no failures, errors or skips.
The focused real provisioning and populated owner-recovery run passed nine cases
and failed one older staffing expectation in 13m30s. The failure proved that the
unused Workforce binding migrations 0019–0021 also reverse before the populated
Programme staffing fence. The test now enumerates those exact successors, with
no blanket exemption; its rerun passed in 2m24s. All original guard, data and
recorder assertions remain, with explicit current-graph recovery added. The nine
unchanged cases include actual atomic runtime-role provisioning and all older
conversion/Scheduling fence targets.

The existing edition-creation suite separately passed all 38 cases in 2m29s.
That diagnostic followed an initially incorrect mapping of an interrupted dot
progress line; complete ordered collection identified the two recorded failures
as the older host-populated conversion fences, both now passing in the focused
group. No unrelated edition behavior changed. Ruff and maintained-document
validation passed. These separate focused reports are not a combined or exact-
commit certification receipt.

A fresh exact-commit exhaustive certification and independent
hosted protected acceptance are still required. #94 is not yet delivered;
approval/publication, output/continuity, guided setup and #92 remain successors.
