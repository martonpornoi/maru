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
