# Current project state

Last updated: 2026-09-07
Phase: Progressive adoption and pre-production release evaluation.

Maru is an actively developed Django/PostgreSQL modular monolith, not a
production-ready release or supported hosted service. Use synthetic data only.
This file is the restart guide; the [roadmap](ROADMAP.md) owns outcome sequencing,
the [production-consolidation ledger](PRODUCTION_CONSOLIDATION.md) retains the
detailed baseline, and [checkpoints](../checkpoints/index.md) preserve history.

## Previous delivered Programme baseline

Programme review and accountable decisions (#71) were delivered through
[PR #72](https://github.com/martonpornoi/maru/pull/72), protected squash
`47960893902d910d86f9b5c8fe5d9b5b2dc65fed`. Issues #66 and #64 were already
closed through PRs #69 and #70. None of these is pending implementation.

Under ADR 0085, the dormant Applications kernel now supports exact-seal review
cases, immutable stage/rubric/template policies, independent scoring and
recusal, moderation/reopening, accountable decisions, and recipient-only
message acknowledgement. It retains audited, field-scoped projections,
canonical locking, runtime SELECT-only relations, readiness fingerprints, and
populated downgrade fences. Review-side acceptance does not create a Programme
item or host, and no Programme profile, route, UI, API, or worker is activated.

The tested PR head was `6cd0c317ecc9ad6262dbf2baa91649d4a91c8661`.
Its complete local certification passed 5,841 Python tests and 33 frontend
tests, all eight PostgreSQL shards, and the combined 90% branch-aware coverage
gate. Hosted [full acceptance](https://github.com/martonpornoi/maru/actions/runs/33975720775)
and [CodeQL](https://github.com/martonpornoi/maru/actions/runs/33975720037)
passed before merge. These are exact-revision results, not the current suite
count, deployment evidence, or production approval.

Detailed implementation and recovery evidence is in the
[review checkpoint](../checkpoints/2026-09-05-programme-staged-review-and-decisions.md),
[readiness correction](../checkpoints/2026-09-05-programme-review-readiness-follow-up.md),
[Applications contract](../modules/applications.md), and
[review recovery runbook](../operations/applications-programme-review-migration-and-recovery.md).

## Completed maintenance

Issue [#73](https://github.com/martonpornoi/maru/issues/73) was delivered through
PR #74 as protected squash `08ae02ef12e21e2bf91990c9527ebd840d624c54`.
It reconciles this handoff and the roadmap, and corrects both rehearsal paths to
remove anonymous volumes associated with exact label-verified containers.
Named-volume cleanup, complete namespace checks, and stopped retention remain
separate and explicit. See the
[maintenance checkpoint](../checkpoints/2026-09-05-handoff-and-rehearsal-resource-hygiene.md)
and its linked PR for candidate-specific verification and delivery state.

Pre-existing Docker cleanup requires a separately approved exact inventory;
unrelated projects, persistent Maru data, and uncertain orphaned volumes must
not be pruned. Follow [local Docker housekeeping](../development/docker-housekeeping.md).
This maintenance does not implement a Programme child or optimize migrations.

Issue [#75](https://github.com/martonpornoi/maru/issues/75) was delivered through
[PR #76](https://github.com/martonpornoi/maru/pull/76), protected squash
`89d3b10662dab882bcd5cc34bc53a8ac817e21ec`, with clean local main synchronized.
Twelve serial Registration historical cases
reuse committed compatible setup; both schema round trips and the populated
recovery fence retain ordinary committed execution. Every original assertion
remains, with additional real-migration leakage and deferred-input checks.
The comparable fresh-database group passed in 14m07s for 18 tests versus 44m03s
for the original 15, about 68 percent less elapsed time. The focused 19-test
PostgreSQL isolation run and independent current-schema/guard inspections also
passed. Exact-head local certification passed 5,846 Python tests, 33 frontend
tests, eight PostgreSQL shards, and the unchanged coverage and quality gates.
[Hosted acceptance](https://github.com/martonpornoi/maru/actions/runs/34027199995)
and CodeQL passed before merge. Hosted PostgreSQL jobs still ranged from
73m41s to 109m45s; the group improvement is not a whole-suite speedup claim.
That optimization pilot is closed; the later separately approved #83 CI task is
described below. No Docker cleanup is authorized. See the
[pilot checkpoint](../checkpoints/2026-09-06-registration-migration-test-pilot.md).

## Current bounded outcome: CI before Programme continuation

Issue #77 was delivered through PR #78, squash
`6279cb50d287d70e33e2bebabda3e54564668475`. Issue #79 was delivered through
[PR #80](https://github.com/martonpornoi/maru/pull/80), squash
`7ef234b20867c13674999f5cfc0e47fd65039716`, after exact-head local and hosted
acceptance. Programme host confirmation and deliberately shared availability
are delivered dormant foundations, not pending implementation.

Issue [#81](https://github.com/martonpornoi/maru/issues/81) remains unmerged in
[PR #82](https://github.com/martonpornoi/maru/pull/82), branch
`codex/programme-scheduling-candidates`, preserved at
`4e6eb1bde8a681b6d5cebb0cdbeaac2bbbc77f68`. That head passed complete local
certification (6,575 Python and 33 frontend tests, eight PostgreSQL shards and
90-percent branch-aware coverage), but hosted shards 5, 6 and 7 exceeded two
hours in [run 34132347435](https://github.com/martonpornoi/maru/actions/runs/34132347435).
Its gate is red. The prior timing-only repair did not resolve the bottleneck.

On 2026-09-07 the user approved a separately bounded CI redesign, tracked in
[#83](https://github.com/martonpornoi/maru/issues/83), before continuing #48.
Work is single-agent on `codex/risk-based-postgresql-ci`, from protected main.
[ADR 0090](../architecture/decisions/0090-risk-based-postgresql-acceptance.md)
retains current-schema PostgreSQL behavior and unchanged coverage on every code
PR, adds affected history for domain schema changes, and requires full history
for global safety/harness changes, changed-revision nightly checks and releases.
Independent historical functions form smaller isolated groups; shared committed
baselines stay together. Exhaustive hosted runs use sixteen groups with at most
eight simultaneous databases and unchanged per-job timeouts.

The implementation has a validated per-function inventory, actual-collection
checks, risk/graph selection, local scope receipts and nightly deduplication.
The current-only diagnostic for `2a0dda7f7307925135b7c2bfe401feb3f24829bb`
completed in 899.281 seconds (14m59s): 2,981 unit and 3,002 PostgreSQL cases,
zero failures/errors/skips across eight isolated databases. It deferred 124
historical cases and did not run non-database quality gates. This is not full
certification or hosted acceptance. The initial 20–35-minute hosted routine
estimate remains an estimate; the exhaustive suite still has substantial cost.

Final review found that the runner initialized Django before recording
coverage; its 89.56-percent combined result passed only through the existing
whole-number rounding. The candidate now starts coverage before the runner and
uses two-decimal reporting at the same 90-percent threshold and exclusions.
Regressions protect startup recording and rejection of the rounded shortfall.
The corrected diagnostic at `8fa540cf649937a56855d4098f7ec7647744e439`
passed all 5,985 tests but correctly failed the precise coverage gate at 89.56%.
Current-input, form, scope-token and dormant-profile regressions now exercise
that behavior independently of historical migration fixtures. The candidate's
fresh diagnostic at `80f36ad713a6c5d5e3589dee22d9b8fe344d2477` passed
3,224 unit and 3,002 current PostgreSQL tests, zero failures/errors/skips, and
90.02% combined coverage in 957.955 seconds (15m58s). This supersedes the mixed-run
development estimate and is current-path evidence, not full certification. The non-database
quality gates passed on `8fa540c` with a fresh type-analysis cache; certification
now isolates that cache per run to prevent cross-branch Django-plugin residue.
Nightly deduplication also verifies the actual exact-revision Full CI gate,
not a selector-only successful workflow with skipped acceptance.
Final exhaustive local certification and hosted acceptance must pass before
delivery. See the
[benchmark checkpoint](../checkpoints/2026-09-07-postgresql-current-path-benchmark.md)
for exact observations, limitations and the preserved original evidence.
The [verified current-path checkpoint](../checkpoints/2026-09-07-postgresql-current-path-verified.md)
records the precise passing result and its acceptance boundary.

Neither #83 nor #81 is delivered. Preserve the separate Programme branch,
existing stashes and other worktree. Do not merge PR #82 using a current-only
diagnostic result: its migration-harness changes still require full evidence.
The temporary #83 app reminder was deleted at the user's request; do not recreate
it. The completed #77 app check-in remains disabled. Docker cleanup and unrelated
product work remain outside this bounded task.

## What can be evaluated today

- **Workforce-only:** guided edition adoption and the Organization structure,
  Position, Assignment, Availability, and Shift journey, including independent
  confirmation and retained personal history. It creates no unrelated
  Registration, Participation, payment, or attendance state. See the
  [Workforce contract](../modules/workforce.md) and
  [adoption/recovery runbook](../operations/workforce-only-adoption-and-recovery.md).
- **Programme foundations:** owned items and information/readiness layers
  (#61); Applications calls and acknowledged collaborative proposals (#63);
  preview-first import (#66); Department continuity (#64); review and decisions
  (#71); explicit source-bound accepted conversion (#77). These remain dormant
  foundations, not a departmental workspace.
  [Events](../modules/events.md), [Applications](../modules/applications.md),
  and the [Programme Operations setup contract](../product/page-contracts/programme-operations-adoption-setup.md)
  own the details.
- **Release evaluation:** `v2026.08.27-rc.1` remains an immutable synthetic
  evaluation candidate. Exact-image runtime/static rehearsals and consumer
  integrity checks are bounded evidence, not provider or production acceptance.

## Smallest sensible next actions

1. Complete #83's exhaustive local and hosted acceptance after the passing current diagnostic,
   protected delivery and exact-main synchronization. Do not bypass the red #82
   gate or repeat the already delivered #77/#79 work.
2. If separately authorized, approve and remove only identified disposable
   Docker resources. Resource cleanup and test-performance work are different
   outcomes.
3. Integrate the delivered CI policy into #81's preserved branch, resolve its
   inventory/owner changes explicitly, and obtain its own exhaustive exact-head
   acceptance before delivering PR #82. Preserve committed round trips,
   downgrade fences, concurrency and isolation. Measure setup, execution and
   teardown without lowering coverage or bypassing protected acceptance. See
   [testing strategy](../quality/testing-strategy.md) and the
   [existing isolation checkpoint](../checkpoints/2026-09-05-historical-migration-test-isolation.md).
4. Continue umbrella [#48](https://github.com/martonpornoi/maru/issues/48) after
   each completed child without another routine approval: Scheduling core and
   accessible editor, Workforce staffing,
   atomic release/outputs, on-site continuity, and integrated acceptance.
   Profile setup/activation comes after those mandatory continuations. Keep the
   umbrella open until the complete Programme-only journey is accepted.

Outside the Programme sequence, #42 owns the reproducible Workforce tutorial,
#22 continuity/reversible adoption, #23 the role-state accessibility matrix,
and #24 the later attendance/handover/actual-time contract. The roadmap and
live issue queue own further priorities; this maintenance does not reprioritize
or close them.

## Known risks and production gates

- Programme has no usable timetable, staffing/release workspace, on-site pack,
  or activated adoption profile. Dormant code is intentional, not abandoned.
- Workforce import/export, printable/manual fallback, reconciliation,
  expansion/decommissioning, and stopped-operation rehearsal are incomplete.
  Do not replace an incumbent system based on scoped pages or APIs alone.
- Representative accessibility (including screen readers, keyboard, zoom,
  widths, and disclosure/mutation states) and two-human owner acceptance remain
  open. Synthetic sessions and automated tests do not replace those gates.
- Provider certification, deployment/stopped-writer cutover, runtime-role
  provisioning, restore/PITR, worker supervision, load, telemetry, privacy,
  safeguarding, training, and operational owner acceptance remain open.
- Availability disposal needs approved retention, legal holds, observable
  execution, and recovery. No production personal data is authorized.
- Historical-model reconstruction is a measured test bottleneck. Documentation
  and Docker disk cleanup do not establish a migration-test speedup.

## Resume safely

Follow `AGENTS.md`, this handoff, the roadmap, then the task's requirements,
owning module/runbook, ADR index and related decisions, and code/tests. Use the
[agent-assisted workflow guide](../development/agent-workflows.md) to select
only matching procedures; historical checkpoints are consulted as needed.

Preserve scope-before-disclosure authorization, immutable evidence, canonical
lock order, runtime-role containment, and fix-forward recovery. NFR-013 forbids
unadopted module side effects. Retired-route guards, migrations, ADRs, and
historical checkpoints are not cleanup targets. Keep focused evidence, exact
local certification, protected hosted acceptance, and production approval
distinct. Replace superseded status rather than adding another delivery diary.
