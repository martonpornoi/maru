# Current project state

Last updated: 2026-10-11
Phase: Guides integration with delivered workflow baseline; verification pending.

Maru is a Django/PostgreSQL modular monolith under synthetic evaluation, not a
production-ready release or supported hosted service. Furry conventions are the
primary audience. Occasional volunteers need plain language, accessible controls
and secondary technical settings. Each workflow must work without unrelated
modules. Continuous work and routine product choices are authorized; Programme
#48 remains deferred. [ROADMAP](ROADMAP.md) owns sequencing and the
[checkpoint archive](../checkpoints/index.md) retains history.

## Delivered baseline and active acceptance

Approachable navigation and contributor entry are delivered through
[PR #209](https://github.com/martonpornoi/maru/pull/209), protected main
`e77fae5b94dbee3e7f2e9d64b2f768be95888738`.

Standalone Announcements PR #210 and developer workflow PR #211 are delivered.
PR #211 merged on 2026-10-11 at 06:46 UTC as
`bc09e8b63e4142c712178a067a123c61b0924e2f`, after exact-head local and hosted
acceptance including all 77 PostgreSQL batches, PR gate and CodeQL. Its merged
tree matched the certified source and the clean main checkout was synchronized.
There were no submitted reviews or unresolved conversations. Guides inherits
the code, not those certification results.

Guides is now integrating that protected baseline using the shared Announcements
source `633fab4` to account for squash history. API contracts were regenerated. All 14,239 unit tests passed in 89.10 seconds;
strict typing passed for 881 source files, and lint/format/documentation checks
passed. No new browser result is claimed. Full exact-commit
certification of a6fd408 failed in the first database batch: three historical
lineage cases assumed Announcements was the final function successor, and one
Participation migration case created a current event after rolling its schema
back. The other active batches were interrupted, not independently failed.
Evidence is preserved. Scoped test-setup repairs retain all original assertions;
all five selected native cases passed in 596.17 seconds with unchanged source
and verified owned-container cleanup. A new full exact-commit certification
remains required. See the [repair checkpoint](../checkpoints/2026-10-11-guides-historical-test-repair.md).
The next full run on `34a3103` stopped after 37 minutes: 13 batches passed,
then Guides foundation checks failed after an empty historical migration round
trip. Seven other active batches were interrupted; all owned containers were
removed. Complete failed evidence is preserved. A fresh-versus-roundtrip probe
confirmed that dropping and recreating `adoption_revision` leaves a dropped
physical column slot, which the unchanged exact schema contract correctly rejects.
The single-connection test now isolates its real DDL with the existing rollback
helper and asserts restored schema and readiness. All 16 focused history-plus-current
cases passed in 492.60 seconds, with unchanged source and owned cleanup;
see the [schema isolation checkpoint](../checkpoints/2026-10-11-guides-schema-isolation.md).
Full `6d732f5` passed the repaired Guides batch, then stopped after 52m57s on
an older orphan-recovery test using current models after schema reversal. Failed
evidence is preserved. Creating calls before reversal was correctly rejected by
the retained-evidence downgrade fence in a focused failed attempt. The fixture
now creates its old call graph with historical models and native guards enabled,
then restores all current leaves before exercising recovery. A focused attempt
exposed generic historical question visibility defaults; the fixture now sets
the closed Programme flags explicitly. The next native check identified missing
activation actor/time, now retained alongside the exact receipt. Creation and
activation then passed, but current-model loading in the retirement helper failed
against the old schema. Retirement now also uses historical models with exact
structure version, actor/time and receipt under native guards; the former
dependency-probe monkeypatch is removed. Both focused native cases passed in
418.60 seconds with unchanged source and verified owned cleanup. Full exact-commit
certification remains required; see the [orphan fixture checkpoint](../checkpoints/2026-10-11-guides-orphan-fixture.md).
The existing synthetic runtime fixture remains stopped and preserved.

## Guides scope and verified outcome

[ADRs 0118–0119](../architecture/decisions/0118-reviewed-internal-guidance.md)
and KNO-010–013/EVT-008 define independently reviewed internal guides,
current-only reading and contextual placement, replacement, withdrawal, portable
outputs and separately accepted responsibility. Fresh `guidance_only@1` and
explicit Announcements expansion preserve unrelated workflows. Platform status
does not grant content access. [ADR 0124](../architecture/decisions/0124-evidence-bound-adoption-transition-effects.md)
adds an evidence-bound transition route without changing old profile meanings.

Before this reserve repair, the corrected workflow/routing selection passed 44 native cases in 431.76 seconds
(wrapper 438.062). Migration/recovery passes eight in 350.78 seconds (wrapper
357.156). Both source inventories matched and exact owned containers were removed.
These owner-login selections are separate from the genuine runtime proof below.

The isolated V6 fixture passed real `maru_runtime` provisioning: all 25 role/ACL
flags plus the derived current-session check, all five owning integrity gates,
provenance ready with zero blockers, health HTTP 200, and Django/migration checks.
Actual synthetic people accepted separate Announcements and Guides-only scopes.
The corrected command continuation independently approved two guide copies, kept
the first current during replacement review, withdrew the second, and proved
self-review and reader private-history refusals. Announcements remains unexpanded
and its approved copy unchanged. Runtime/provenance checks passed before and after.

The original helper confused an item ID with a revision ID. Its failed run and
invalid self-review evidence remain preserved and are not counted as success.
The exact fixture container is stopped, its volume/accounts retained and web port
free. No authenticated browser or human journey occurred. Credential entry and
the combined browser expansion remain unresolved; full Guides certification,
complete accessibility, print and operational acceptance are still open.

The [identity/routing checkpoint](../checkpoints/2026-10-09-guides-event-identity.md)
and [ACL checkpoint](../checkpoints/2026-10-09-guides-aggregate-execute-hardening.md)
retain exact source inventories, prior failures, timings and runtime artifacts.
The preserved `ba5c83e1` source passed 14,160 units in 76.25 seconds. Those full
units, handbook, native and runtime results predate this batch; they do not prove
the revised native guard.

## Withdrawal reserve and focused feedback

Ordinary writes now retain 8 KiB for one reasoned withdrawal inside the unchanged
8 MiB history cap. The native check uses the final persisted head, including an
ordinary write followed by withdrawal in one transaction. The **Remove guide from readers** page
identifies the affected copy and explains that pending review ends. KNO-011–012,
ADR 0118 and the [reserve checkpoint](../checkpoints/2026-10-10-guides-withdrawal-reserve.md)
record the contract, capacity limits and exact evidence.

Focused feedback passed 117 units, then 60 affected presentation cases after the
final wording refinement. The fresh native reserve selection then passed **two
cases in 326.98 seconds** (333.219-second wrapper), with unchanged source and
exact owned-container cleanup. This owner-login evidence proves the selected
reserve boundaries; it predates the later source-channel admission correction.
The isolated timing does not recalibrate the complete planner: its explicitly
unmeasured conservative fallback remains unchanged.

New Guides command attribution now fits Audit's existing 40-character ceiling
before any owner writes or retry lookup. Noncanonical text keeps its original
error; exact retries and fixed `knowledge-html` UI attribution are unchanged.
The historical receipt field and reserve bound remain 80 characters. No model,
migration, SQL, pin, runtime permission or route changed for this correction.
Installed focused feedback passed **79 units in 0.75 seconds**, with zero database
calls; scoped lint, formatting, typing, Python-docstring and documentation checks
passed. This is focused source feedback, not a new full-suite result.
The stopped genuine-runtime fixture and its seven harness inputs remain untouched.
Already-full legacy histories cannot gain a reserve retroactively; old installed
K0002 does not acquire this pre-release guard edit without fresh migration.

## Preserved source and presentation

The [decisions](../checkpoints/2026-10-09-guides-bounded-decisions.md),
[theme](../checkpoints/2026-10-09-guides-admin-theme.md),
[Access](../checkpoints/2026-10-09-guides-access-language.md) and
[roadmap](../checkpoints/2026-10-10-roadmap-focus.md) checkpoints retain prior
source and synthetic presentation evidence, not authenticated acceptance.

## Other active checkouts

Each checkout owns its independently reviewed observations, native and runtime
evidence. Help desk, Reading and Service retain their own unfinished-work gates;
none inherits this reserve change, the Guides runtime result or permission to
activate unfinished work. Propagation requires separate source and native review.

## Smallest next actions

1. Preserve the passed native reserve evidence and later admission-fix feedback.
   Resolve browser credential entry before the genuinely unrun combined expansion;
   retain the stopped fixture.
2. Follow the corrected [Guides walkthrough](../operations/guidance-maintainer-walkthrough.md)
   for the browser/manual journey. Source review corrected initial roles, the
   review screen path and replacement submission; the walkthrough is still unrun.
3. Freeze Guides, then run its complete exact-commit certification and protected
   hosted acceptance. Verify dependent workflows against their own boundaries.

## Verification and retained boundaries

Follow [local certification](../development/local-certification.md): focused
feedback, complete inexpensive units, then one clean required run with `CI=true`,
pinned pnpm 11.9.0 and unchanged coverage/timing gates. Hosted acceptance is
independent. Announcements released the local pool; its hosted checks are separate.
Keep local native fixtures sequential and never overlap full local certification.
Preserve failed evidence; stop or remove only exact owned resources.

Programme #48, #92, #109 and #108 remain open. Return through its
[evidence map](../operations/programme-acceptance-evidence.md),
[maintainer walkthrough](../operations/programme-maintainer-walkthrough.md),
[human session cards](../operations/programme-human-acceptance.md) and
[archive runbook](../operations/programme-exit-archive.md). Deferral changes no
Programme manifest or activation/independent-person/specialist acceptance gate.

Preserve the original Programme checkout, unrelated worktrees/resources and
stashes `5b6851f`/`dd651ef`/`3cc5df`/`9fecfe`, plus isolated P12/#96 work. Keep
Windows Animation effects disabled. No production deployment, broad Docker
cleanup or new automation is authorized by this batch. Repository metadata is a
separate settings change.

## Maintained demo coverage

Extend ongoing/future fictional editions with Guides samples when its browser
fixture is safe and verified. Current demo dates and seed remain unchanged; no
complete UI coverage is claimed.
