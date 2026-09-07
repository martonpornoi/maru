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
No more optimization or Docker cleanup is in the current task. See the
[pilot checkpoint](../checkpoints/2026-09-06-registration-migration-test-pilot.md).

## Current bounded Programme outcome

Issue [#77](https://github.com/martonpornoi/maru/issues/77) is delivered through
[PR #78](https://github.com/martonpornoi/maru/pull/78), protected squash
`6279cb50d287d70e33e2bebabda3e54564668475`. Exact candidate
`d1ed054900e252b8c2706eb4f3c2977c4dcd3e4a` passed full local certification
(5,912 Python tests and all unchanged quality/coverage gates),
[hosted full acceptance and PR gate](https://github.com/martonpornoi/maru/actions/runs/34047039112)
and [CodeQL](https://github.com/martonpornoi/maru/actions/runs/34041922616).
Clean local main was synchronized to that protected result. ADR 0086's exact
accepted conversion creates one private source-bound item and seven unresolved
readiness concerns. The provisioning SQL omission found during its first
certification attempt was corrected and retested before successful acceptance.
Its [implementation](../checkpoints/2026-09-06-programme-accepted-conversion.md)
and [provisioning](../checkpoints/2026-09-06-programme-conversion-runtime-provisioning.md)
checkpoints retain the detailed evidence.

On 2026-09-06 the user explicitly resumed **all remaining children of #48**,
sequentially through documented tests and green protected merges. This
supersedes the earlier stop-after-#77 boundary; routine continuation approval
between children is no longer required. Keep the work single-agent and leave
the completed temporary #77 check-in disabled. Unrelated Docker cleanup and
test-performance optimization remain outside this task.

Issue [#79](https://github.com/martonpornoi/maru/issues/79) is delivered through
[PR #80](https://github.com/martonpornoi/maru/pull/80), protected squash
`7ef234b20867c13674999f5cfc0e47fd65039716`.
[ADR 0087](../architecture/decisions/0087-programme-host-confirmation-and-availability.md)
and PRG-008 contract explicit host/co-host invitations, person-owned responses,
deliberately shared per-item availability, field ceilings, dependency freshness
and retained evidence. It implements four host tables, explicit commands,
independently ceilinged reads, current-person/dependency readiness, database
guards, SELECT-only runtime inventory and additive recovery fences.
Exact candidate `92dd4bb25c429736c7594d32d9bd5c2db29245b7` passed complete
local certification: 6,041 Python tests, 33 frontend tests, all eight isolated
PostgreSQL shards and unchanged quality/coverage gates. The current
[hosted full acceptance and PR gate](https://github.com/martonpornoi/maru/actions/runs/34065746000)
and [CodeQL](https://github.com/martonpornoi/maru/actions/runs/34061604993)
passed before merge. Hosted PostgreSQL shards took 73m54s to 119m19s; this is
not a test-performance improvement. Main was fast-forwarded to the verified
squash, whose tree equals the certified tree; both worktrees and existing
stashes were preserved. The
[host implementation checkpoint](../checkpoints/2026-09-06-programme-host-confirmation-and-availability.md)
and [protected delivery checkpoint](../checkpoints/2026-09-07-programme-host-protected-delivery.md)
retain focused, recovery and final evidence. Historical conversion tests now
prove retained guards and explicit full-graph forward recovery when Django
has reversed unused successors before encountering a populated older fence.
Neither current adoption manifest nor any Programme route is activated.

Active child [#81](https://github.com/martonpornoi/maru/issues/81) is implemented
locally on `codex/programme-scheduling-candidates`, based on that protected main.
[ADR 0088](../architecture/decisions/0088-versioned-scheduling-candidates-and-venue-binding.md)
contracts Scheduling-owned service days, stable occurrences, immutable candidate
alternatives, explicit host-presence requirements, current conflict reports and
deliberate Venue reservation/replacement/cancellation. Alternative drafts do not
reserve rooms or imply host consent, Venue approval or Programme publication.

The [Scheduling owner contract](../modules/scheduling.md) and
[migration/recovery guide](../operations/scheduling-migration-and-recovery.md)
describe source field ceilings, canonical locks, reciprocal two-owner evidence,
database integrity, exact readiness, sixteen SELECT-only relations and joint
populated downgrade fences. Both existing literal adoption profiles remain
unchanged; no route, UI, API, worker or release has been activated.

The combined new Scheduling/owner-seam group passed 377 tests in 326.99 seconds
with 93.64% branch-aware targeted coverage. The complete database-free suite now
passes 3,163 tests in 11.83 seconds. Runtime ACL/provisioning coverage passed 98
cases in 45.44 seconds; eight affected conversion/host historical cases passed
in 495.13 seconds. These overlapping groups are development feedback, not a full
certification result. The twelve new integration weights come from complete
file timings in the successful focused run; existing weights and gates remain
unchanged. They do not establish a whole-suite speedup.

Historical Registration/Identity helpers now explicitly remove unused
Scheduling/Venue successors when rewinding their prerequisite owners. Historical
model reconstruction separately filters unmigration targets and refuses
dependencies that reintroduce an explicitly absent owner. Original historical
assertions and real migration execution remain; both focused committed round-trip
cases passed in 379.30 seconds. Source typing, lint, docstrings and a fresh warning-fatal
Sphinx build passed. No model/migration drift was detected; the unconfigured
invitation-delivery warning is expected in this synthetic environment.

The [implementation checkpoint](../checkpoints/2026-09-07-scheduling-candidates-and-venue-binding.md)
records the initial focused evidence. First full certification of
`3f04efd0f2f9100a4f235b5c74786abf42489ea8` passed 6,533 Python tests but failed
two cross-cutting assertions; non-database gates and 33 frontend tests passed,
but the combined coverage gate was not reached. The missing dormant-event
classification and stale readiness-response assertion are corrected. A newly
reproduced historical-planner handover defect is also corrected without
weakening current-actor eligibility or independent Venue approval. The
[certification follow-up](../checkpoints/2026-09-07-scheduling-certification-follow-up.md)
records the 92-test targeted repair pass, 15-test final continuity/guard pass,
and ordinary reverse/reapply evidence. Corrected clean-head full certification,
hosted acceptance and protected delivery remain next; #81 is not yet delivered.
After verified delivery and issue reconciliation, continue the accessible
editor and remaining #48 children sequentially without another routine approval.

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
  (#71); explicit source-bound accepted conversion (#77); host confirmation
  and deliberately shared per-item availability (#79). These remain dormant
  foundations, not a departmental workspace.
  [Events](../modules/events.md), [Applications](../modules/applications.md),
  and the [Programme Operations setup contract](../product/page-contracts/programme-operations-adoption-setup.md)
  own the details.
- **Release evaluation:** `v2026.08.27-rc.1` remains an immutable synthetic
  evaluation candidate. Exact-image runtime/static rehearsals and consumer
  integrity checks are bounded evidence, not provider or production acceptance.

## Smallest sensible next actions

1. Deliver #81's implemented Scheduling candidate/conflict and governed
   Venue-binding contract: certify the clean exact head, obtain green hosted
   acceptance, squash through the protected gate, reconcile issues and sync
   main. Do not repeat #77 or #79's completed certification.
2. If separately authorized, approve and remove only identified disposable
   Docker resources. Resource cleanup and test-performance work are different
   outcomes.
3. Keep any further migration-test optimization separately bounded. Reuse
   committed setup only for eligible serial cases; preserve committed round
   trips, downgrade fences, concurrency, and isolation. Measure whole-group
   setup, execution, and teardown without weakening case selection, coverage,
   timeouts, or protected acceptance. See
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
