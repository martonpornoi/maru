# Current project state

Last updated: 2026-11-11
Phase: Reviewing and verifying the AI-assisted workflow policy for a pull request.

## AI-assisted workflow policy — 11 November 2026

The maintainer approved normal agent-operated fictional rehearsals, a local
documentation certification path, reusable read-only checkers and continued
routine work within the approved scope. [ADR 0134](../architecture/decisions/0134-bounded-ai-assisted-work-and-local-documentation-checks.md)
records those boundaries. The isolated candidate starts from verified
protected main and leaves the older workspace and GUI branch intact.

The Workforce launcher offers prepared fictional sign-ins in a fresh strict
fixture. Auto selects the local documentation checks only after the shared
classifier and exact tree diff agree on an eligible prose-only change. Its
separate receipt does not claim PostgreSQL or coverage. The unit suite passed
15,007 tests with one expected Windows skip. The real prose-only run passed
all 12 selected checks without Docker, and the prepared-sign-in fixture passed
startup and owned cleanup. The
[policy checkpoint](../checkpoints/2026-11-11-ai-assisted-workflow-policy.md)
records the exact scopes. Delivery review found that a local pytest option
could suppress the licensing test run. The documentation path now ignores
that option and 145 focused tests passed, including a regression for a failing
case. The certification harness requires exhaustive local and hosted checks
for this pull request. Browser and human acceptance remain separate.

## Catalog protected delivery — 5 November 2026

