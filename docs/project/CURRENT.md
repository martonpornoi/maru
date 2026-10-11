# Current project state

Last updated: 2026-10-10
Phase: Developer workflow improvements before Guides.

Maru is a Django/PostgreSQL modular monolith for furry-convention operations,
under synthetic evaluation. It is not a production-ready release or supported
hosted service. [ROADMAP](ROADMAP.md) owns sequencing; the
[production ledger](PRODUCTION_CONSOLIDATION.md) owns release readiness.

## Active outcome

Make a fresh checkout easier to start, inspect in the browser, and verify.
The bounded batch adds a disposable local preview around the existing demo seed,
prerequisite checks, startup timings, a short browser tour, and a documented
focused-check/browser/full-certification loop. It preserves permission boundaries,
coverage, historical migration acceptance and protected delivery. No feature,
profile, migration, production setting or agent permission mode is changed.

The [local guide](../start-here/run-locally.md) owns usage and limits. The
[workflow guide](../development/agent-workflows.md) owns reusable procedure under
ADR 0079. This implements NFR-001, NFR-002, NFR-003, NFR-011 and the existing
educational demo boundary; it does not establish exact authority provenance.
Local implementation and browser checks pass. Full exact-commit certification
and independent hosted delivery remain outstanding; no PR exists for this batch.
Detailed evidence and limits are tracked in the
[workflow checkpoint](../checkpoints/2026-10-10-developer-workflow.md).

## Testing-policy follow-up

The maintainer requested including testing-efficiency work in this same branch
before creating its PR. The existing nightly/manual full workflow and release
gate are retained. The standalone preview launcher now selects current behavior
instead of unrelated exhaustive history; unknown scripts and shared safety/test
machinery remain exhaustive. Routine guidance uses Auto rather than forcing Full.
This policy-changing candidate still needs new exact-commit exhaustive evidence.
The previous a4bb1e8 exhaustive run passed all 77 database batches, all ten
gates and 91.59% branch coverage in 4h28m; its artifacts remain baseline evidence,
never certification of the changed source. The 178 focused classifier, history,
nightly and preview tests passed. Final exact-commit certification and hosted
delivery of the policy follow-up remain pending.
Database template/cloning optimizations remain proposals, not implemented gains.
Demo coverage is unaffected by this policy change.

## Incremental demo coverage

The maintainer wants one ongoing and one future fictional edition, eventually
prefilled for every available UI function. Extend this coverage with each relevant
feature, or state its remaining gap; unrelated commits should note no effect.
The [demo direction](../modules/demo-data.md#maintained-interactive-demo-direction)
owns that accepted intent. This batch records the maintenance rule only: no seed,
event date, running preview or feature data has changed. Guides is the next
product journey to consider for sample coverage after workflow certification.

## Delivered baseline

[PR #209](https://github.com/martonpornoi/maru/pull/209) delivered purpose-based
navigation, plainer language, progressive technical details and the furry-first
contributor path under UX-031 and ADR 0116.

[PR #210](https://github.com/martonpornoi/maru/pull/210) merged on October 10 at
15:30:56 UTC as `7e363933e964fc20c1676bde77e1359c643fa00e`. Announcements supports
purpose-specific setup, writing, independent review, manual publication records,
corrections and portable downloads under ANN-007–009 and ADR 0117. It introduces
no Registration, Participation, payments, attendance or automatic notifications.

The exact candidate `168622fb4c9142051074e7297c5515b3d82fec59` passed full local
certification and independent hosted acceptance, including all 77 PostgreSQL
jobs, PR gate and CodeQL. Both review conversations were resolved; the merged
tree matched `9be64bfb4fe7dd66f5541ed2f426a561859cb460`. The clean main checkout
was synchronized and its merge heartbeat stopped. These results certify PR #210,
not this new workflow batch or production use.

Preserved historical evidence remains in the Announcements checkpoints:
[implementation](../checkpoints/2026-10-09-standalone-announcements.md),
[recovery fences](../checkpoints/2026-10-09-announcements-recovery-fence.md),
[shard density](../checkpoints/2026-10-09-historical-shard-density.md),
[frozen execution](../checkpoints/2026-10-09-frozen-shard-execution.md),
[setup admission](../checkpoints/2026-10-10-announcements-setup-admission.md), and
[source pin](../checkpoints/2026-10-10-announcements-migration-source-pin.md).
Retain failed/interrupted artifacts; earlier passing receipts never certify a
later repair.

## Boundaries and unfinished work

- Guides, Help desk, Dealer and other feature branches remain separate work.
  The Help desk historical run was intentionally interrupted when scope changed;
  it is neither passing evidence nor a product failure. Do not restart it as
  part of this workflow batch.
- Programme #48, #92, #109 and #108 remain deferred. Independent-person,
  screen-reader, operational-owner, native print/offline/archive/restore,
  production/PITR and go/no-go evidence retain their separate gates. Use the
  [evidence map](../operations/programme-acceptance-evidence.md) before resuming.
  No profile is activated. Keep disabled Windows animation effects unchanged.
- The general demo is an educational fixture. Purpose-specific workflows need
  their own approved setup and acceptance data. A platform administrator is not
  convention membership; a successful login is not tenant-isolation acceptance.
- Preserve every unrelated worktree, stash, partial proposal, stopped fixture
  and failed receipt. Do not overlap a populated preview with the full eight-
  database certification pool. Never prune unrelated Docker resources.

## Smallest next actions

1. Review the bounded workflow batch and its recorded browser/cleanup evidence.
2. Follow [local certification](../development/local-certification.md) and the
   protected PR flow for delivery; preview checks do not substitute for it.
3. Then return to Guides with an explicit adoption-expansion and purpose-specific
   authority contract. Do not silently widen v1 manifests or duplicate an event.
