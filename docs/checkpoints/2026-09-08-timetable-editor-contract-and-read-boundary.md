# Timetable editor contract and initial read boundary

- Date: 2026-09-08
- Child: [#85](https://github.com/martonpornoi/maru/issues/85), native parent #48
- Branch: `codex/programme-timetable-editor`
- Base: protected `ec0d2474810e27b72c9dbabcc1d210222e4989af`
- State: partial implementation; no pull request, certification or delivery yet

ADR 0092 and the Programme timetable planning page contract define the next
mandatory editor child. Pointer actions enhance the same explicit forms;
private drafts, conflict preview, physical reservations and publication remain
distinct. Existing profile manifests, routes and runtime ACLs are unchanged.
The #82 delivery checkpoint reconciles the former stale pending handoff.

The first implementation adds complete bounded Scheduling-owned current
planning, independent fifty-row history pages and exact historical manifests.
Reads use the edition mutex, final field authorization and audit-before-release.
They omit private Programme layers, host identity/presence/availability, room
labels and foreign booking facts. Immutable manifest count/digest checks and
parent/current-revision completeness prevent a partial passing inventory.
Pure helpers resolve exact edition-local or offset-bearing minutes and compare
already-authorized placement revisions by stable occurrence identity.

Focused verification passed 31 database-free cases and 26 real PostgreSQL
cases. Initial schema creation plus 21 cases took 160 seconds; the expanded
rerun reused only that isolated database's schema and took 56.18 seconds. Test
cases retain real committed commands and per-test cleanup. An added fixture's
attempt to create a closed edition correctly failed the draft-first database
guard; the fixture now reaches those states through ordinary Events commands.
No guard, assertion or acceptance scope was weakened. Focused lint/format,
strict mypy and NumPy docstring checks passed for the new code.

This is not a usable editor or completed issue. Owner-content composition,
non-mutating current conflict preview, forms/server adapters, responsive board,
browser interaction/accessibility rehearsal, complete exact-head certification
and protected delivery remain. No schedule is created or re-enabled. Keep #85
and #48 open and retain all integrated Programme acceptance gates.

## Same-session verification completion

All 3,542 database-free tests passed in 18.74s, with the two already-known
Django URLField deprecation warnings. All 40 candidate/read PostgreSQL cases
passed in 71.94s. The 26 new cases are colocated with the existing candidate
contracts; a direct body comparison confirmed every original test remained
unchanged. This resolves the legacy diagnostic inventory bookkeeping failure
without changing a timing map, classifier, historical scope or any assertion.
Maintained documentation validation passed for 424 Markdown files, four
repository skills and 215 stable requirement identifiers; the new page is
included in both the human catalog and Sphinx toctree.

## Owner inventories and shared non-mutating preview

The next local slice adds a complete Programme working-title inventory (2,000
items maximum), a separately authorized Venue-label inventory (256 selections
maximum), and current/unsaved candidate conflict preview. Programme SQL excludes
working summaries and other layers; Venue SQL excludes contacts, notes, booking
content and availability. Both inventories use existing capability fields,
final authorization and mandatory minimized audits. Missing data and sentinel
overflow do not become partial unscheduled/room lists.

Preview shares the saved candidate evaluator and placement revision resolver.
It retains all other candidate occurrences, detects room/host overlap, checks
current versions, distinguishes blockers from unavailable sources and explicitly
lists deferred staffing/rest/accessibility/release checks. Unsaved placements
do not inherit physical reservation identity. The edition mutex precedes
Programme's complete canonical person set and the final actor-only recheck.
Final denial/audit failure withholds the projection and rolls back success
audits. Only read audits are written; all Scheduling relations and versions,
Venue bookings, domain events and outbox counts remain unchanged by preview.

A real Venue workspace-policy test exposed mismatched field names in the new
inventory. The inventory and preview now request the existing catalog fields,
without changing the catalog or admitting any profile. Four fast consistency
cases ensure editor read ceilings remain subsets of their owning capabilities.

Verification for this follow-up slice:

- All 3,546 database-free cases passed in 18.86s, with the two existing Django
  URLField deprecation warnings.
- All 50 candidate/history/placement PostgreSQL cases passed in 95.96s.
- All 33 evaluation/preview and 19 Programme-query cases passed together in
  105.52s, including the unchanged persisted evaluator contract.
- All 28 Venue physical-source/inventory cases passed in 46.00s. The new label
  success/isolation cases use real workspace policy, not future-source admission.
- The 130 focused PostgreSQL cases reused only the task-owned isolated schema;
  their combined 247.48s excludes initial migration setup. This is focused
  iteration evidence, not a whole-suite speedup or certification claim.
- Focused Ruff, strict mypy, NumPy docstrings, maintained documentation
  validation and whitespace checks passed. No CI, historical inventory, timing
  map, coverage threshold or existing assertion was changed.

The inspector's independently protected layers and selected host-presence
composition, forms/server adapters, responsive board and browser acceptance
remain to implement. Keep #85 open with no completed-editor/PR/runtime claim.
The exact-head complete local and hosted protected gates remain mandatory before
delivery. Existing literal profiles, production routing and runtime ACLs are
unchanged; no scheduled check-in was created or resumed.

## Selected-layer inspector and native command adapters

The follow-up after local checkpoint `925480c` adds one explicitly selected
Programme inspector layer at a time: working copy, approved copy, delivery,
readiness, roster or deliberately shared availability. Scheduling permission
does not admit any Programme layer, and denied/unavailable layers never fall
back to another source. Applications proposal/review text is not selectable.

The host requirement reader validates the exact candidate version, manifest,
occurrence binding and bounded complete presence rows before composing the
independently authorized roster. Current related-person labels come from
Identity only after Programme's canonical person locks. Inactive identities
receive neutral labels; missing expected current labels fail closed. Retained
required times are neither personal availability nor host consent. Both owner
audits and final Scheduling authority precede release.

Events' minimized Scheduling reference now supplies its trusted IANA zone to
the planning snapshot. Native service-day and placement forms use it for exact
minute input; browser/machine zones do not silently select instants. Native
submit adapters delegate to the existing service-day/placement commands or
non-mutating preview. Strict fields reject unknown/duplicate inputs, aliases,
invalid intervals and incomplete required host times. Save requires a human
reason and preserves the exact retry key/version. Preview never constructs a
command request. Stale failure preserves the bound input without automatic
rebase or partial state. The future renderer must submit the action only once
and make Preview the default placement submit action.

Verification:

- All 44 new database-free form/adapter cases passed in 0.37s; the complete
  3,590-case database-free suite passed in 23.97s with the two existing Django
  URLField deprecation warnings.
- The 28 selected roster/inspector/presence cases passed in 58.36s.
- Three real native-command cases passed in 8.82s: preview/save/exact replay,
  stale-input preservation/rollback, and service-day create/revise.
- The expanded affected current-behavior run passed all 132 PostgreSQL cases in
  263.65s. Only three unchanged historical host-schema/capability migration
  cases were deselected for this iteration. This does not alter their inventory
  or policy-required certification coverage. All tests reused the exact
  task-owned isolated current schema, not production or shared data.
- Focused Ruff, strict mypy, NumPy contracts, documentation validation and
  whitespace checks passed. No CI classifier, timing map, coverage floor,
  migration, runtime grant, route or profile was changed.

This remains partial #85 implementation. Candidate/occurrence/history and
physical-reservation controls, board/template rendering, browser interaction
and accessibility rehearsal, and complete protected delivery remain. No PR or
activated Programme workspace is claimed. Keep #85 and #48 open and continue
the accepted editor contract before moving to the next umbrella child.

## Complete native record command adapters

The follow-up after local checkpoint `456d9c4` adds the remaining closed native
record controls. These delegate candidate create/copy/restore/archive,
occurrence creation/repetition/group revision/retirement, day retirement,
unplacement, saved conflict evaluation, exact warning acknowledgement and
physical reservation replacement/cancellation to the existing owner commands.
There is no second writer, new schema, profile expansion or mounted route.

Each form accepts only its server-selected operation's fields. Item/group
choices must already be independently authorized, group/sequence meaning stays
explicit, and all operations require a human reason and exact retry key.
Consequential actions require confirmation, and room-hold reasons are labelled
Venue-visible. Form validation does not grant mutation/history/Venue authority
or let a hard blocker be acknowledged. Domain failures preserve entered values
and do not retry against newer optimistic versions.

The real history round trip exposed a test assumption that only creation
advances edition control. All successful Scheduling mutations advance it. The
test now observes a fresh snapshot for the new copy intent, and copy input
requires the positive control version already required by the command. A
separate test confirms stale pending creation is not silently rebased. An
additional scope fixture correction uses Events' actual `series` relation.
Neither correction changes a domain or acceptance contract.

Verification for this slice:

- The complete database-free suite passed 3,671 tests in 22.65s, including 81
  new record-control cases and the two existing Django URLField warnings.
- The 17 selected native-command PostgreSQL cases passed in 38.54s using the
  same label-verified task-owned current schema. They exercise retained history,
  exact replay, explicit repeated occurrences, day retirement, base-read versus
  mutation/history authority, cross-edition/organization denial, stale sources,
  forbidden blocker acknowledgement, physical replacement rollback and historic
  cancellation after unplacement. Draft movement/unplacement leaves the current
  room hold active until an explicit physical command succeeds.
- Focused lint, formatting, strict mypy, NumPy contracts, whitespace and
  maintained-documentation validation passed (424 files, four skills, 215
  requirement identifiers). No complete certification is claimed here.
- Existing test bodies, CI/classification/timing files, historical acceptance,
  coverage floor, migrations, runtime ACLs and production routing are unchanged.

The complete browser surface is still pending, including protected persisted-
evaluation/current-booking readouts, board/forms, browser/accessibility
rehearsal and exact-head local/hosted protected acceptance. Keep #85 and #48 open
with no partial-editor PR or runtime claim. Continue those editor tasks before
the next umbrella child; no scheduled check-in has been created or resumed.

## Fresh review, current holds and initial board rendering

The follow-up after local checkpoint `611671b` adds independently audited
conflict-review and physical-hold readouts plus the initial complete inventory,
day/room board and native form rendering composition.

Conflict review compares the latest saved report for the exact current draft
revision with fresh owner dependencies. Historical completeness is separate
from current availability, and a missing, stale or unavailable report never
supplies eligible warning evidence. Hard blockers cannot be acknowledged.
The projection returns no calendars, source JSON, dependency digests, warning
fingerprints or acknowledgement actors/reasons. Missing/overflowed/inconsistent
findings withhold the whole result. The saved evaluator and preview keep the
same underlying algorithm; only their minimized projection is shared.

Physical review orders Scheduling's reciprocal intents by the unique immutable
command **control version**, not a wall-clock timestamp. Existing exact-resource
Venue policy then proves the selected binding's live version/review state.
Movement/unplacement retains an earlier hold until an explicit physical command
succeeds; generic Venue cancellation and independent approval are reflected.
No new Venue reader, capability or broad grant is needed. The active envelope
is the current authorized reciprocal binding's consequence, not arbitrary
history/rationale access. Both readers retain required minimized audits and
canonical locking; final denial/audit failure rolls back success audits.

The pure board composer receives independently authorized title, room and
Scheduling snapshots. It preserves items with no occurrence, explicit repeats,
unplaced/placed and retired occurrences. Missing/duplicate references fail
closed. Planning placements now include their stable day identifier, so a
revised day does not silently drop retained geometry from the board. Changed
metadata is visibly distinguished from the saved placement envelope.

Initial templates reuse the management shell, one H1/main, labelled ordered
cards, explicit overnight dates and offsets, current physical-hold readout and
native form/error rendering. Labels are escaped. The action is submitted only
once, Preview is first for placement forms, and recoverable errors retain
entered values and the retry key. This is a dormant rendering component, not a
complete HTTP workspace or browser/accessibility acceptance claim.

Verification:

- All 3,690 database-free tests passed in 23.05s, with the two existing Django
  URLField deprecation warnings. Nineteen new composition/rendering tests cover
  complete inventories, duplicates/missing references, stale day continuity,
  ordering, escaped owner labels, landmarks/IDs, explicit times, native action
  cardinality, Preview-first ordering and linked retained form errors.
- The initial 23 readout cases passed in 63.92s. The subsequent complete affected
  candidate/evaluation/reservation run passed all 152 PostgreSQL cases in 370.66s,
  including current-profile and cross-organization/edition denials, current/
  stale/unavailable warning evidence, independent field/final-audit failures,
  current/historical room holds and real owner-backed board composition.
- One additional real independent-Venue-approval readout case passed in 3.99s:
  physical version two and approved state are visible while Programme timing
  stays unpublished. Six unchanged continuity cases were not selected for this
  focused follow-up; policy-required certification retains them.
- All database tests reused the same exact label-verified synthetic task schema.
  These 153 current-behavior cases are focused evidence, not whole-suite or
  runtime-role certification. No migration, CI classifier/timing/coverage policy,
  current profile, production URL or runtime grant changed.
- Focused Ruff/formatting (12 Python files), strict mypy and NumPy contracts
  (six source files), whitespace and maintained-documentation validation passed
  (424 files, four skills, 215 requirement identifiers). A syntax-tree comparison
  confirmed all 102 original test functions in the five modified existing test
  files were retained unchanged; an insertion-placement mistake was corrected
  before the complete run.

Remaining editor work is trusted HTTP selection/command orchestration, native
filters and full inspector/history/conflict presentation, pointer-prefill and
unsaved-input behavior, then complete synthetic browser and protected delivery
acceptance. No production route is mounted and no partial-editor PR is open.
#85 and #48 remain open; no schedule has been created or resumed.

## Strict selection and native control composition follow-up

The editor now has a strict transient POST selection namespace and one native
control composer. Selection is not command attribution: actor, tenant, versions
and retry keys remain outside `ui_` state. Unknown and repeated values survive
splitting and are rejected by the appropriate strict form. Scoped selection
resolves before filtering; item selection never guesses its first repeated
occurrence. Text/state/day/room filters change visible cards and lanes only,
retaining complete choices and independently resolved selection.

Each native command control uses the existing form and owner command. Fresh
intents receive the observed shared control or exact target version, explicit
targets and a new retry key. Bound forms receive no fresh initial values and
preserve stale/invalid input and retries. Placement prefill uses all four exact
instants and required host windows, never availability inference. Missing
context and read-only lifecycle withhold new controls; archived alternatives
remain copyable. Current room-hold cancellation keeps its original source even
after unplacement, while replacement refers to the current selected placement.
Missing selected history cannot silently fall back to current timing.

Connecting the first-group workflow exposed a missing native action: previous
choices only permitted existing groups. A planner can now deliberately start a
new group with an explicit sequence and a retained opaque pending key. This
edition-local grouping key is not a foreign-record reference or authority; the
same owner command checks group uniqueness. The action creates exactly one
occurrence; a second occurrence remains a separate versioned command.

Verification for this increment:

- The complete database-free suite passes 3,789 cases in 26.63s, with only the
  two existing Django URLField deprecation warnings.
- The final 180 focused selection/control/record cases pass in 1.71s under
  branch-aware coverage. The three selected source modules total 97.79%; the
  control composer is 96.97%, selection 97.89%, and record forms 100%. This is
  component coverage, not complete certification or whole-application coverage.
- Eight native-command PostgreSQL cases pass in 14.15s. Real owner projections
  compose the new form; initial group creation, exact replay and explicit
  second occurrence retain two command receipts and two ordinary occurrences,
  leaving candidate timing and physical bookings unchanged. Sixty-two other
  candidate-file cases were deselected for this focused incremental run.
- Existing record-dispatch assertions remain, with two additional checks that
  native-only new-group controls never become owner-command keyword arguments.
  No CI classifier, timing inventory, coverage threshold, historical scope,
  migration, runtime write grant or current profile was changed.
- Focused Ruff/formatting, strict mypy, NumPy docstrings, whitespace and
  maintained-documentation checks pass. No production route is mounted, no
  HTTP/browser acceptance is claimed, and no partial-editor PR is opened.

The next work is to connect these typed components to trusted HTTP request and
response handling, native filter/inspector/history/conflict presentation and
pointer/unsaved-state behavior, then perform browser and protected acceptance.
This is still one incomplete #85 editor, not a separately delivered child.

## Trusted HTTP and native information workspace follow-up

The unmounted server adapter now connects exact native selection and forms to
the existing owner reads/commands. Actor identity comes from the authenticated
request, tenant/edition from trusted arguments, and ordinary CSRF checks remain
enabled. Responses are no-store, private POST values are masked, URL filters
are rejected, and base permission/audit precede private selection binding.
Current policy and lifecycle compute task choices without adding a page ACL.
Current-source copy retains the writer's independent history-read requirement.

The management shell now renders filters, selected item/layer context, paged
immutable history and exact comparison, and current/saved conflict findings
with closed human causes and safe next actions. Native query forms do not nest
or duplicate successful single-value fields. Current item labels beside old
geometry are explicitly current; availability does not silently load names or
render periods for an unshared relationship. Only the explicitly requested
layer is queried. Each owner keeps its own canonical transaction/lock set.

Successful commands reload real records and select the affected resource.
Preview and recoverable errors preserve the exact pending form/key/version;
permission failures withhold all prior private context. A lost success refresh
can follow a committed command, so the error heading says attention is needed,
not that the action failed. Exact replay confirms that receipt without a
duplicate. No raw source exception is returned, and no private draft action
implicitly publishes timing or alters physical holds.

Verification for this increment:

- The complete database-free suite passes 3,882 cases in 21.70s, with the two
  existing Django URLField deprecation warnings.
- Ninety-three HTTP/rendering unit cases pass in 3.82s under branch-aware
  coverage. The three new source modules total 95.33%; workspace composition
  and conflict explanations are 100%, HTTP dispatch is 92.75%. This is focused
  component coverage, not whole-application certification.
- Fourteen real PostgreSQL HTTP cases pass in 42.58s, reusing the same exact
  label-verified synthetic task database. Creation of days, candidates and first
  groups, positive CSRF, preview/save and exact replay, immutable comparison,
  historical copy/restore, stale input, current-profile and independent-layer
  denial, foreign tenant/edition candidates and post-commit refresh loss all
  exercise actual owner reads/commands. Seventy other cases in the existing
  candidate test file were deselected for this focused increment.
- Focused Ruff/formatting, strict mypy, NumPy contracts, whitespace and maintained
  documentation checks pass. Existing test assertions, migrations, runtime
  permissions, profile manifests, CI/history classification, timing inventory
  and coverage thresholds remain unchanged.

Pointer-assisted prefill, unsaved-input protection, synthetic browser rehearsal
and the full protected acceptance/delivery gates still remain. Neither #85 nor
#48 is closed; no partial-editor PR, runtime route or scheduled check is added.
