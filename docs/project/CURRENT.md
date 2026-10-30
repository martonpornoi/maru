# Current project state

Last updated: 2026-10-30
Phase: Workforce operating home (#225, child of #35); PR #226 review repair.

## Workforce operating home — 29 October 2026

PR #224 is protected-delivered as `ac5f099e50624fbe7f0824a97b9b4309c45df7bc`;
the merged tree equals certified `6e0646d5abdb9e6f196c233c1bb60bc31e678575`.
Fresh local and hosted acceptance passed 14,521 units, 5,173 current native cases
across 21 shards, 128 frontend cases, and hosted combined coverage 91.1715%.
All three CodeQL analyses were clean, four review conversations were resolved,
and clean main was advanced fast-forward only. #223 is closed; #22 stays open.
The older source-stage record below remains historical.

The maintainer approved completing the Workforce operating-home milestone
thoroughly, including routine design decisions and protected delivery, without
waiting for input. #225 is a native child of #35. UX-032 and new ADR 0128 extend
the existing owner projection through Assignments, shared Availability, Shift
decisions, completion and closeout, with at most four independently admitted
items. Existing domain rules, capabilities, field ceilings and independent
decisions remain authoritative. No migration, profile expansion, new grant,
mutable task store, attendance or activity tracking is introduced.

The implementation adds pure state choices, an owner work-phase reference,
bounded current-state metadata queries and a primary/attention presentation.
It loads no person labels, rationale, documents or exact Availability periods.
An unavailable area preserves other admitted work; a quiet area makes no
whole-event readiness claim. The first native run passed all 40 cases, including
the real Assignment/Availability/Shift closeout sequence and retained setup
regressions, with identical source/resource inventories and exact owned cleanup.
Subsequent failure-path regressions exposed setup-only error propagation and
grant/lifecycle movement during audit. Their repairs recheck after audit and at
aggregate release, fence upcoming expiry/start/end boundaries and preserve other
admitted areas. All 182 focused units and the complete 14,621-case unit suite
pass, with eleven existing warnings. Strict types pass over 897 source files,
both docstring checks and a fresh warning-fatal Sphinx build pass, and both fresh
dependency audits report zero vulnerabilities. Expanded native feedback passed the six new
revocation, time, phase and query-boundary cases and both existing demo cases.
Its one failed new assertion incorrectly assumed platform oversight was denied;
the corrected test passed separately without changing the existing policy.

`--scenario workforce` uses its own exact-profile ongoing/future fixtures and
generated role accounts, genuine owner commands, exact provenance and restricted
runtime login. The existing Announcements/Guides default keeps its meaning.
The genuine restricted-runtime browser rehearsal completed independent Assignment
approval, private/shared/empty/withdrawn Availability, claim confirmation, refused
stale-coverage locking, renewed evidence/reconfirmation/locking, and actual-time
Shift completion. Other-edition and role denials disclosed no protected records.
Seven widths from 320 to 1920 pixels had no horizontal overflow; keyboard drawer,
focus and owner-link activation worked. The repaired list was repeated at 320,
390 and 1280 pixels with no stray markers, one named list and three items; light
and dark rendering were checked. A normal zoom shortcut made no measured change, so 200% zoom and
specialist screen-reader acceptance remain unverified. All ten original stopped
fixtures were retained; the preview's owned database and server were stopped,
with exact before/after source and resource equality. These are development
observations, not final exact-head local or hosted acceptance. The two new
diagnostic timing-inventory paths use the established median fallback; every
prior weight and the authoritative group-cost map remain unchanged. Both new
groups keep their conservative largest-known fallback for full acceptance.

The first complete ordinary Auto attempt failed at native shard 57 after all
14,621 units and 56 native shards passed. Seven running shards were interrupted
by normal failure cleanup; all 64 owned containers were removed and ten original
stopped fixtures retained. Failed originals are preserved. Two isolated
reproductions traced the failure to a historical Programme import test that
removed and re-added Events' `adoption_revision`, leaving a dropped physical
column slot in the shared database. Current migration leaves alone do not
restore its pinned shape. The test now uses the existing committed-history
isolation fixture, including exact before/after setup schema and readiness
assertions. Its original body, the genuine-runtime readiness assertion, production
pins, migration sources, inventory and timing weights are unchanged. Both original
tests now pass together, with exact source/resource equality and owned cleanup;
the fixture's before/after schema and readiness checks also pass. See the
[isolation checkpoint](../checkpoints/2026-10-30-workforce-home-native-isolation.md).

Complete ordinary Auto subsequently passed on clean `ef383e1c`: all ten gates,
14,621 unit cases, 5,355 native cases across 111 shards and historical groups,
128 frontend cases and 91.3068% combined coverage. Independent reconciliation
covered the complete plan and identities, native phases, source pins, measured
headroom, peak eight, exact owned cleanup and all ten original stopped fixtures.
All three exact-head CodeQL analyses were clean. These results apply only to that
commit. All original evidence is preserved.

Ready PR #226 received its single automated review. Two supported gaps remained:
owner records could change after the initial stable pair without invalidating
the released continuation, and setup editability could survive a later lifecycle
change. Twenty new regressions reproduced them. A fresh checkout preserves the
certified source and outputs. The repair repeats complete bounded source checks
before/after audit and at aggregate release, checks time fences after the source
probe, and rechecks existing setup lifecycle gates after operating-area checks.
Read-only setup loses its target and management hint; unavailable remains
unavailable. No permission, domain rule, migration, inventory or timing policy
changes. The obsolete hosted attempt was cancelled and fully preserved; its
incomplete matrix and red aggregate gates are not acceptance.

Final expanded focused unit feedback passed 132 cases. Expanded native feedback passed
49 cases and failed seven new assertions that incorrectly expected an empty
Assignment plan after approval, or unchanged operating items after an edition
version change. The source-discard and setup read-only checks passed before those
assertions. Only the new expected-state assertions were corrected. All eight
affected native cases subsequently passed in 286.76 seconds, including refreshed
owner consequences after the earlier stopping assertions. Independent readback
confirmed all 3,288 source hashes before, after and live, unchanged production
bytes, the helper pin, exact owned cleanup and all ten original stopped fixtures.
Whole-source lint, strict types, both docstring checks, documentation policy and
a fresh warning-fatal Sphinx build pass. Result-only prose is policy-checked
separately; complete certification repeats the documentation gate. These focused
results do not certify a clean commit or replace complete hosted acceptance.
Both failed and successful originals remain preserved. See the
[review checkpoint](../checkpoints/2026-10-30-workforce-home-review-freshness.md).

Next: perform fresh exact-head ordinary Auto on this review repair and independently verify
new hosted checks, CodeQL, review disposition and protected squash/main
synchronization. The single review request is consumed. The manual-test
environment, accounts, saved records and 113-checkbox guide stay untouched.
Broader #35 contributions, #23 independent accessibility, #24 attendance,
#42 recipient-owned acceptance and production/operational gates remain open.

## Latest handoff — 29 October 2026

PR #222 is protected-delivered as `968607e93b92bc5dbb9acca52fd6e7cb6854c935`.
Its tree `17b572a416bc352367d89c02500fcfa0ddc84766` equals the exact certified
candidate. Local and hosted acceptance passed 14,438 unit cases, 5,329 native
cases across 111 shards, 128 frontend cases and 91.2872% combined coverage;
all three CodeQL analyses were clean and all review threads resolved. Hosted
headroom and complete original artifacts were independently reconciled. The
maintainer explicitly authorized merge, and clean designated main was advanced
fast-forward only with local/origin/remote/protected equality. The temporary
monitor was deleted. No manual-test environment, accounts, data or checklist changed.

The maintainer then authorized the next bounded task without routine input.
Issue #223, a native child of #22, adds an offline integrity command for existing
rota ZIPs under HR-016 and ADR 0127. It checks fixed members, a closed manifest,
lengths and SHA256 hashes without extraction, HTML/schema execution, network,
Django, database or domain writes. It adds no dependency, format/profile meaning,
web route, authority or audit event. Matching hashes do not establish authenticity,
schema validity, freshness, current permission, restore or operational readiness.

The first clean head `beecadaf` passed independently reconciled ordinary Auto:
14,497 unit cases (eleven existing warnings), all 5,173 required current-schema
native cases across 21 shards, 128 frontend cases and 91.1749% combined coverage.
All ten gates, complete selections/native phases, source hashes, headroom and
exact cleanup matched. All 12,155 raw local originals are sealed in place;
the nine unrelated stopped fixtures and stopped manual database were retained.
All three exact-head CodeQL analyses were clean. That evidence applies only to
the first head; it does not certify the current repair.

The single automated review found four supported gaps: ZIP64 directory override,
size-truncated member reads, FIFO opening before type validation, and argument
errors echoing rejected paths. New regressions against the first implementation
recorded 17 failures and one Windows non-regular-input pass. The obsolete hosted
application run was cancelled; its partial results are not hosted acceptance.
A fresh checkout retains the old certified outputs unchanged.

The repair measures complete bounded stored/deflated streams and CRCs, validates
matching contiguous local/central members, refuses ZIP64 locators before entry
construction and ZIP64 extra fields, opens descriptors nonblocking where supported,
and uses fixed argument-error output. All 89 focused checker/exporter cases pass,
including 83 checker cases. Windows covers descriptor flags and a real directory
refusal; the conditional real Unix FIFO regression still needs its Linux hosted
run. Maintained exporter bytes, dependencies, server authority and format remain
unchanged. Whole-source Ruff, strict types over 893 files, both docstring checks
and documentation policy (780 Markdown files, four skills, 223 requirement IDs)
pass. Earlier new-test style, binary-unpack type and indirect-exit docstring
findings remain recorded. Fresh exact-head certification is still required.

Earlier feedback remains separate: one wrong docstring-tool invocation, one
test-string line-length failure, and a restricted Windows full-unit run whose
eight unchanged existing cases could not link/replace files or use loopback.
The complete unchanged suite then passed with normal file/socket access and a
fresh task-owned temporary directory. No application assertions were weakened.
These older failures remain separate from both the first exact-head success and
the supported review repair. Next: commit normally, run fresh ordinary Auto in
the new checkout, then publish and
verify new hosted checks, review disposition and protected delivery. The one
review request is consumed; do not duplicate it. See the
[initial checkpoint](../checkpoints/2026-10-29-workforce-rota-integrity-check.md)
and [review repair](../checkpoints/2026-10-29-rota-integrity-review-hardening.md).

Maintained demos and their role walkthroughs are unchanged: this is an offline
file command with synthetic CLI examples in the owning runbook, not a new UI
journey. #22 remains open for import, reconciliation, full history/exit and
recovery work. Human invitation, browser/accessibility, operational and production
acceptance remain open. Older notes below retain their historical evidence.

## Latest handoff — 28 October 2026

The maintainer authorized marking PR #222 ready, completing hosted acceptance
and addressing in-scope findings, with the PR left unmerged. The previously
certified `61197159` passed all ten local gates on 26 October: 14,433 units,
5,329 native cases across 111 shards, 124 frontend cases and 91.2797% combined
coverage. Its complete source and original evidence remain intact in the
retained checkout. A fresh checkout now owns the repair branch so no sealed
local-CI or documentation outputs are overwritten.

The ready-state hosted audit found msgpack 1.2.1 affected by CVE-2026-114613;
the global advisory was published after that local certification. The remaining
quality job was cancelled after the known failure; no hosted unit/native or
combined-coverage success is claimed. Complete job pages and run logs are
preserved with SHA-256 readback. Official upstream evidence supports the bounded
1.2.3 repair; CacheControl's old and new serialized response bytes match and its
valid/invalid-cache checks pass. Fresh Python and all-severity frontend audits
report no known vulnerabilities.

The single Copilot review identified three supported interface defects, repaired
together: local access-expiry parsing now exposes an associated error while
retaining inputs; panel badges use paired theme colors; suspended accountable
access has review/recovery guidance instead of provisioning instructions.
Focused template/input feedback passes 117 cases; all 128 frontend cases pass,
and the four expiry regressions pass again after the final accessible-label
adjustment. Type checking and the normal production build pass. Supplied-state
browser checks retain readable badge colors and correct recovery text at actual
320/768/1,280 CSS pixels; dark badge contrast is 16.45:1. Invalid share expiry and
correction were exercised against synthetic responses only. Replacement submission
was blocked by automatic browser approval review, so its correction evidence is
automated component coverage. No signed-in human journey is claimed. Complete
certification remains pending; failed helper/environment/new-test assumptions
remain separately recorded. See the
[hosted-findings checkpoint](../checkpoints/2026-10-28-interface-repair-hosted-findings.md).

Next: complete focused verification, commit normally, run one fresh ordinary Auto
certification of the clean repaired head, push and independently verify new hosted
acceptance and review disposition. No merge, deployment, protection changes,
manual-test restart/data changes, password handling or invitation acceptance is
authorized. Independent human/accessibility/operational/recovery gates remain open.

## Latest handoff — 25 October 2026

The maintainer requested continued work that needs no manual verification, with
their browser continuation left for tomorrow. PR #221 is already merged at
`7bd59c0bf1130a7ebc8b202d0f47b2bc26c9182b`; its old source-checkpoint next steps
below are historical. No rota certification or implementation was restarted.

The 24 October interface repairs and tutorial are copied into an isolated
`codex/manual-interface-delivery` candidate based on that protected result.
The original manual-test worktree, running services, saved records, passwords
and checklist are unchanged. Automated review also fixes choice-group help
references: each fieldset describes its own help and errors through unique
field IDs. New regression coverage checks two invalid groups together. Two
new widget docstrings now document their default arguments correctly.

Verification results and remaining boundaries are recorded in the
[automated-preparation checkpoint](../checkpoints/2026-10-25-interface-repair-automated-preparation.md).
Fresh development feedback passed 14,433 units, 124 frontend cases, strict types,
lint, both docstring checks and a warning-fatal documentation build. All six
generated API/frontend files reproduce byte-for-byte. The original manual-test
source snapshot remains unchanged; full native acceptance was not run.
This candidate is for draft review, not certified merge or production use.
The maintainer subsequently authorized overnight complete automated
certification and in-scope failure repair, retaining draft status. Follow the
[overnight scope](../checkpoints/2026-10-25-interface-repair-overnight-certification.md).
The first exact-head attempt failed its dependency audit on filelock 3.32.0.
Its 14,433 units passed; the pool was explicitly cancelled after that known
failure: eight shards were interrupted and 103 unstarted. All eight owned
containers were removed, original resources/source remained unchanged, and
1,010 original evidence files were preserved with equal SHA-256 hashes.
The bounded [security repair](../checkpoints/2026-10-25-interface-repair-security-dependencies.md)
updates only filelock to 4.2.1 and the existing undici override to 7.30.1.
Fresh audits are clean; 107 other Python and 173 other frontend package records
remain exact. Audit-cache interoperability and all 124 frontend cases pass.
The repaired clean candidate still needs complete fresh certification; the
first failed attempt and focused feedback do not certify it.
The second attempt at `6ac89b41` passed 48 native shards, all units and the
non-database gates, then found one obsolete integration assertion expecting
**Set up Workforce** instead of the accepted **Set up a volunteer team** label.
Seven active shards were cancelled and 55 were unstarted. Original source and
resources stayed unchanged; all owned containers were removed. Its 4,885 local-CI
and 5,774 documentation-build originals are hash-verified in preservation storage.
The assertion now follows UX-031 and the existing page contract, with every
other lifecycle, input and authorization assertion retained. See the
[native-title repair](../checkpoints/2026-10-25-interface-repair-native-title.md).
The complete focused native case passes in a fresh owned database; independent
AST/resource checks retain every other statement and confirm exact cleanup.
The new clean candidate requires fresh complete certification; no result is
borrowed from either failed attempt.
The exact pinned receipt and PR #222 own the run outcome; this source checkpoint
does not predict its result. Hosted merge acceptance and protected delivery
remain required. Human invitation acceptance, Alex's Crew continuation and the
broader independent-person/accessibility/recovery gates remain open. Incorporate
tomorrow's observations separately; any later changed head needs fresh proof.

## Latest local handoff — 24 October 2026

The maintainer completed manual account, governance, registration-draft and
Department setup, then reported navigation, contrast, choice alignment, typed
date-entry, naming and tutorial problems. Local repairs now restore the owning
Create organization action, consistently label Set up a volunteer team, keep
radio controls beside their labels, use theme-aware action/required/error colors,
and provide typed ISO dates / 24-hour local times across maintained browser forms
and staff-console inputs. Existing domain precision, DST validation, API formats,
authority, native guards and adoption boundaries are unchanged.

The volunteer wizard now requires a deliberate create/reuse choice and shows
stable organization locators beside reused names. Existing unfinished volunteer
workspaces point to Finish accountable access. The tutorial's hyphenated question
keys match their actual validator; its 113 checkbox positions and browser notes
are retained.

**Actual blocker:** Crew belongs to a second, still-provisioning organizer,
`synthetic-moonfox-organizers-2`; Alex's active Board appointment belongs to the
original organizer. No access was copied or granted by this repair. The updated
[guide](../operations/blank-start-manual-test.md#continue-after-the-24-october-test-reports)
gives the exact admin invitation → Alex/Blake self-acceptance → Maru-operator
activation → Crew Structure/Positions continuation. Both editions and every
existing manual record are preserved; the two editions deliberately exercise
different profiles, while the accidental second organization explains the access
gap. A fresh test should explicitly reuse the original series.

14,432 database-free unit cases passed (11 existing warnings), all 124 frontend
cases passed and the normal frontend type-check/build passed. The first broad
run remains recorded as failed: two obsolete display expectations and 512
inaccessible-global-temp-folder setup errors were diagnosed; a fresh owned temp
directory and exact new display expectations resolved them. Browser smoke
verified the actual action/title/date/reuse/access continuations. Actual widgets
were separately measured at 312, 614 and 1,024 CSS pixels in a synthetic preview,
with no overflow and all six radios beside text; light/dark checks covered
contrast. This is bounded local feedback, not full certification, native-history,
hosted, independent-person or production acceptance. See the
[repair checkpoint](../checkpoints/2026-10-24-manual-test-interface-repairs.md).

**Next:** hard-refresh the running local test and follow the guide's recovery
section, then continue step 10. The agent has not accepted governance invitations
or entered any of the maintainer-created people's passwords. No commit/push/PR
or deployment was requested for this local repair. Maintained demo data is
unchanged; the from-empty guide records the current representative journey.

## Latest local handoff — 23 October 2026

The maintainer requested a big GUI test from one administrator and zero project
data. The [from-empty checklist](../operations/blank-start-manual-test.md) has
13 main steps and seven optional branches, copy-ready fictional inputs, expected
results and notes. The separate persistent local environment contains one admin
and no ordinary people, organizations, series, editions or other business data.
The maintainer will create every further account and convention record manually.
Private launchers/login/keys/logs remain in ignored local storage; see the
[preparation checkpoint](../checkpoints/2026-10-23-admin-only-manual-test.md).

Migrations/system checks and actual browser login, one-account/zero-organization
inventories and supported invitation/organization form smoke checks passed.
Interactive checklist ticks/notes persisted after reload and were then cleared.
Stop/Start preserved the initial password and zero business data; all nine
unrelated stopped containers were unchanged. The organization inventory omits
its Add link; the guide links the mounted authorized GUI form and records that
navigation gap. The complete mainline is left unperformed for the maintainer.
Documentation policy/whitespace checks cover this documentation-only preparation.

Registration supports canonical draft construction; complete activation/public
checkout remains incomplete. Programme timetable activation is still gated.
Volunteer Shifts supply this guide's available scheduling journey. No guard,
profile, authority or recipient-owned password acceptance boundary was bypassed.

PR #221 is now protected-delivered as
`7bd59c0bf1130a7ebc8b202d0f47b2bc26c9182b`, certified tree
`2eea52b1fc3ca92522c327b0f993816bbb1e9aa0`; exact-head hosted acceptance,
three clean CodeQL analyses, protected squash and designated-main fast-forward
equality are verified. Its heartbeat was deleted. Original failed/successful
evidence and the separate #42 human-acceptance boundary remain preserved.

**Next:** start the prepared environment on 24 October, follow the GUI checklist,
record findings and Stop to retain work. No commit/push/PR, application repair or
production approval is claimed by this local preparation.

**Historical pre-delivery checkpoint below:** retained intact for continuity.
Its outstanding PR #221 certification/delivery steps were subsequently completed
as recorded above and in PR #221/ignored delivery evidence. They are not the next
actions for the newly authorized manual test.


Maru is a Django/PostgreSQL modular monolith under synthetic evaluation, not a
production-ready service. Follow [ROADMAP](ROADMAP.md), requirements and owning
contracts. Programme activation remains deferred. Complete one independently
adoptable workflow before expanding breadth.

## Last protected outcome

[PR #220](https://github.com/martonpornoi/maru/pull/220) delivered the first
owner-projected Workforce home continuation on 2026-10-21 as
`0988157ee761b4b547d5fea9d128ca873af8f813`. Its tree
`9566941311d7189cc2b13d2dfd8161abc4b1291a` exactly matches certified source;
designated clean main was fast-forwarded and local/origin/remote/protected
result equality verified. All ten final local gates passed: 14,335 units,
5,304 native cases, 111 history shards and 91.2621359223301% combined coverage.
Fresh hosted acceptance passed 122 jobs with three normal alternative skips;
all three exact-head CodeQL analyses were clean and both valid review findings
were repaired/resolved. Complete original evidence, including all failed
attempts, remains preserved. The completed heartbeat was deleted.

PRs #218/#219 also remain protected-delivered. #35/#36/#42 stay open; their issue
baselines now distinguish delivered work from remaining scope while retaining
the original text. The prior unexplained home archive audit-guard rejection
remains unreproduced, not fixed. Diagnose any recurrence without weakening guards.

## Current authorized outcome

The maintainer requested autonomous continuation through verification and
protected delivery without routine input. HR-016 and ADR 0127 define the first
#22 slice: an exact `workforce_only@1` Shift/retained-commitment snapshot,
versioned JSON and closed schema, integrity manifest, standalone print HTML and
[operating-copy guidance](../operations/workforce-rota-package.md).

The adapter resolves opaque route IDs before named reads. Authorization's
verified-current-principal seam admits complete edition/Shift fields and separate
existing Shift-management authority. One repeatable-read snapshot, complete
inventory limits, final scope/field/current-principal admission, metadata comparison
and required minimized audit protect disclosure. No capability/profile/role meaning,
schema, runtime privilege, domain writer or notification changes. A necessary
Vitest development-tool patch and DRF runtime security upgrade are documented
below; unrelated dependency records remain exact.
The copy excludes platform account IDs, private calendars, identity contact fields,
application/documents, decision reasons and unrelated module data.

## Verification and delivery still required

Seven-source types, scoped Ruff/NumPy docstrings and documentation policy passed.
Six package units and 76 native cases passed with complete independent source,
selection/JUnit/all-phase identity/order/duration and exact cleanup verification;
the original three native modules' ASTs remain equal to base. Two earlier focused
failures are preserved: audit metadata used unsupported keys, then a deactivation
fixture incorrectly targeted a Board controller. Repairs retained every guard
and denial assertion. See the [checkpoint](../checkpoints/2026-10-22-workforce-rota-portability.md).

After two copy-only corrections, supplied component feedback passed all 21
state/width measurements at 320 through 1,920 CSS pixels: one H1/main, unique IDs,
no overflow, escaped text and no console warnings/errors. Keyboard focus and
fixture navigation were checked with an honest bounded click fallback. Both
preview servers/tabs were closed and viewport overrides reset. This is not real
sign-in, true zoom, screen-reader, human or actual printer/PDF acceptance.

The new native file's measured whole-file inventory entry is 126.911 seconds;
all inherited entries, group fallback, histories, selection, resources, worker/timing
limits and 90% coverage target are unchanged. All 14,341 database-free units passed
in 103.30 seconds with three existing Django warnings; actual JUnit identities and
complete original artifacts were independently preserved.

A fresh all-severity precheck found two moderate Vitest mocker advisories. The
supported 4.1.12 patch changes only Vitest and its seven matching internal packages;
all 166 unrelated locked records/snapshots, Node engines and exports remain exact.
Frozen installation, fresh Python/frontend audits (zero known vulnerabilities),
all 116 frontend cases, generated API/types, production build, whole-source Ruff,
strict types and NumPy docstrings passed with byte-identical generated assets.
Complete before/after/live source hashes and 158 original artifacts were verified.
The later semantic-docstring stage found one summary-quality violation; its
wording-only repair preserves the executable AST. That failed invocation stays
failed, with later stages explicitly unexecuted. Fresh Ruff, both docstring
checks, documentation policy, exact timing-inventory unit and whitespace passed;
source/JUnit/original-artifact readback independently verified the final tail.

The first exact-head ordinary Auto attempt passed 14,341 units, then stopped on
two existing demo failures in native shard 43. Forty-one shards completed, seven
were cancelled and 62 were unstarted; no combined coverage or success receipt
exists. Complete failed evidence and exact resource cleanup were preserved.

An unchanged 37-case reproduction proved that the scope-v2 history case leaves
three dropped/recreated EventEdition adoption columns after full-leaf restoration.
Native function/trigger checks stayed valid; the exact physical-schema guard
correctly refused Guidance activation. A test-specific fixture now runs that
committed current-to-historical-to-current sequence in a fresh owned database.
Every original body, target, assertion and full restoration remains intact.
The same 37 cases then passed in the original order in 1,022.00 seconds. Independent
source/selection/JUnit/all-phase/readiness/schema and exact owned database/container
cleanup verification confirmed the shared database remains unchanged.

The second ordinary Auto on clean `1f00882c` completed all 5,329 native cases
across 111 shards and all 14,341 units, with independently verified native phases,
identities/order/durations, plan/source, peak eight, measured headroom and exact
111-container cleanup. It still failed: the Python audit reported three high
DRF 3.17.2 advisories published after the earlier clean precheck. Later repository
gates and combined coverage were unexecuted; no success receipt exists. All
1,860 local-CI and 21 wrapper/temp originals are preserved and verified.

The required DRF 3.18.3 upgrade includes the security fixes and the upstream
3.18.2 regression correction. Only its locked package and the project's DRF
requirement change; all 106 other package records and lock policy remain exact.
The supported list-error compatibility option retains the existing positional
API problem contract without suppressing its deprecation warning. Focused
regressions cover charset refusal before body reads, bounded negotiation and
normal JSON, plus nested problem indices/codes. No permission, profile, schema,
runtime grant, guard, history, timing, worker or coverage rule changes. Maintained
demo data and walkthrough scope are unaffected.

Fresh dependency feedback passed both audits, all 14,349 units, all 116 frontend
cases, types and warning-fatal documentation, then failed generated-asset equality.
DRF changed the automatic read-only adoption code from text to a choice field.
An explicit read-only text projection and schema regression now preserve the
existing edition API and generated-client contract. The failed feedback's 10,449
originals are independently preserved in place; its passing stages are not full
acceptance. The focused mounted-schema regressions passed, and normal generators
restored byte-identical OpenAPI and TypeScript contracts.

Fresh complete non-database feedback then passed all 26 stages: 14,350 units in
78.22 seconds, 33 focused security/compatibility cases, all 116 frontend cases,
both zero-vulnerability audits, package/static/type/docstring checks, fresh
warning-fatal documentation, Django contract checks and byte-identical generated
assets. Eleven unit warnings remain visible, including the supported DRF list-error
option's deprecation. Independent reconciliation verified unique JUnit without
errors/failures/skips, every stage/order/duration, all 3,255 before/after/live
source hashes, all 38 cumulative changed hashes and the prelaunch/before/after/live
runner hash. All 10,449 originals are preserved and read back in place. No unit
phase observer or database acceptance is claimed. Only this outcome append follows
that feedback; documentation policy and whitespace must validate it before commit.

Fresh final clean-head Auto, independent hosted acceptance and protected delivery
remain required. Outcomes belong in the resulting PR and ignored evidence while
source is pinned. No failed, older or focused receipt certifies this candidate;
no production acceptance is claimed.

## Preserved human and operational boundaries

#42 remains at its actual human recipient-password/self-acceptance boundary in
the separate `codex/workforce-rehearsal` worktree. Do not restart, seed accounts
or use an alternate credential route to evade it. Its old disposable environment
expired with cleanup verified; no completed activation or human journey is claimed.
#23 retains its broader role/state accessibility matrix. Maintained practice
editions cover Announcements/Guides; a Workforce practice edition remains separate.

#22 stays open: import, complete history/exit export, approved manual
reconciliation, stopped-operation/restart, deliberate expansion, decommissioning
and representative restore/PITR remain unimplemented or unaccepted. Saved copies
cannot be recalled; approved custody/retention/disposal and incumbent fallback
remain necessary. Preserve all old receipts, worktrees, stashes, private
credentials, unrelated stopped fixtures and paused monitors.

## Smallest next actions

1. Complete final checks and normally commit the supported DRF security repair
   and API compatibility documentation; retain both failed full attempts.
2. Fetch actual current main and run fresh ordinary Auto on the exact clean head.
   Preserve complete originals; passing tests from an audit-failed run cannot
   certify the dependency-upgraded candidate.
3. Push normally, prepare the complete PR and verify exact-head hosted PR gate,
   all CodeQL provenance, requested-review disposition and resolved conversations.
4. Refresh no-bypass protection/current mergeability, exact-head squash, verify
   identical certified tree and fast-forward-only designated clean-main equality.
