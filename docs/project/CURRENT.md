# Current project state

Last updated: 2026-10-10
Phase: Standalone Announcements implementation and pre-production evaluation.

Maru is a Django/PostgreSQL modular monolith under synthetic evaluation, not a
production-ready release or supported hosted service. Furry conventions are the
primary audience. [ROADMAP](ROADMAP.md) owns sequencing;
[checkpoints](../checkpoints/index.md) preserve historical evidence; the
[production ledger](PRODUCTION_CONSOLIDATION.md) owns the release baseline.

## Active direction

The maintainer has deferred completion of Programme umbrella #48 and approved a
broader convention roadmap. First make everyday work understandable to occasional
volunteers, including people whose first language is not English. Continue with
complete optional workflows instead of requiring a convention to adopt all modules.

The approachable-work batch is delivered through
[PR #209](https://github.com/martonpornoi/maru/pull/209), protected main
`e77fae5b94dbee3e7f2e9d64b2f768be95888738`. It groups authorized navigation, makes
activity/application language clearer, hides technical details progressively and
shortens the furry-first contributor path under UX-031 and ADR 0116.

The current batch is [standalone Announcements](../modules/announcements.md):
guided purpose-specific setup, write, independent review, manual publication reports,
corrections and portable downloads. [ADR 0117](../architecture/decisions/0117-standalone-manual-announcements.md)
and ANN-007 through ANN-009 define the boundary. The profile adopts Announcements
plus foundations only, with no Registration, Participation, payment, attendance,
Workforce, Programme or recipient-notification effects. Ordinary publication needs
a different reviewer of the exact draft; copying is not publication. Existing
profile versions and Workforce operator authority remain unchanged.

Implementation and the bounded synthetic browser journey are complete locally.
The earlier development evidence below precedes the successful certification and
current review repair recorded later in this handoff. The
[Announcements checkpoint](../checkpoints/2026-10-09-standalone-announcements.md)
records actual roles, widths, repairs and remaining acceptance limits. The final
native Announcements domain/migration batch passes
27 cases, including real concurrent retries, competing edits, receipt-to-state
integrity, unused uninstall/reapply and retained-history downgrade refusal.
A separate 33-case native foundation batch includes genuine restricted-login
setup, operator acceptance/activation and the approved-copy/report/export workflow.

The final combined database-free suite passed 13,806 cases in 75.81 seconds;
108 frontend cases and generated contracts also passed. Full strict typing, Ruff,
formatting and semantic Python documentation checks passed. Browser verification
used separate synthetic writer/reviewer accounts and a genuine restricted runtime.
The scripts-blocked correction/report/stopped-use path, private/public download
separation and integrity, 320–1,920 pixel layouts, error focus and normal mobile
menu return were verified. A final shared-shell fallback repair passed nine focused
cases after the whole unit run and was included in later full acceptance. Native print,
200-percent zoom, specialist and independent-person acceptance remain open.
These development results and subsequent commit-specific acceptance are not
production activation or independent human acceptance.

Two earlier exact-commit certification attempts exposed joined recovery ordering
regressions; complete failed artifacts and source bundles are preserved. Candidate
`633fab42736d8d34d3112bac23947d19d449b27a` failed when retained Programme history
was checked only after newer Announcements guards had reversed. The first repair
passed 65 units and 20 native cases. Its fresh full run at
`94646aa5180e532d6854d1e16c447e12005cef76` passed that original failure and twelve
native shards, then a bare Programme edition reached Events constraint reversal
before Workforce's existing refusal. PostgreSQL rejected pending trigger events.
No successful certification receipt or aggregate coverage exists for either run.

The follow-up preflight retains that edition before schema alteration; it does not
flush pending triggers or call a mutating reverse operation to check for evidence.
The expanded native batch passed 27 cases; the completed preflight then passed
seven final native cases in 278.43 seconds, including retained representation and
access records before event setup. Final readiness/recovery units pass 65 cases.
Both disposable databases were removed. These focused repairs preceded the
successful full run recorded below; [the repair checkpoint](../checkpoints/2026-10-09-announcements-recovery-fence.md)
retains exact failure and repair evidence.

## Announcements scheduling repair

Commit `0eabf43b421804aed1ef7db7bec0c5603f7c299c` failed full certification
on measured timing headroom after 63 native shards passed. Shard 64 passed all
three test bodies but exceeded 3,200 seconds during final restoration. Its full
4,694-file evidence tree, console and exact source archive are preserved and
hash-verified; no successful receipt exists. An unchanged single-shard diagnostic
then passed all three cases and cleanup in 2,279.203 seconds, removing its owned
container. That diagnostic does not replace full concurrent acceptance.

ADR 0098 now limits each budgeted shard to two complete historical groups as well
as its existing cost budget. The same 374 groups, including 106 historical groups,
produce 77 rather than 74 jobs; maximum concurrency remains eight and every
runtime/coverage requirement remains unchanged. The estimates and provenance map
are untouched. [The scheduling checkpoint](../checkpoints/2026-10-09-historical-shard-density.md)
records the diagnostic and preserved failure. The repair passes 121 focused
policy cases and all 13,816 unit cases in 73.91 seconds; lint, formatting,
documentation references and its Python documentation contract passed. At that
stage, full certification and hosted acceptance remained and PR #210 was draft.

That fresh run at `7cb0a071c53787dbcbd580828e0e487185a4e2c8` exposed a separate
execution defect: the runner validated the new plan but then repartitioned without
its density constraint. Fifty-eight of 73 started shards selected different groups
from the saved manifest. The run was orderly-cancelled after 65 passing subsets;
eight workers were interrupted, four shards never started, and all owned databases
were removed. Its complete 4,711-file evidence tree and exact source are preserved.
No successful receipt exists. The runner now consumes the validated assignments
directly; a main-path regression reproduces the original mismatch. The
[execution checkpoint](../checkpoints/2026-10-09-frozen-shard-execution.md) records
the repair and its then-pending full acceptance. Its main-path and policy regression batch
passes 122 cases; all 13,817 database-free units pass in 76.20 seconds. Canonical
typing, lint, formatting, Python documentation and documentation references pass.
Real CLI checks match four selected shards and all 374 planned assignments.
Candidate `dccd7dcd9c43198b7864b9aed135e667c394d43b` subsequently passed the
complete local required certification in 17,220.652 seconds: all 77 PostgreSQL
shards, at most eight concurrent databases, and 91.586053% combined coverage.
Independent hosted acceptance also passed all 77 PostgreSQL jobs, PR gate and
CodeQL. Its successful local evidence is preserved in the original checkout under
`.tools/certification-evidence/announcements-local-dccd7dc-success/preservation.json`.
PR #210 is now non-draft. The maintainer has authorized protected merge after the
new review repair passes fresh exact-head local and hosted gates.

## Announcements review repair

PR #210's review repair closes generic edition creation for `announcements_only@1`.
The dedicated setup retains its current profile checks, purpose-specific operator
provisioning and complete retry receipt. Generic HTML/API choices omit it and the
shared command refuses crafted requests before persistence. The Events 0019
description now accurately states its persisted profile and receipt changes.
ANN-007 and ADR 0117 remain the governing contract; no migration operation,
runtime grant or existing profile manifest changes.

The repair passes 257 focused database-free cases, including both actual adapters,
the real dedicated/child command composition with mocked persistence, exact replay
and scope reset after failure. Focused strict typing, Ruff, generated API contracts
and TypeScript checking pass. Native UI/API regression cases are added but remain
unexecuted at this checkpoint. [The review checkpoint](../checkpoints/2026-10-10-announcements-setup-admission.md)
records the boundary and evidence.

The fresh full run at `c5f053661bd989e5c719c09e5983e513fdc3595d` failed after
721.109 seconds. All 13,825 database-free units and non-database gates passed,
but 25 Announcements native setup cases refused a stale whole-source migration
fingerprint. The earlier documentation correction changed Events 0019's two
docstrings without updating its reviewed source pin. The eight owned pool
containers were removed; failed evidence remains retained, with no successful
receipt or aggregate coverage for that run.

The bounded follow-up updates only that reviewed source fingerprint. Comparison
with `dccd7dcd` confirms identical migration operations after removing only the
two docstrings; native SQL/catalog hashes and grants are unchanged. Three new
unmocked source-contract checks reproduce the stale pin before repair. The repaired
focused batch passes 312 cases in 2.57 seconds, plus strict focused typing, Ruff,
formatting and Python documentation checks. The
[source-pin checkpoint](../checkpoints/2026-10-10-announcements-migration-source-pin.md)
records the audit and limits. Fresh full exact-commit local certification and
independent hosted acceptance remain required before the authorized protected
merge. Preserve failed artifacts before replacing `.local-ci/`; older passing
receipts cannot certify this repair.

## Starting baseline and verification

PR #209 passed complete local and independent hosted acceptance before protected
merge; source, tested merge and squash trees matched. Its site deployment and
signed-out newcomer path were verified. The
[implementation checkpoint](../checkpoints/2026-10-08-approachable-convention-work.md)
and [verification follow-up](../checkpoints/2026-10-08-approachable-convention-verification.md)
retain exact commits, counts, timings and failed-attempt evidence. Those results
certify PR #209, not the Announcements candidate.

Follow [local certification](../development/local-certification.md): focused
feedback, complete inexpensive units, then one clean exact-commit required run
with `CI=true`, pinned pnpm 11.9.0, unchanged coverage and measured headroom.
Preserve failed/interrupted evidence before replacing `.local-ci/`. At most eight
native databases may run concurrently; do not overlap a populated rehearsal with
the full pool. Hosted acceptance remains independent of the local receipt.

## Programme work retained for later

#48, #92, #109 and #108 remain open. Deferral is not acceptance or activation.
Use the [evidence map](../operations/programme-acceptance-evidence.md),
[maintainer walkthrough](../operations/programme-maintainer-walkthrough.md),
[human session cards](../operations/programme-human-acceptance.md), and
[archive runbook](../operations/programme-exit-archive.md) when explicitly returning
to this work. The October 5 print-preview and verified-HTML observations remain
limited maintainer reports, without a supplied browser/version or startup commit.

Independent-person, specialist screen-reader and operational-owner acceptance,
#109 reconciliation, and #108 promotion are separate gates. Native print/offline,
archive, restore and browser results retain their own recorded scope. Assistant
accounts are not independent people. Production/PITR, capacity, safeguarding,
training and go/no-go remain separate. No production profile, routes or data are
activated. Retain the user's disabled Windows Animation effects.

`programme_operations@1` remains limited to Applications, Programme, Scheduling,
Venues and Workforce plus required foundations. No Registration, Participation,
payment, attendance, Logistics or general Communications effects may be inferred.
Purpose-specific authority, owning commands and independent approval still apply.

## Smallest next actions

1. Freeze the coherent Announcements batch and run one clean exact-commit
   required certification, then independent protected delivery. Preserve previous
   evidence before replacing local receipts; keep the populated fixture stopped.
2. Resolve the explicit adoption-expansion and purpose-specific authority contract
   alongside Guidance so an existing event can add that workflow safely. Do not
   widen a v1 manifest, grant new control implicitly or duplicate an event.
3. Continue guidance/help desk, volunteer and fursuit/accessibility services, then
   the remaining [roadmap](ROADMAP.md) journeys. The maintainer has requested
   continuous work until explicitly stopped; routine product choices are delegated.

The original Programme checkout and unrelated worktrees, stashes and resources
must remain untouched. In particular, do not reapply already-applied stashes
`5b6851f`/`dd651ef` or remove unrelated `3cc5df`/`9fecfe` and isolated P12/#96 work.
No new automation, production deployment or broad Docker cleanup is authorized by
this batch. Remote repository description/topics remain a separate settings change.
