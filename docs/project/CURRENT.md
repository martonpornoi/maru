# Current project state

Last updated: 2026-10-09
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

Implementation and the bounded synthetic browser journey are complete locally;
exact-commit certification and protected delivery remain. The
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
cases after the whole unit run; final certification will include it. Native print,
200-percent zoom, specialist and independent-person acceptance remain open.
Exact-commit certification and hosted acceptance still remain; these development results are not production activation or independent
human acceptance.

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
