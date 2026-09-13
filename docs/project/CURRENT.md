# Current project state

Last updated: 2026-09-13
Phase: Progressive adoption and pre-production release evaluation.

Maru is an actively developed Django/PostgreSQL modular monolith, not a
production-ready release or supported hosted service. Use synthetic data only.
This concise handoff owns current work; the [roadmap](ROADMAP.md) owns sequencing,
the [production ledger](PRODUCTION_CONSOLIDATION.md) retains the detailed baseline,
and [checkpoints](../checkpoints/index.md) preserve historical evidence.

## Latest protected delivery

[#99](https://github.com/martonpornoi/maru/issues/99) is closed through
[PR #101](https://github.com/martonpornoi/maru/pull/101), protected squash
`f999fb510b69901798959e16c120bf0fd15b839d` at 2026-09-13 01:10:30 UTC.
Its tree equals certified head `ed654e27ff1328fde01171e93d74ceb16c5676c6`;
clean local main was synchronized to that result and origin/main.

ADR 0097 delivers dormant public and exact-person host/volunteer output from
the active approved release. Independent owner authority, approved immutable
copy, separately versioned current instructions and retained Workforce work
stay distinct across typed/JSON/calendar/rendered/print adapters. Native
withdrawal/invalidation fails closed without silently cancelling or relocating
accepted Shifts. No profile, production route or runtime writer is activated.

ADR 0098 replaces fixed PostgreSQL counts and differing local/hosted partitions
with budgeted source-bound assignments, at most eight concurrent fresh databases,
incremental diagnostics and measured pre-push timing headroom. Full replacement
local certification passed all ten gates, 9,089 Python tests, 64 frontend tests
and 90.67% combined branch-aware coverage in 3h32m58s. All 39 local jobs passed
in 30m22s–51m54s; every disposable container was removed. The worst conservative
projection was 87m51s against the unchanged two-hour hosted limit.

Independent hosted acceptance, CodeQL and the protected PR gate passed on that
exact head. All 39 hosted PostgreSQL jobs passed in 27m22s–49m58s, median 39m58s,
with at least 70m02s timeout margin. Total hosted workflow latency was 3h19m26s.
Downloaded reports independently reconcile all 334 complete groups, 4,251
PostgreSQL cases and 4,838 units, with no failure, error, skip or duplicate.

This is timeout resilience, not a whole-suite speedup: exhaustive local wall
time increased 31.0% over the original eight-way run. Original timed-out hosted
attempts and the failed Windows Docker-wrapper launcher candidate remain
separate from the completely certified repair. No timeout, coverage or scope
waiver was used. Do not repeat completed certification.

See the [protected delivery checkpoint](../checkpoints/2026-09-13-programme-output-protected-delivery.md),
[output evaluator guide](../operations/programme-output-evaluation.md),
[ADR 0098](../architecture/decisions/0098-budgeted-postgresql-shard-planning.md)
and [local certification procedure](../development/local-certification.md).
The prior atomic release #96 / PR #98 remains delivered under ADR 0096.

## Active bounded delivery: operator run sheets (#100)

Branch: `codex/programme-operator-run-sheets`, based on the protected #101 result.
[#100](https://github.com/martonpornoi/maru/issues/100) is the next native #48
child. It retains the room/department/operator acceptance explicitly separated
from #99; closing #99 does not deliver or waive that audience.

[ADR 0099](../architecture/decisions/0099-purpose-scoped-programme-operator-outputs.md)
and the [run-sheet page contract](../product/page-contracts/programme-operator-run-sheets.md)
define independent room, Department and edition operator purposes. Department
membership follows current Venue responsibility and deliberately adopted
Workforce binding lineage, never inferred Programme item/proposal ownership.
Five new field-ceilinged read capabilities and native migration 0030 grant no
authority or profile activation; retained grant/role use fences downgrade.

Local typed/JSON/calendar/shared-Administration-shell HTML/print implementation
is present, with exact-purpose admission, mandatory owner audits, current room
and retained-work membership, checked release geometry and reviewed copy, and
requested-only private delivery/staffing fields. Current owner instructions and
immutable accepted work intervals remain separate. No #100 certification, push
or protected acceptance is claimed.

Focused evidence: all 4,986 units passed in 34.20s (two existing Django URL-field
deprecation warnings); 17 PostgreSQL cases passed in 299.59s including fresh
schema setup (156.36s). They cover exact native scopes, person/tenant denial,
withdrawal, mandatory audit, requested-column privacy, a Department with linked
work but no room, retained predecessor intervals, real HTTP reauthorization and
real unused migration reversal/reapply plus retained grant/role downgrade
fences. The disposable container was removed. Repository-wide Ruff, formatting,
type, NumPy-docstring and semantic-docstring checks pass. Earlier focused
failures were repaired fixture permissions and catalog inventories, not waivers.
The two real HTTP cases also pass exact-copy invalidation followed by release
withdrawal in a focused 183.31-second fresh-database rerun.

The isolated browser journey now covers exact-purpose/default/all-layer output,
retained work, denial, source failure/withdrawal, private downloads and print view.
A per-response CSP nonce repairs blocked shared navigation; modal semantics and
collapsed-section focus filtering repair the exposed keyboard boundary. Fresh
checks pass Close/Escape, focus containment/return, keyboard layer submission and
seven responsive widths without overflow. Fixture containers were removed by
exact ID. Launcher/observer failures and teardown-session warnings remain recorded,
not passing browser evidence. The warning-fatal documentation build also passed.

See the [operator checkpoint](../checkpoints/2026-09-13-programme-operator-run-sheets.md)
for evidence and limitations. Next: certify the clean exact candidate with its
source-bound PostgreSQL plan and measured headroom, then protected delivery.
Human-only native-print, zoom, screen-reader and calendar-client checks are
explicitly retained under #92 and remain unpassed. #97 still blocks activation.

## Existing foundation and mandatory gates

Programme children #57, #59, #61, #63, #66, #64, #71, #77, #79, #81, #85,
#88, #91, #94, #96 and #99 are delivered dormant. Do not restart those tasks.
The [Programme Operations contract](../product/page-contracts/programme-operations-adoption-setup.md)
and owning [Programme](../modules/programme.md),
[Applications](../modules/applications.md), [Events](../modules/events.md) and
[Workforce](../modules/workforce.md) documentation describe their boundaries.

#87 is closed through protected PR #90 for the maintainer's bounded native
Cancel/discard, actual 200% Chrome zoom and Windows Animation effects-off
observations. Preserve that preference and evidence; it does not satisfy new
integrated acceptance. The [browser checkpoint](../checkpoints/2026-09-11-programme-browser-protected-delivery.md)
records the one-off split-run exception without a fabricated success receipt.
#92 remains deferred human/screen-reader acceptance, not passed or waived.

#97 is open: logical dump/restore can re-render array-cast CHECK expressions and
fail exact schema readiness. Native guards/ACLs/recorder checks and same-image
physical recovery do not waive logical-restore acceptance. Preserve negative
weakened-constraint tests; do not blindly rebaseline fingerprints. This blocks
activation and a director pilot, not further dormant in-scope development.

## Smallest sensible next actions

1. Preserve #101's completed exact-head local/hosted evidence; do not rerun it.
2. Deliver #100's independently authorized room/department operator run sheets.
3. Deliver detailed change impact, governed destination delivery and recipient
   acknowledgement through the same output boundaries.
4. Continue on-site continuity, #97 logical recovery, guided setup/surfaces and
   integrated Programme-only acceptance. Keep #48 open through the complete
   journey; retain #92 and every other activation gate.
5. After #48, continue #42 and the director introduction/pilot package, then the
   agreed guidance/accessibility and continuity/succession priorities. #22, #23
   and #24 retain their separate Workforce ownership and are not absorbed here.

## Resume and operate safely

The maintainer authorizes unattended sequential PR/merge delivery. Use one agent
and current model settings; no schedules, policy bypass, production deployment,
personal data or general Docker cleanup. Preserve unrelated worktrees, stashes
and containers. Remove only exact verified disposable task resources.
Follow AGENTS, this handoff, roadmap, relevant contracts/ADRs and code/tests.
Use the [agent workflow guide](../development/agent-workflows.md) to load only
matching procedures; historical checkpoints are consulted as needed.

Workforce-only has guided structure/Position/Assignment/Availability/Shift
operation; complete exit/continuity and representative accessibility remain
open. Programme remains dormant, with no activated departmental workflow or
on-site pack. Provider/deployment/runtime provisioning, restore/PITR, supervision,
load, privacy, safeguarding, training and two-human operational acceptance are
still production gates. The immutable `v2026.08.27-rc.1` is synthetic evaluation,
not production approval. Never infer readiness from a page, test count or green CI.

[ADR 0090](../architecture/decisions/0090-risk-based-postgresql-acceptance.md)
retains current PostgreSQL behavior for code changes and exhaustive history for
global safety/harness changes. ADR 0098 replaces fixed job counts and differing
local/hosted partitions with budgeted exact assignments. Focused checks, exact local certification, hosted
acceptance and production approval are distinct. Historical-model reconstruction
is a measured cost; documentation or Docker cleanup is not a test-speedup claim.
