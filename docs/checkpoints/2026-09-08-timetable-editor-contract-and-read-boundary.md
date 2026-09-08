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
