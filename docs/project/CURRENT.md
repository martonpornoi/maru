# Current project state

Last updated: 2026-09-17
Phase: Progressive adoption and pre-production release evaluation.

Maru is an actively developed Django/PostgreSQL modular monolith, not a
production-ready release or supported hosted service. Use synthetic data only.
This handoff owns current work; the [roadmap](ROADMAP.md) owns sequencing,
the [production ledger](PRODUCTION_CONSOLIDATION.md) retains the baseline,
and [checkpoints](../checkpoints/index.md) preserve historical evidence.

## Latest protected delivery

Atomic Programme foundation setup is delivered through
[PR #154](https://github.com/martonpornoi/maru/pull/154), protected squash
`7441d35243321bd5adbe4b015db01a7c93c07aa9` at 2026-09-16 22:03:02 UTC.
Its tree equals certified head `e531f074a3776e32fc951122d7065d8b0c038055`;
clean local main matched origin/main and that result. All eight retained local
gates passed in 6m41s, including 9,197 units in 73.56s and 103 frontend tests.
Hosted quality took 12m22s and units 1m59s; PR gate and CodeQL passed. PostgreSQL
was explicitly deferred, not certified. The setup schema file now maintains 36
uncollected/unexecuted cases, alongside PR #152's six reference cases. See the
[protected evidence](../checkpoints/2026-09-17-programme-atomic-setup-protected-delivery.md).

The [integrated rehearsal protocol](../operations/programme-integrated-rehearsal.md)
defines twelve checkpoints, distinct sessions, isolation/excluded-effect proof,
failure/recovery/stop-use, human/accessibility tasks and exact-source evidence.
It is preparation, not an executable integrated fixture or accepted journey.
Earlier [PR #150](https://github.com/martonpornoi/maru/pull/150) delivered supporting-file
controls; its [checkpoint](../checkpoints/2026-09-16-programme-file-controls-protected-delivery.md)
retains exact native-deferred and synthetic-browser limits. Do not restart it.

## Current work: scoped operational authority and setup continuation (#108)

Branch: `codex/programme-operational-authority`, from protected PR #154.
Delivered Events setup composes public owner commands in one atomic transaction, with exact-profile
denial before database work, fresh Identity admission, actor/key serialization,
canonical locked foundation comparison, complete-receipt replay and final locked
authority recheck. One new edition/first Department, truthful representation and
all owner/setup evidence commit together. Child replay cannot substitute for a
complete setup receipt. Current profiles and runtime SELECT-only remain unchanged;
the private receipt writer grants no invitation, authority, route or activation.

The next implementation must preserve the fixed accountable representation root
and use separately approved immutable operational roles. Department call/review,
edition Programme/planning, organization Venue facts and exact-resource physical
approval have different scope ceilings; no catch-all role can substitute for them.
Actual distinct controllers must submit their own intent/approval after genuine
representation acceptance and activation. Existing generic approver-email selection
is not proof of that person's own action. Ordinary authority requires persistent
current controller sources, not generic platform policy or an accepted invitation.
ADR 0106 records this design. The current candidate adds 27 immutable optional
role recipes and closed normalized request/decision inputs with exact digests.
The owned catalog registers definitions without admitting them to either current
profile. This is not an implemented grant, request schema, surface or fixture.
Database-free iteration passed 9,297 units in 55.41s and strict types for 698 files;
focused recipe/input/adoption checks passed 117 cases. Fresh exact-commit retained
certification and protected delivery are still pending for this candidate.

The explicitly approved disposable schema-only observation completed in 3m22s:
forward migration and exact native metadata passed; the pinned readiness wrapper
returned true. This is not native test, reverse/rollback, runtime-role or workflow
acceptance. The exact task container and temporary database were removed, with
logs retained; no user container or persistent volume was touched. PostgreSQL
suites remain deferred and all final acceptance gates remain open.

Next complete independently approved authority, genuine-person continuation,
guided UI and the actual isolated
fixture. Preserve existing truthful representation and immutable `maru-operators@1`,
two distinct eligible people's own acceptances, Department-scoped call/review
versus edition-scoped planning, and independently approved additional authority.
Do not infer authority from a source fingerprint or an earlier invitation.

Keep current profiles unchanged; final promotion waits for #102/#97/#92/#109.
Delivered item, Applications, reference/file, timetable/release/staffing, notice
and continuity connections remain implemented. #108's overall outcome and #48
stay open for setup and all final acceptance gates.

Non-blocking tooling follow-up after #48: the semantic docstring validator's
no-argument defaults are strings rather than `Path` objects; its maintained explicit
`src scripts` invocation passes. The reader checkpoint records the failed diagnostic
and correct rerun; do not expand this delivery into unrelated tooling cleanup.

## Remaining #48 delivery decomposition

The maintainer makes every item in [#48](https://github.com/martonpornoi/maru/issues/48)
the number-one priority. Supporting increments never finish their whole parent
outcome by themselves. #108 and #48 remain open.

- [#108](https://github.com/martonpornoi/maru/issues/108): finish the recorded
  guided departmental journey and final gated promotion:
  - preserve the delivered dormant Applications/reference/file tasks and ordinary
    item/timetable/release/staffing/notice/continuity connections in one integrated
    acceptance journey;
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