[PR #241](https://github.com/martonpornoi/maru/pull/241) delivered the product
and variant reference through protected squash
`f8510bcf01994bd76e67af56e3b4bdcbc189d60d`. Its tree matched the certified
candidate, and the clean local main was fetched and fast-forwarded with
local, remote and GitHub equality verified.
[PR #242](https://github.com/martonpornoi/maru/pull/242) then delivered the
batched stock projection through protected squash
`8c243d8d88f1973704f93105b8b83f58146f4daf`. Its tree matched the independently
verified candidate and its sole parent was the protected #241 result. The
designated clean main was fetched and fast-forwarded with local, origin,
remote and GitHub equality verified.

The combined read-reference increment in [PR #243](https://github.com/martonpornoi/maru/pull/243)
retains both delivered outcomes. Its full exact-head local and hosted acceptance
is tracked in that PR; the [review checkpoint](../checkpoints/2026-11-05-catalog-protected-review-and-read-reference.md)
records scope and focused feedback. The next #36 work is the remaining handled
response contracts and the documented completeness, consistency, audit,
dependency-failure and compatibility decisions.

## Catalog product and variant creation reference — 4 November 2026

This bounded INT-001 increment documents the existing product and variant
creation commands. The OpenAPI reference and generated TypeScript describe
new and replayed receipts, invalid and conflicting requests, denied access,
and unavailable catalogs or parent products. All 43 focused Catalog
PostgreSQL tests and 18 Catalog and Venues API unit tests passed. The native
cases compare HTTP responses with the schema and check that replay and
rejection preserve the original command evidence.
See the [Catalog API contract](../modules/catalog-api.md#product-and-variant-creation-responses)
and the [verification checkpoint](../checkpoints/2026-11-04-catalog-product-variant-openapi-contract.md).

## Catalog order history and activity reference — 5 November 2026

This INT-001 increment documents the observed order-history and staff-activity
responses. Order history returns only the caller's orders and can return an
empty list without a catalog. Staff activity is scoped to an authorized edition
and records its read audit before unsupported-query rejection. The native
matrix checks those existing effects against the generated response schemas.
The combined source passed 136 focused unit checks and documentation
validation. PR #243 tracks complete acceptance for its final integrated head.
See the [Catalog API contract](../modules/catalog-api.md#order-history-and-activity-responses)
and [checkpoint](../checkpoints/2026-11-05-catalog-read-openapi-contract.md).

Issue #36 retains the wider compatibility, self-read audit, completeness,
dependency-failure and concurrent-change decisions.

## Edition Catalog API reference — 3 November 2026

The previous INT-001 increment documents the edition Catalog read and draft
creation operations. OpenAPI and the generated TypeScript declarations now
describe verified success and problem responses, correlation and cache headers,
and fictional examples for a catalog read, draft creation and receipt replay.
The focused run passed 40 Catalog PostgreSQL tests, including validation of
actual HTTP bodies against the generated schema, and 119 focused unit tests.
See the [Catalog API contract](../modules/catalog-api.md#edition-catalog-responses)
and the [verification checkpoint](../checkpoints/2026-11-03-catalog-edition-openapi-contract.md).

Issue #36 remains open. Read completeness, read-audit policy, dependency
failure handling and broader compatibility work require separate review under
the [Catalog conformance plan](../development/catalog-edition-api-conformance-plan.md).

### Catalog route and read-cost review — 4 November 2026

The mounted Django routes, generated OpenAPI, checked-in schema, TypeScript
operation mappings and module route list agree on 11 operations across nine
paths. The 22 focused schema tests passed. Handled problem responses are
documented for six operations in the combined Catalog reference.

The [query-cost baseline](../checkpoints/2026-11-04-catalog-route-and-read-cost-baseline.md)
found two reads per finite-stock variant. The attendee Catalog API and page now
derive stock and commitments in the scoped variant query. The new native case
uses five SQL statements with either one or twelve variants and verifies the
latest adjustment, pending and paid quantities, zero stock and stockless
output. The 41 Catalog PostgreSQL cases and 119 focused unit cases passed.
See the [stock projection checkpoint](../checkpoints/2026-11-04-catalog-batched-stock-projection.md).
Read completeness and consistency across the full response remain separate
decisions under #36.

## Previous Workforce verification — 3 November 2026

[PR #236](https://github.com/martonpornoi/maru/pull/236) delivered the bounded
recent Shift-outcome component and native authority creation-time correction.
#235 is closed after independent local/hosted acceptance, protected squash,
certified-tree/sole-parent verification and clean-main synchronization.
The [delivery checkpoint](../checkpoints/2026-11-02-workforce-recent-outcomes-protected-delivery.md)
records the exact result and separate browser/human gates.

The maintainer authorized one-agent work on #235, #42, #35, #23 and #22 in order,
closing only verified scopes. [PR #237](https://github.com/martonpornoi/maru/pull/237)
delivered the bounded technical scope for #42. Its
[canonical rehearsal](../operations/workforce-only-rehearsal.md)
names twenty steps and four role sessions through invitations, activation,
Structure, Positions, applications, independent Assignment decisions,
person-owned Availability, Shift completion, retained ending and absence checks.
README and the adoption runbook link it; the older foundation tutorial is historical.
The dedicated source launcher initializes only its synthetic bootstrap account,
uses the restricted web runtime and separate invitation worker, and owns cleanup.

Current-source feedback passed all 14,972 unit cases, including the 64 focused
route/actor/launcher/inspection units, plus the exact Windows POSIX skip and
eleven existing warnings. All five native inspector cases passed. The first
native attempt's guarded refusal is preserved: its positive fixture restored a
2020 clock after creating current native authority. That new fixture now uses
current foundations and one finite real planned-end wait, retaining every
lifecycle, independence, privacy and absence assertion. Production source and
guards remain equal to the protected result.

The restricted source-development startup smoke passed its empty baseline over
all 223 unadopted models, readiness and exact owned cleanup. All 3,332 source
hashes agreed during feedback; ten original stopped fixtures remained unchanged.
The 71 public and ten private new originals are separately sealed in place.
No ordinary account or browser journey was prefilled or claimed. See the
[current-source feedback checkpoint](../checkpoints/2026-11-02-workforce-rehearsal-native-startup-feedback.md)
and the historical [preparation checkpoint](../checkpoints/2026-11-01-workforce-rehearsal-preparation.md).
The first clean final candidate's all-history Auto failed after committed
authority-issuance history left three dropped/re-added edition-column slots in
the shared test database. An unchanged 26-case native reproduction verified
that the exact Guidance schema guard correctly refuses that residue. Failed
originals and independent catalog proofs are sealed. The historical case now
uses the existing isolated migration database and checks the caller's exact
Guidance fingerprints and readiness before and after. Fresh repaired feedback
passed all 26 original cases and 78 phases; all 3,334 source hashes and exact
owned cleanup independently reconcile. Production source remains equal to
protected main. See the [isolation checkpoint](../checkpoints/2026-11-02-workforce-rehearsal-migration-isolation.md).
Exact-head local and hosted all-history verification passed. Hosted Linux
passed all 14,973 unit tests, 5,394 native cases across 111 shards and 128
frontend tests. Independent reconstruction from 112 original hosted coverage
parts measured 91.348679% and matched every original XML condition.
The protected squash `8c6ccd52fa46b1cc2b4f225512b5b0dadcd095a5` has the
certified tree and sole parent. The designated clean main was fetched and
fast-forwarded and agrees with GitHub. See the
[protected delivery checkpoint](../checkpoints/2026-11-03-workforce-rehearsal-protected-delivery.md).

#42 requires the complete four-role browser journey and its final absence proof
before closure. The current-URL safety control stopped browser input in this
logical task; no retry or alternate mechanism bypasses it. The original incomplete
human trial, private invitation material, manual accounts/passwords/records,
113-checkbox guide and all ten stopped fixtures remain untouched.
#35 remains open. Its bounded Workforce Home guidance and recent Shift outcomes
have automated evidence for authorization, lifecycle, provider failure and
destination reauthorization. The full role and lifecycle matrix, real browser
zoom and representative assistive-technology acceptance still need evidence.
[PR #238](https://github.com/martonpornoi/maru/pull/238) aligned the
management-shell and recent-outcomes contracts with the delivered panel.
Its protected squash was 32517c2e16f3f679942ebd296e5b7e285dc66b8f. Independent
local current-history acceptance and the selected hosted documentation lane
passed. The designated clean main fast-forwarded to the certified tree.

#23 remains open. A review of nine passing protected-tree cases found automated
evidence for drawer markup and Shift authorization, recovery and disclosure.
The full authenticated role and state matrix, required widths, real 200% zoom,
keyboard and drawer behavior, reduced motion and representative screen-reader
checks still need live evidence.

#22 remains open. An isolated fictional database restarted on the same owned
volume. PostgreSQL logical restore preserved 323 table fingerprints and passed
restricted-runtime, Guidance and authority readiness. The broader catalog
comparison found five compacted dropped-column slots across three tables, so
the drill exited nonzero. See the
[recovery checkpoint](../checkpoints/2026-11-03-workforce-continuity-recovery.md).
The offline validator, revision comparison and authorized rota remain bounded
deliveries. The next technical work is a trusted live import mapping and
confirmation contract, minimized reconciliation, scoped continuity/history/exit
and governed stop/restart/expansion/decommission. Representative restore/PITR
and operator acceptance require separate evidence.

## Last protected delivery — Recent Shift outcomes and authority clock

[PR #236](https://github.com/martonpornoi/maru/pull/236) merged at 13:31:05 UTC on
2 November as `92f59d227e2bdd247c404f7131cd0e58651504a9`, tree-identical to
certified `35f8dc7de8241699532570bfeb166a886543dcf0`; its sole parent is
`f101e42d6e1139f3f9f708a96dde1986d40830c3`. Exact-head PR gate app 15368,
all three current CodeQL app 57789 analyses/uploads, current protections and
resolved conversations passed before the no-bypass squash. Designated clean
main was normally fetched and fast-forwarded; local/origin/remote/API equality
was verified before #235 closed.

Local and hosted acceptance independently reconcile all 391 groups, 111 native
shards, 5,389 native passes and 16,167 phase records, plus 128 frontend passes
and every actual quality gate. Local units passed 14,908 with one exact Windows
POSIX skip; hosted Linux passed all 14,909. Eleven existing warnings remain.
Original local combined SQLite reconstructs 91.348679-percent branch coverage;
all 112 original hosted individual parts reconstruct 91.353558 percent and every
original XML condition, above the unchanged 90-percent threshold. Local individual
parts were consumed by ordinary combine and are not claimed retained.

Actual native/container interval peaks and enforced concurrency were eight;
all exact owned resources were cleaned up. Conservative projections including
cleanup, rounding margin, 50-percent slowdown and ten-minute reserve were
4,544.1345 local / 5,109 hosted seconds, below 5,400. Full hosted originals include
every paginated API/job/attempt, the complete log ZIP and all 114 artifacts by
actual ID/digest. New originals and independent derivations are sealed in place;
failed/interrupted evidence retains its disposition. Ordinary Node audit still
reports one moderate development advisory without an identifier.

UX-033/ADR 0132 retain the five-second optional-component budget and minimized
mandatory audit; ADR 0133 retains native creation time and all existing authority,
source, horizon, deadline, privacy and runtime safeguards. The three-field ORM
state migration changes no physical column or privilege. Current-head browser
acceptance is not claimed: prior observations name predecessor `16c9dd7d`.
Real 200-percent zoom, live long-label/empty/unavailable layouts, specialist
screen-reader, representative owner/two-human, recovery, operational and
production gates remain separate.

## Earlier protected delivery — Recent outcome contract

[PR #234](https://github.com/martonpornoi/maru/pull/234) delivered #233 as
`f101e42d6e1139f3f9f708a96dde1986d40830c3`, tree-identical to certified
`004ee2aeef18a50580bd833c518f1cc09f6a6921`, sole parent
`e45c4b4e6d8d8c53dface9dcc15a35f490be5c88`. It changed documentation only.
Fresh ordinary local Auto passed all ten gates: 14,853 unit passes plus one
expected Windows skip/eleven existing warnings, 5,209 native cases/23 current
shards/279 groups/15,627 phases, 128 frontend cases and 91.228070 percent combined
branch coverage. Complete source hashes, fresh collection/plan, identities,
phase outcomes/durations, peak/bound eight, headroom and exact cleanup agreed.
All 12,566 new local originals are sealed; ordinary combine consumed local parts.

Selected hosted run `41319256115` passed its documentation lane, 30 fixed licensing
cases and PR gate app 15368; three unused alternatives were skipped. It did not
repeat full units/native/frontend/coverage. Its documentation artifact digest,
complete APIs/jobs/logs and CodeQL run `41319254210` with all three exact-head clean
analyses/SARIF provenance were independently verified. All 4,410 hosted originals
and 259 further delivery metadata files are sealed. Live reviews/requests/threads
were empty under unchanged zero-approval policy. Protected exact-head squash,
certified tree/sole parent, final PR body and designated clean-main normal
fetch/ff-only local/origin/remote/API equality were verified. Only #233 closed;
#35, #23, #22 and #42 remain open. Contract delivery did not implement this panel.

## Last protected delivery — Accessibility rehearsal

[PR #232](https://github.com/martonpornoi/maru/pull/232) delivered the contributor
guide as `e45c4b4e6d8d8c53dface9dcc15a35f490be5c88`, tree-identical to certified
`9f14734aa35a3e629b785d7264fec6dad6a760d6`, sole parent
`382175fbffd683c76f852e6844f1f695f0868b38`. The guide maps fifteen role/state
cards, seven widths, real zoom, keyboard, semantics, disclosure and recovery.
Its signed-out and rendered-document observations retain exact named-source
limits; prior PR #226 restricted-runtime evidence remains separately valid.

Fresh ordinary Auto independently passed all ten gates: 14,853 units plus one
expected Windows POSIX skip/eleven existing warnings, 5,209 native cases across
23 current shards/279 groups/15,627 phases, 128 frontend cases and 91.228070
percent reconstructed combined coverage. All 3,308 source hashes, fresh metadata,
complete plan, identities/order/outcomes/durations, peak/bound eight, unchanged
headroom and exact cleanup agreed. All 12,536 new local originals are sealed;
normal combine consumed local individual coverage inputs.

Selected hosted run `41310515890` passed its documentation lane: static checks,
30 fixed licensing/metadata cases, warning-fatal Sphinx and PR gate app 15368.
Its three unused alternatives were skipped; it did not repeat full units,
native, frontend or combined coverage. Complete APIs/jobs/log ZIPs and the exact
published documentation artifact/digest were preserved; 4,404 hosted originals
and 262 further delivery metadata files are sealed. CodeQL run `41310513544`
passed all three current clean analyses with exact upload/SARIF provenance.
Actual reviews/requests/conversations were empty under unchanged zero-approval
policy. Protected squash/tree/sole parent, final body and clean designated-main
normal-fetch/ff-only local/origin/remote/API equality were verified.

#23 remains open. Authenticated W02–W15 and real zoom were blocked by supported
browser-input/native-control limits, with no valid-credential product failure
inferred. Human/specialist/owner, recovery, operational and production gates
remain separate. Original manual accounts/records/113-checkbox guide and ten
stopped fixtures remain unchanged. No runtime, profile, authority or deployment
change was made. See the [guide](../operations/workforce-accessibility-rehearsal.md)
and [checkpoint](../checkpoints/2026-11-01-workforce-accessibility-rehearsal.md).

## Last protected delivery — Offline proposal revision comparison

[PR #231](https://github.com/martonpornoi/maru/pull/231) delivered HR-019/ADR 0131
as `382175fbffd683c76f852e6844f1f695f0868b38`, tree-identical to certified
`8c1a540426ff1e0eb808dcf5cecce15e92fc2653`, sole parent
`82a351478773ab60ce6f195db4e9996e8832ba9f`. The offline comparison checks two
HR-017-valid proposals with equal declared file-local scope. Its complete bounded
report omits supplied values and applies no live records, identities or approvals.
See the [operator guide](../operations/workforce-import-comparison.md).

Independent ordinary Auto passed all ten gates, 14,853 units plus one expected
Windows POSIX skip, 5,209 native cases/23 current shards/279 groups/15,627 phases,
128 frontend cases and 91.232962 percent combined coverage. All source hashes,
fresh collection, complete plan, selections, identities, outcomes, durations,
peak eight, headroom and exact cleanup agreed. All 12,550 local originals remain
sealed in place; local individual coverage inputs were consumed by normal combine.

Hosted acceptance passed 14,854 Linux units including the real POSIX pipe case,
all selected native/frontend/static/security/documentation gates and app 15368.
All 26 artifact digests and 24 original coverage inputs independently reconciled
with the same 91.232962 percent coverage; all three current CodeQL analyses and
app 57789 were clean. No reviews, reviewer requests or conversations remained
under the unchanged zero-approval policy. All 5,648 hosted originals and 431
further delivery metadata files are sealed. Helper-only API/policy/interpreter
bookkeeping errors remain recorded; no test or collection was rerun to repair them.

Protected exact-head squash, certified tree/sole parent, complete final PR body
and clean designated-main normal-fetch/ff-only local/origin/remote/API equality
were verified. #229 is closed; #22 retains live mapping/application, governed
reconciliation, full history/exit and recovery. #23, #35 and #42 remain open.
Original manual data and ten stopped fixtures remain untouched. No deployment,
protection change, live import or human/operational/production acceptance.

## Work records contract — 31 October 2026

The maintainer authorized proceeding through successive bounded tasks and PRs,
including automated preparation for issues with later human validation. HR-018,
ADR 0130 and the Work records page contract now separate existing planned Shift
completion, observations, reported actual intervals, independent verification,
correction/dispute, recipient-owned handover and Scheduling-owned publication.
The first implementation slice is a person's actual-time report for retained
ended confirmed work and a different authorized reviewer's exact-version decision.

The contract defines trusted scope/person/source, explicit intervals and breaks,
policy/horizon/retention prerequisites, closed input/query bounds, replay,
concurrency, minimized evidence, disclosure, manual fallback, restore and exit.
Current profiles, permissions, code, models, migrations, API schemas, routes and
ongoing fictional demos are unchanged. An accepted contract creates no authority,
collection or runtime readiness. Future implementation must add its synthetic
subject/reviewer demo and complete the separately identified human/owner,
accessibility, operational and production gates.

[PR #230](https://github.com/martonpornoi/maru/pull/230) protected-delivered this
contract as `82a351478773ab60ce6f195db4e9996e8832ba9f`. Its tree equals certified
`cc0de5719916ef7bef68a9043cee92faa9a95285`; its sole parent is
`a42205cb7d18fc59575982824a43bf66f9ff8139`. Ordinary Auto independently passed all
ten gates, 14,811 units plus one expected Windows skip, 5,209 current native cases
across 23 shards, 128 frontend cases and 91.220268% combined coverage. Exact
selection/JUnit/native phases, source/plan hashes, timing/peak eight and cleanup
agree. All 6,662 local originals remain sealed and the certified source pinned.

The selected hosted documentation lane independently passed static checks,
30 licensing/metadata cases, warning-fatal Sphinx and PR gate app 15368; unused
unit/native/full alternatives were skipped. It did not repeat full units,
native, frontend or combined coverage. Both run log ZIPs, complete APIs and the
published documentation artifact/digest are sealed. All three current CodeQL
analyses/SARIF uploads and app 57789 aggregate were clean, with no open alerts,
reviews, requests or conversations under unchanged zero-approval policy.
Protected exact-head squash, certified tree/sole parent and clean designated-main
normal fetch/ff-only local/origin/remote/API equality were verified. Final PR body
exactly records delivery; 259 further metadata originals are sealed without
rehashing earlier evidence. Helper-only environment/output-stream assumptions
remain retained and no test/collection was retried during independent readback.

#24 is closed for its contract scope. Runtime implementation and actual
organization policy, #22 continuity, #23 accessibility, #42 human rehearsal and
#35 broader home work remain open. No deployment, protection change, profile
expansion, human or production acceptance was inferred. See the
[contract checkpoint](../checkpoints/2026-10-31-workforce-work-records-contract.md)
and [future acceptance matrix](../product/page-contracts/workforce-work-records.md#observable-acceptance-and-human-handoff).

## Prior protected delivery — Offline Workforce proposal checker

[PR #228](https://github.com/martonpornoi/maru/pull/228) delivered HR-017/ADR 0129
as `a42205cb7d18fc59575982824a43bf66f9ff8139`, tree-identical to certified
`5bc391efbf84d07dad9ae65a791865e6d8d06f75`, sole parent
`b70f63f8035b287aeff2e8fab995940441745339`. Independent local and hosted
acceptance reconciled all ten local gates, 5,209 current native cases/23 shards,
128 frontend tests and 91.220268% coverage. Hosted units passed all 14,812 cases,
including the real POSIX pipe test skipped on Windows. All 26 published artifact
digests, 24 original coverage parts, selection/JUnit/native phases, timing, a peak
and bound of eight and exact cleanup agreed. Three current CodeQL analyses were clean;
no reviews, requests or conversations remained under the unchanged zero-approval
policy. Protected squash and clean main normal fetch/ff-only synchronization
were verified with local/origin/remote/API equality. #227 is closed; #22 stays open.

The versioned offline checker, schema and fictional examples change no live
record or authority. Existing development-only moderate minimatch advisory
GHSA-g3hv-75wg-m249 remains documented; the required high-threshold audit passes,
without a zero-vulnerability claim. Local verifier/saver bookkeeping failures and
all originals remain retained; no failing helper was treated as a failed test,
and no successful API/download/test/collection/check was repeated to repair them.
Certified source stays pinned. See the [operator guide](../operations/workforce-import-validation.md).
Manual accounts/passwords/records, the 113-checkbox guide, ten stopped fixtures,
unrelated worktrees/stashes and paused automations remain preserved. No new
heartbeat was created; the old operating-home and PR222 heartbeats stay deleted.

## Prior protected delivery — Workforce operating home

PR #226 is protected-delivered as `b70f63f8035b287aeff2e8fab995940441745339`.
Its tree equals certified `089c28d76a09f179b0e376664b8017eded78cb22`; the sole
parent is `ac5f099e50624fbe7f0824a97b9b4309c45df7bc`. Complete local and hosted
acceptance independently passed 14,643 units, 5,365 native cases across 111
shards, 128 frontend cases and coverage above 90 percent. All three current
CodeQL analyses were clean, both supported findings were repaired, and all
conversations resolved. Clean designated main advanced fast-forward only with
local/origin/remote/API equality. #225 is closed; #35 remains open. Verified
delivery is [recorded in PR #226](https://github.com/martonpornoi/maru/pull/226#issuecomment-6536111582).
The temporary heartbeat was deleted. Retained exact-head source and sealed
original evidence stay pinned. Genuine 200% zoom, specialist screen reader,
representative-owner, recovery, operational and production gates remain open,
as do #23 and recipient-owned #42 acceptance. #24's later contract delivery is
recorded above; it does not implement attendance or actual time.

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

1. Finish documentation feedback, commit the #24 contract and certify its exact
   clean head with ordinary Auto; preserve all earlier evidence.
2. Publish one ready PR, verify its selected hosted checks and current CodeQL,
   then exact-head protected squash and clean designated-main ff-only equality.
3. While hosted checks run, prepare the next bounded issue on a separate branch;
   recheck the queue before publishing and update/re-certify after main advances.
4. Keep implementation and genuine human acceptance separate. Preserve the
   manual rehearsal, certified sources, sealed outputs and unrelated work.
