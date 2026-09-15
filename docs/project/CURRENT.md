# Current project state

Last updated: 2026-09-15
Phase: Progressive adoption and pre-production release evaluation.

Maru is an actively developed Django/PostgreSQL modular monolith, not a
production-ready release or supported hosted service. Use synthetic data only.
This handoff owns current work; the [roadmap](ROADMAP.md) owns sequencing,
the [production ledger](PRODUCTION_CONSOLIDATION.md) retains the baseline,
and [checkpoints](../checkpoints/index.md) preserve historical evidence.

## Latest protected delivery

#108's item/timetable/release connections are delivered through
[PR #132](https://github.com/martonpornoi/maru/pull/132), protected squash
`0ccd7866aa3965f527b3d8a28fcf5a2e4eebcb27` at 2026-09-15 05:32:33 UTC.
Its tree equals certified head `b7c3d26d3ff83959d992be1b9952259c4ba70726`;
clean local main and origin/main were synchronized to the protected result.

All eight retained local gates passed in 18m12s: 7,591 units in 44.67s and
92 frontend tests. Hosted units passed in 80.52s, quality took 26m54s,
documentation 24m50s and workflow latency 27m22s. Exact-head PR gate and CodeQL
passed; there was no canonical or hosted repair/rerun or acceptance exception.
The observed 3m06s quality margin is not guaranteed; #113 retains this risk
without displacing unblocked #48 work.

The canonical dormant timetable wraps the original native editor in the shared
shell, dispatches once, and rechecks protected owner facts after rendering.
Independently admitted fixed-label links connect items, planning and release;
missing or moved optional links are omitted without obscuring authorized results.
No writer, schema, profile, production route or CI policy changed. One maintained
native scenario and further real-owner revalidation remain unexecuted #102 debt.
New human checks are recorded under #92; component browser observations do not
replace #92/#109 acceptance. See the
[implementation](../checkpoints/2026-09-15-programme-workspace-connections.md) and
[protected delivery](../checkpoints/2026-09-15-programme-connections-protected-delivery.md).

Earlier deliveries, including [PR #131 release workspace](../checkpoints/2026-09-15-programme-release-workspace-protected-delivery.md),
remain complete. Do not restart them or reuse their evidence for a new head.

## Active bounded outcome: Programme staffing-to-Shift connections (#108)

Branch: `codex/programme-shift-connections`, from protected PR #132.
Connect a current Programme staffing requirement to its exact existing Workforce
Shift, with a safe Programme return continuation. This next increment is recorded
beneath #108's existing owner-connections checkbox before implementation.
Notice/continuity connections and final setup remain separate unfinished work.

Reuse Workforce's existing read fields and sole Shift lifecycle. A minimized
Programme coverage grant is not the complete organizer Shift permission.
Resolve real organization/series/edition slugs through an explicit Events owner
seam; do not invent a UUID-shaped Workforce route or import private owner models.
Do not copy personnel into Scheduling, follow a successor silently, open work,
confirm claims or change accepted commitments through navigation.

Preserve original pending input and retry behavior. Optional destination changes
must not obscure a completed command. Account for the existing Shift pages' lazy
template rendering when adding return links; final checks must not redispatch a
POST. Keep current versus historical binding/predecessor meaning explicit.

Implemented locally: Events exact-chain route metadata, Workforce full-field
destination admission, current-bound-Shift card links and lazy-render-safe
Programme return navigation on organizer Shift pages. No personnel inventory is
loaded for navigation and no source rows or command forms are replaced.

Iteration: 7,624 units passed in 45.36s, 93 frontend tests passed; focused checks,
Ruff, mypy and NumPy docstrings passed. A full-unit attempt first caught a missing
empty-panel template fallback; repaired before the passing run. Synthetic browser
handoff and coverage-only omission were observed with database access forbidden.
The exact-commit canonical certification and hosted protected delivery are next;
these iteration results are not a certification receipt.

No schema, runtime grant, profile, production route or CI policy changed. One
existing native Shift scenario was extended without collecting/running PostgreSQL.
Human checks remain #92, integrated proof #109 and native restoration #102. See
the [staffing connection checkpoint](../checkpoints/2026-09-15-programme-shift-connections.md).

## Remaining #48 delivery decomposition

The maintainer makes every item in [#48](https://github.com/martonpornoi/maru/issues/48)
the number-one priority. Supporting increments never finish their whole parent
outcome by themselves. #108 and #48 remain open.

- [#108](https://github.com/martonpornoi/maru/issues/108): finish the recorded
  guided departmental journey and final gated promotion:
  - independently authorized person/domain-reference selection and safe-file
    intake/selection/viewers; typed text presentation alone does not finish these;
  - authorized labelled connections from the delivered item/timetable/release
    workspaces to Workforce Shift work, #104 notices and #107 continuity;
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
#108 has additionally delivered item/readiness/public-copy/hosting workspaces,
call composition/Department transfer, personal proposal collaboration and exact
sealing/submission, review-policy/case/assignment/reviewer/moderation/decision
tasks, recipient history, accepted conversion and the two latest continuations.

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
