# Current project state

Last updated: 2026-09-15
Phase: Progressive adoption and pre-production release evaluation.

Maru is an actively developed Django/PostgreSQL modular monolith, not a
production-ready release or supported hosted service. Use synthetic data only.
This handoff owns current work; the [roadmap](ROADMAP.md) owns sequencing,
the [production ledger](PRODUCTION_CONSOLIDATION.md) retains the baseline,
and [checkpoints](../checkpoints/index.md) preserve historical evidence.

## Latest protected delivery

#108's registered private person-reference tasks are delivered through
[PR #138](https://github.com/martonpornoi/maru/pull/138), protected squash
`5dd497fea1c683623034cd803146864120be1e75` at 2026-09-15 14:47:01 UTC.
Its tree equals certified head `396f16bcc8e5c77d9da43818e758e0b6d08a79a8`;
clean local main and origin/main were synchronized to the protected result.

All eight retained local gates and exact-head hosted PR gate/CodeQL passed.
Hosted quality took 29m17s, leaving only 43s; #113 retained that risk.
See [implementation](../checkpoints/2026-09-15-programme-person-references.md) and
[protected evidence](../checkpoints/2026-09-15-programme-person-protected-delivery.md).
No schema, profile or route activation. Earlier deliveries remain complete.

## Active bounded outcome: same-call domain references (#108)

Branch: `codex/programme-domain-references`, from protected PR #138.
The candidate implements registered same-call track/format extra-answer selection,
clear and independent current/sealed/review viewers under PRG-009. Original intent,
canonical replay, same-call membership and anonymous no-lookup remain enforced;
main selection/routing/timetable and current profiles are unchanged. See the
[page contract](../product/page-contracts/programme-domain-references.md) and
[implementation/browser evidence](../checkpoints/2026-09-15-programme-domain-references.md).
The earlier implicit-import certification failure was repaired without changing
person-reference contracts or legacy digests.
The corrected head `383ca2dab488232e97897f853c0f6a3031386e5e` passed all eight
retained local gates in 18m51s (8,160 units in 52.38s). Its hosted units/CodeQL
passed, but [PR #139](https://github.com/martonpornoi/maru/pull/139) remains unmerged:
quality exhausted its 30-minute budget after a successful 28m01s documentation
build, cancelling frontend acceptance. Existing #113 owns this active blocker.

The in-PR repair applies ADR 0074's current-section navigation before Furo renders
the sidebar, retaining every source, catalog, search index, warning and timeout.
A real miniature Sphinx/Furo build passes discovery/search regressions; all 8,169
database-free units pass in 55.27s (three existing URLField warnings), along with
Ruff/format and 558-document validation. New exact-head certification, rendered-site
browser verification and protected hosted acceptance remain pending. See the
[repair checkpoint](../checkpoints/2026-09-15-pr139-documentation-navigation-repair.md).

Six maintained, unexecuted native cases and human follow-up are recorded in
[#102](https://github.com/martonpornoi/maru/issues/102#issuecomment-5683156776) and
[#92](https://github.com/martonpornoi/maru/issues/92#issuecomment-5683157180);
integrated proof remains #109. No profile, production route or CI-policy change.
Safe-file intake needs governed upload/receipt handling. A fresh bounded schema-only
exception was requested; no answer has arrived and no such check is authorized yet.
Independent scoped launchers can proceed after this PR if the exception is pending.

## Remaining #48 delivery decomposition

The maintainer makes every item in [#48](https://github.com/martonpornoi/maru/issues/48)
the number-one priority. Supporting increments never finish their whole parent
outcome by themselves. #108 and #48 remain open.

- [#108](https://github.com/martonpornoi/maru/issues/108): finish the recorded
  guided departmental journey and final gated promotion:
  - independently authorized person/domain-reference selection and safe-file
    intake/selection/viewers; typed text presentation alone does not finish these;
  - complete ordinary scoped entry/navigation over the delivered item, timetable,
    release, staffing-to-Shift, #104 notice and #107 output connections;
  - accountable blank-organization setup, coherent shared navigation and an isolated
    complete synthetic fixture without changing current profiles;
  - final separately verified promotion only after all gates below pass.
- [#109](https://github.com/martonpornoi/maru/issues/109): integrated synthetic
  setup-to-on-site, isolation, excluded-side-effect, recovery and stop-use proof.
- [#102](https://github.com/martonpornoi/maru/issues/102),
  [#97](https://github.com/martonpornoi/maru/issues/97) and
  [#92](https://github.com/martonpornoi/maru/issues/92): mandatory native database,
  logical recovery and human acceptance gates.

Build dormant surfaces/fixtures before #109/#92 acceptance; do not create a
circular dependency requiring activation before an isolated fixture can run.
Record discovered prerequisites beneath their owning checklist item before work.
Unrelated ideas stay in their own backlog without displacing this decomposition.

## Delivered foundations: do not restart

Programme children #57, #59, #61, #63, #66, #64, #71, #77, #79, #81, #85,
#88, #91, #94, #96, #99, #100, #104, #105 and #107 are delivered dormant.
#108's recorded item, call/proposal/review, release, staffing and continuity
increments remain delivered; do not restart them or equate them with activation.

Use the [Programme Operations contract](../product/page-contracts/programme-operations-adoption-setup.md)
and owning [Programme](../modules/programme.md),
[Applications](../modules/applications.md), [Scheduling](../modules/scheduling.md),
[Events](../modules/events.md) and [Workforce](../modules/workforce.md) documentation
for durable contracts, and the checkpoint archive for actual delivery evidence.
Dormant components are not an activated departmental workflow or production approval.

## Temporary testing policy and mandatory gates

Maintain PostgreSQL tests, historical inventories and migration/recovery fixtures
as features change, but neither collect nor execute PostgreSQL suites during
this dormant development phase. Record changed unexecuted scenarios as #102 debt;
do not invent native weights, timings, coverage or success. The completed #104
schema-only exception is not standing authority for another schema check.

Run complete inexpensive database-free unit feedback during iteration, then fresh
clean exact-commit development certification before each protected PR. Follow
[local certification](../development/local-certification.md): `CI=true`, pinned
pnpm, all eight retained gates and a truthful `postgresql_deferred` receipt.
Preserve previous receipt, plan, JUnit and package artifacts outside `.local-ci/`
before the next run clears it. Certify the actual candidate, not a preceding head.
Require exact-head PR gate/CodeQL and resolved conversations before normal
match-head squash, then verify equal trees and clean protected-main synchronization.

[ADR 0100](../architecture/decisions/0100-temporary-programme-postgresql-deferral.md)
fences full/release acceptance and Programme profile addition while deferred.
#102 restores required mode and exhaustive exact-head local/hosted PostgreSQL,
unchanged full coverage and measured budget evidence before final integrated
acceptance, activation, director pilot or release. ADRs 0090/0098 retain their
risk/scope and measured-assignment contracts; unit coverage cannot replace them.

#97 remains open: logical dump/restore can re-render array-cast CHECK expressions
and fail exact schema readiness. Native guards/ACLs/recorders and same-image physical
recovery do not waive logical acceptance. Preserve weakened-constraint negatives;
never blindly rebaseline fingerprints. This blocks activation/pilot, not dormant work.

#87 is closed through PR #90 for bounded native Cancel/discard, actual 200% Chrome
zoom, visible Tab focus and Windows Animation effects-off observations. Preserve
that preference and [evidence](../checkpoints/2026-09-11-programme-browser-protected-delivery.md).
The one-off split-run exception is not standing acceptance policy. New integrated
human, screen-reader, responsive and comprehension checks remain unchecked under #92.

## Scope and safe continuation

Keep the exact `programme_operations@1` boundary: Applications, Programme,
Scheduling, Venues and Workforce plus required foundations. No Registration,
Participation, payment, attendance, Logistics or general Communications side effects.
Reuse each owner's public seam and shared shell. Ordinary users select authorized
labelled tasks, not database identifiers. Navigation is not permission.

#104 notices retain separate preparation, independent review, manual handoff and
genuine-person acknowledgement; inventory is not delivery completeness. #107
continuity retains source age, scope, expiry, independent trust, custody and disposal.
Known withdrawal/invalidation suppresses ordinary old content. Offline packs are
historical read-only material, never fresh authority or an on-site mutation relay.

The maintainer authorizes unattended sequential PR/merge delivery with one agent
and current model settings. No schedules, policy bypass, production deployment,
personal data or general Docker cleanup. Preserve unrelated worktrees, stashes and
containers; stop/remove only exact verified task-owned disposable resources.
Use AGENTS and the matching [agent playbooks](../development/agent-workflows.md).

After #48, continue #42 and the director introduction/pilot package, then the agreed
guidance/accessibility and continuity/succession priorities. #22, #23 and #24 retain
their separate Workforce ownership. Provider/deployment/runtime provisioning,
restore/PITR, supervision, load, privacy, safeguarding, training and two-human
operational acceptance remain production gates. The immutable
`v2026.08.27-rc.1` is synthetic evaluation, not production approval.
