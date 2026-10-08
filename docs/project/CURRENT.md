# Current project state

Last updated: 2026-10-08
Phase: Approachable convention workflows and pre-production evaluation.

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

The first coherent batch implements [UX-031](../product/requirements.md)
and [ADR 0116](../architecture/decisions/0116-approachable-convention-work.md):

- One authorized menu, grouped by purpose; clear current event, search, pins,
  current-group expansion, and secondary Advanced records.
- Team workspace and activity-idea language; technical details are expandable.
  Required choices, consent, approvals, errors, and event scope remain visible.
- A shorter furry-convention introduction, truthful maturity guidance, and one
  verified newcomer setup path. Existing ADRs and checkpoints are retained.

This is presentation and documentation work. No schema, permission, profile
activation, API identifier, or cross-module side effect is introduced. Policy
reference codes with no approved choice catalog still require explicit input;
this change explains them rather than inventing a default. The
[batch checkpoint](../checkpoints/2026-10-08-approachable-convention-work.md)
records evidence and remaining limits. Exact-commit certification and independent
protected checks must pass before this batch is delivered.

## Verified baseline and current feedback

[PR #208](https://github.com/martonpornoi/maru/pull/208) merged on October 6 at
`1fc8a216c96a7a42e7ab1f3bcec206eae50a1426`. It delivered 24-hour deadline entry
and the bounded source-map-js security repair. Its exact source `5b53f21` passed
local and hosted acceptance: 18,491 Python cases, 103 frontend cases, 30 required
PostgreSQL shards, and 91.61% combined coverage. That evidence certifies the
previous source, not this batch. Earlier PRs #199, #201, #202, #204, #206 and #207
remain delivered; their historical attempts must not be restarted as current work.

Current development feedback passes all 13,588 Python units and 108 frontend
cases. Expanded database feedback passed 129 cases; its one stale label assertion
was corrected and the remaining case passed separately. The first exact candidate
`40bac23` passed every non-database gate but stopped when an Applications journey
still expected the old form-studio label. Twenty-one database shards passed; seven
active shards were interrupted, not accepted. All 29 started databases were removed
and complete failed evidence plus source were preserved. The
[verification follow-up](../checkpoints/2026-10-08-approachable-convention-verification.md)
records the bounded expectation repair: all 14 affected Applications integration
cases pass, and their owned database and volume are removed. A fresh complete
certification remains required. No production behavior, timeout, coverage threshold
or authorization test is relaxed. A fresh disposable database applied migrations;
ordinary sign-in, event selection, Team workspace, and technical setup disclosure
were checked in a real local browser. Synthetic template checks cover seven widths
and keyboard navigation. These observations are assistant-operated and do not
prove independent-person comprehension or specialist accessibility acceptance.

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

1. Finish exact-commit local certification and protected review for the coherent
   usability/contributor batch; record the final head and delivery evidence.
2. Define and deliver a bounded announcements workflow, followed by convention
   knowledge/helpdesk and volunteer, fursuit and accessibility services. Each needs
   its own complete journey and modular-adoption contract before implementation.
3. Continue dealers, charity auctions, arrival exceptions, hospitality and
   continuity in the [roadmap](ROADMAP.md), carrying the same plain-language rules.

The original Programme checkout and unrelated worktrees, stashes and resources
must remain untouched. In particular, do not reapply already-applied stashes
`5b6851f`/`dd651ef` or remove unrelated `3cc5df`/`9fecfe` and isolated P12/#96 work.
No new automation, production deployment or broad Docker cleanup is authorized by
this batch. Remote repository description/topics remain a separate settings change.
