# Current project state

Last updated: 2026-09-11
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

## Current bounded outcome: trusted Programme release sources (#94)

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

Previous synthetic browser leases and certification watchers are closed; the
active assisted #87 retry is described below. Preserved reports are evidence,
not running certification jobs. Do not rerun the completed suite or
recreate old schedules. Preserve unrelated worktrees, stashes and containers;
no general Docker cleanup or production data is authorized.

### Delivered staffing and active browser acceptance

Issue [#88](https://github.com/martonpornoi/maru/issues/88) is closed through
[PR #89](https://github.com/martonpornoi/maru/pull/89), squash
`dca412e97dfa40371e01db3222105f87cf9d4562` on 2026-09-10. The maintainer
merged after protected acceptance. Clean local main and origin/main equal that
result; its tree equals certified head
`1883c55717f4d843ecbc3a15831aa1e7fc9ca36d`.

ADR 0093 and HR-015 now have dormant Programme-owned versioned requirements,
explicit Workforce create/link/reconcile/successor bindings, independently
authorized source/impact/coverage/history, and native preview/apply controls.
Canonical cross-owner locking, immutable accepted work, audit/receipt/outbox
atomicity, runtime SELECT-only containment and populated recovery fences remain
enforced. The staffing event is explicitly dormant. No profile, route, adapter
or runtime writer is activated.

Complete local certification passed 7,941 Python tests (4,254 unit and 3,687
PostgreSQL), 64 frontend tests, all ten gates and 90.56% combined branch-aware
coverage in 118m56s. Independent hosted acceptance passed all sixteen PostgreSQL
jobs, Full CI gate, PR gate and CodeQL. Seventeen hosted reports contain zero
failures, errors or skips. Full hosted latency was 3h08m18s: exhaustive history
was selected by the CI dependency-closure repair, not a routine-path benchmark.
No test rerun is needed for this delivered candidate. See the
[staffing delivery checkpoint](../checkpoints/2026-09-10-programme-staffing-protected-delivery.md)
for exact provenance, earlier repairs and preserved evidence.

The no-Participation personal proof composes ordinary Workforce owner inputs;
combined published host/volunteer timetables remain part of the release/output
successor. Staffing browser evidence covered planner validation/history,
preview/apply, keyboard controls, independently restricted/read-only roles and
seven widths. It does not close #87 or prove an activated Programme-only journey.

Issue [#87](https://github.com/martonpornoi/maru/issues/87) is closed through
[PR #90](https://github.com/martonpornoi/maru/pull/90), protected squash
`d9dcd5074af494689912dc1524095b85343f5f2c`. Clean local main and origin/main
match that result; its tree equals candidate
`cb131c8c10ee46f12702dada1248204676b3670d`.

The maintainer's Chrome 152.0.7977.83 (64-bit) observations cover native
Cancel/discard, populated genuine 200% zoom with visible Tab focus kept in view,
and usable board interaction with Windows Animation effects off. Browser-control
readback limitations remain explicit. The maintainer chose to keep Animation
effects off; do not revert that preference. Screen-reader, representative
departmental use, provisioned runtime and integrated acceptance remain separate.

All 7,810 Python tests passed (4,254 unit plus 3,556 current PostgreSQL), but the
initial certification command failed at pnpm's non-interactive prompt. The
maintainer approved one-off split-run acceptance: the unchanged candidate passed
recovered non-database gates with CI=true, all 64 frontend tests and 90.38%
combined coverage. No successful certification receipt was fabricated and no
policy or threshold changed. Independent hosted documentation/quality, PR gate
and CodeQL passed before exact-head guarded merge. The
[delivery checkpoint](../checkpoints/2026-09-11-programme-browser-protected-delivery.md)
retains provenance, the exception, browser limitations and cleanup evidence.
Do not repeat the completed tests or browser checks.

Issue [#91](https://github.com/martonpornoi/maru/issues/91) is closed through
[PR #93](https://github.com/martonpornoi/maru/pull/93), protected squash
`60dc9aeb15e306e3d64abd0e76c5a455540402f7`. Its tree equals certified head
`a6a9e6b28f985aa0172a0c077732c842e4301717`; clean local main was synchronized.
Full local certification passed 7,947 Python tests, 64 frontend tests, all ten
gates and 90.40% combined coverage in 30m01s. Exact-head hosted acceptance,
PR gate and CodeQL passed; current PostgreSQL jobs took 7m22s–21m46s and the
workflow took 24m17s. No split-run exception or threshold change was needed.
The [delivery checkpoint](../checkpoints/2026-09-11-release-eligibility-protected-delivery.md)
retains exact evidence. Do not rerun that completed certification.

Active branch: `codex/programme-release-sources`, from the protected #93 merge.
Native child [#94](https://github.com/martonpornoi/maru/issues/94) now owns the
complete authenticated owner-source prerequisite, including explicit no-staffing
and exact physical accessibility-fit evidence and combined person/rest checks.
ADR 0094's ten-category pure policy grants no authority. Existing planning and
coverage queries do not establish these complete release facts. The local change
now implements the complete ten-category preflight, exact candidate/Venue inputs,
retained staffing lineage, independently versioned fit/no-staffing decisions and
history, current readiness/independent-copy evidence and combined global person/
rest checks. Authorized planner, approver and publisher fingerprints agree;
caller-only locks and trace/audit identities are not dependencies. Mandatory
owner/field denial or audit failure withholds disclosure. Venue sources are
re-read before disclosure without inverted physical locking. No planning-warning
acknowledgement is accepted as release evidence.

Iterative focused checks passed for source/field isolation, real cross-tenant
overlap/rest, actual confirmed/locked coverage, retired operative work, optimistic
decision races, immutable reciprocal evidence, Ready/Live operational decisions
without content reopening, and real unused reversal/populated fix-forward fences.
Strict mypy, lint, documentation validation and corrected docstring checks passed.
All 206 new focused cases passed; the wider run then caught an outdated catalog
expectation. Its corrected catalog/contract/shard-inventory group passed 41 cases,
and all six new-relation runtime privilege cases passed. The first Sphinx build
caught four ambiguous type references, now corrected; clean warning-fatal Sphinx,
exact clean-commit certification, protected PR acceptance and merge remain pending.
The [implementation checkpoint](../checkpoints/2026-09-11-trusted-programme-release-sources.md)
retains focused evidence and corrections without claiming a successful failed run.
Runtime SELECT-only and explicit historical inventory changes require the ordinary
exhaustive acceptance scope; no history, gate or coverage threshold is waived.
Persisted independent approval and atomic publication/invalidation follow it,
then shared release-derived outputs/change impact. No release or profile is
activated, and #92's genuine human acceptance remains pending rather than waived.

The maintainer authorized unattended sequential delivery, without routine PR or
merge confirmation. Genuine human checks become explicit #48 follow-up subtasks,
not fabricated passes or waived activation gates. Keep one agent and current
reasoning unless a concrete unresolved problem requires escalation; independent
authorized work may proceed around such a dependency. After #48, continue with
#42 and the director introduction/pilot package, then the agreed guidance,
accessibility, continuity and succession priorities. No new schedule, production
deployment, personal data, repository-policy bypass or general cleanup is authorized.
Previous fixture/certification containers and watchers are closed; no schedule is
active. The label-verified `maru-issue94-postgres` focused-test container and its
anonymous synthetic volume were removed before certification; unrelated Docker
resources were not touched. Certification manages its own eight isolated services.
Preserve unrelated worktrees, stashes, data and containers.

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
  editing (#85); governed Programme staffing and Workforce coverage (#88).
  These remain dormant
  foundations, not a departmental workspace.
  [Events](../modules/events.md), [Applications](../modules/applications.md),
  and the [Programme Operations setup contract](../product/page-contracts/programme-operations-adoption-setup.md)
  own the details.
- **Release evaluation:** `v2026.08.27-rc.1` remains an immutable synthetic
  evaluation candidate. Exact-image runtime/static rehearsals and consumer
  integrity checks are bounded evidence, not provider or production acceptance.

## Smallest sensible next actions

1. Deliver #94's complete trusted release-source collection and missing owner
   evidence; preserve the existing independent scope and field boundaries.
2. Deliver persisted independent approval, atomic publication/invalidation,
   then shared outputs/change impact.
3. Continue on-site continuity, guided setup/surfaces and integrated
   Programme-only acceptance. Keep #48 open and preserve all activation gates.

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
