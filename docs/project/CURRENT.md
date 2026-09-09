# Current project state

Last updated: 2026-09-09
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

## Current bounded outcome: Programme staffing

Issue #77 was delivered through PR #78, squash
`6279cb50d287d70e33e2bebabda3e54564668475`. Issue #79 was delivered through
[PR #80](https://github.com/martonpornoi/maru/pull/80), squash
`7ef234b20867c13674999f5cfc0e47fd65039716`. Programme host confirmation and
deliberately shared availability are dormant delivered foundations, not pending
implementation. The [host delivery checkpoint](../checkpoints/2026-09-07-programme-host-protected-delivery.md)
retains its exact verification and recovery evidence.

### Delivered CI prerequisite

Issue [#83](https://github.com/martonpornoi/maru/issues/83) is closed through
[PR #84](https://github.com/martonpornoi/maru/pull/84), protected squash
`c0cf5a24d7593744bbb52ad0f9293deaf21e393a` on 2026-09-08. The clean main
worktree was fast-forwarded to that identical-tree result.

Exact head `dfc775445d146ab86423544860e9a1726f0131f2` passed exhaustive local
certification: 6,350 Python tests, 33 frontend tests, all quality gates and
90.20% combined branch-aware coverage in 95m22s. Independent
[hosted acceptance](https://github.com/martonpornoi/maru/actions/runs/34161506336),
PR gate and CodeQL passed. All sixteen PostgreSQL jobs passed in 35m23s–63m08s
each, with at most eight simultaneous databases; total PostgreSQL job time was
846m30s and complete workflow latency was 122m20s. Smaller jobs avoided the
per-job timeout; exhaustive history remains costly.

[ADR 0090](../architecture/decisions/0090-risk-based-postgresql-acceptance.md)
keeps current PostgreSQL behavior on every code PR, affected history for domain
schema changes, and full history for global safety/harness changes, changed-main
nightly checks and releases. Two-decimal coverage and initialization recording
retain the unchanged 90% threshold without rounded shortfalls. The separately
[verified current-path diagnostic](../checkpoints/2026-09-07-postgresql-current-path-verified.md)
passed 6,226 Python tests at 90.02% in 15m58s locally; it omitted history and
non-database quality gates. The 20–35-minute hosted routine target remains
unmeasured, not a promise for the high-risk Scheduling PR.

### Delivered Scheduling foundation

Issue [#81](https://github.com/martonpornoi/maru/issues/81) is closed through
[PR #82](https://github.com/martonpornoi/maru/pull/82), protected squash
`ec0d2474810e27b72c9dbabcc1d210222e4989af` on 2026-09-08. Exact candidate
`85db2e16a453355b534dfb2e37e6695bb858e635` passed exhaustive local certification:
6,887 Python tests, 33 frontend tests, all ten quality gates, eight PostgreSQL
databases and 90.34% combined coverage in 108m19s. Its own
[hosted acceptance](https://github.com/martonpornoi/maru/actions/runs/34208969678),
all sixteen database jobs, `PR gate` and CodeQL passed before merge. The clean
main worktree was synchronized and the squash tree equals the certified head.
The [delivery checkpoint](../checkpoints/2026-09-08-scheduling-protected-delivery.md)
retains exact provenance, recovery and cost evidence. Do not rerun the old
timed-out head or treat this delivered child as pending.

### Delivered dormant editor and next priority

Issue [#85](https://github.com/martonpornoi/maru/issues/85) is delivered through
[PR #86](https://github.com/martonpornoi/maru/pull/86), protected squash
`cdb06d41a6d5795078a8ae19ee5e4a0ebbabd466` on 2026-09-09.
Clean local main equals origin/main and that merge; the squash tree matches
the certified candidate `e226e8ded449039057ee79e7540a456b6431ee44`.

The dormant editor provides equivalent pointer/native forms, audited and
independently authorized layers, conflict preview, immutable alternatives and
history, stale-input recovery, and explicit physical-hold actions. Private
drafts neither publish Programme work nor silently reserve rooms. Its
[page contract](../product/page-contracts/programme-timetable-planning.md) and
ADR 0092 remain authoritative.

Complete local certification passed 7,426 Python tests (3,890 unit and 3,536
PostgreSQL), 64 frontend tests, all eight full-history PostgreSQL groups, all
quality/security/documentation gates and 90.49% combined coverage. Exact-head
hosted acceptance passed all sixteen PostgreSQL groups, the full CI gate and
required PR gate; CodeQL passed. No rerun or threshold reduction was needed.
See the [protected-delivery checkpoint](../checkpoints/2026-09-09-timetable-editor-protected-delivery.md)
for timings, links and preserved evidence.

The user explicitly approved dormant delivery with three browser checks
**deferred, not waived**, as mandatory pre-activation acceptance in
[#87](https://github.com/martonpornoi/maru/issues/87): controlled native
Cancel/deliberate discard, genuine 200% browser zoom, and enabled reduced
motion. They are not proven by input retention, responsive widths, absence of
animation at the current preference, unit tests or green CI. Screen-reader,
representative-human and provisioned-runtime acceptance remain separately open.
No production route, navigation, runtime write grant or profile is activated.

All synthetic browser leases and certification watchers are closed. Preserved
reports are evidence, not running jobs. Do not rerun the completed suite or
recreate old schedules. Preserve unrelated worktrees, stashes and containers;
no general Docker cleanup or production data is authorized.

Next implementation is Programme-owned staffing requirements with Workforce-
owned demand/commitments and minimized Scheduling coverage, followed by atomic
release/outputs, on-site continuity, guided setup and integrated acceptance.
The active branch is `codex/programme-staffing`, based on the verified merge.
Native child [#88](https://github.com/martonpornoi/maru/issues/88) is open and
linked from #48. ADR 0093 and HR-015 define exact source binding, immutable
accepted work and minimized coverage; implementation and acceptance remain
in progress. Work stays single-agent and #48 remains open.

The local staffing implementation now includes Programme requirement
create/revise/retire, immutable explicit terms, bounded independently authorized
current/history reads, canonical owner references, reciprocal PostgreSQL guards,
runtime SELECT-only containment and populated downgrade fences. The earlier
minimized Workforce coverage source remains behind an unpinned adapter.

Exact Programme/Scheduling source selection and a separate authorized Workforce
work-impact read are also implemented locally. Candidate copying preserves the
selected source; movement, current service-day changes and requirement retirement
invalidate it. Closed impact rules require identical uncommitted drafts for
linking, no retained commitments for reconciliation, and explicit predecessor
cancellation/history preservation for successors. No binding command is exposed.

The latest full fast run passed 4,173 unit tests in 21.58s, with the same two
pre-existing Django URLField warnings. A focused PostgreSQL regression passed
43 cases in 102.35s, omitting the two unchanged requirement migration round-trip
cases already checked below. Three new source files passed strict types and
semantic docstrings; focused lint passed. These are not full certification,
browser acceptance or protected delivery. See the
[source/impact checkpoint](../checkpoints/2026-09-09-programme-staffing-source-and-impact.md).

The earlier persistence acceptance passed 36 PostgreSQL cases and eight contract
cases in 90.49s, including adversarial DML,
concurrency, read ceilings, audit failure and both migration paths. These are
local step results, not complete issue certification. Exact Programme schema
and guard fingerprints match; authority guard metadata is installed, but the
flushed test database has no active cutover marker and is not a provisioned
runtime acceptance claim. Migration drift, types and semantic docstrings pass.

An existing CI-selection regression was also corrected: a new owner migration
leaf can no longer hide consumers of older model migrations. No history,
timeout, coverage or protected gate is weakened. Source-bound demand commands,
successor/reconciliation, Scheduling/UI integration, browser acceptance and
complete certification remain unfinished. No PR or staffing merge exists.
See the [persistence checkpoint](../checkpoints/2026-09-09-programme-staffing-requirement-persistence.md)
and [earlier input/source checkpoint](../checkpoints/2026-09-09-programme-staffing-inputs-and-coverage.md).

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
  and deliberately shared per-item availability (#79); Scheduling candidates,
  conflict evidence and governed Venue binding (#81); native/pointer timetable
  editing (#85). These remain dormant
  foundations, not a departmental workspace.
  [Events](../modules/events.md), [Applications](../modules/applications.md),
  and the [Programme Operations setup contract](../product/page-contracts/programme-operations-adoption-setup.md)
  own the details.
- **Release evaluation:** `v2026.08.27-rc.1` remains an immutable synthetic
  evaluation candidate. Exact-image runtime/static rehearsals and consumer
  integrity checks are bounded evidence, not provider or production acceptance.

## Smallest sensible next actions

1. Continue #88 with exact-source Workforce demand create/link/reconcile and
   explicit successor commands under ADR 0093. Requirement persistence, exact
   source selection and authorized impact inputs are implemented locally.
   Reuse existing Workforce commands;
   never silently rewrite accepted Shifts. Add reciprocal binding guards,
   source-movement/commitment races and the remaining migration/recovery proof.
2. Carry the staffing child through focused tests, appropriate exact-head
   certification and protected delivery. Include this post-editor checkpoint.
3. Complete #87 before activation. Continue release/outputs, on-site continuity,
   guided setup/surfaces and the integrated synthetic Programme-only journey.
   No routine approval is needed between delivered children; keep #48 open.

Outside the Programme sequence, #42 owns the Workforce tutorial, #22 continuity,
#23 accessibility and #24 later attendance/handover/actual-time behavior. They
are not absorbed or closed by this integration. Docker cleanup still requires
a separately approved exact inventory.

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
