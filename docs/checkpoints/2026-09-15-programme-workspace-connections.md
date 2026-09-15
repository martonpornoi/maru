# Programme workspace connections: local implementation

Date: 2026-09-15
Parent: #108 under #48; partial delivery, both remain incomplete.

## Bounded outcome

From protected PR #131 / `6c1d437e7e9935f5716397aede13b59a2609f4c2`,
`codex/programme-workspace-connections` connects private Programme items, the
canonical dormant timetable and release workspace. This increment was recorded
under #108's existing owner-connections item before implementation. Workforce,
notices, continuity, person/reference/files, accountable setup and final gated
promotion remain independent unfinished continuations within that issue.

SCH-003/004/007–012, PRG-008 and UX-029 map to the existing owner commands,
queries, page contracts and ADRs 0088/0092/0094–0096. No accepted ADR is reversed.
The [timetable contract](../product/page-contracts/programme-timetable-planning.md#canonical-connections-under-108)
owns the connection behavior. The public Scheduling navigation seam is used by
both Programme and Scheduling without another module's private model imports.

## Trust and recovery

The canonical wrapper verifies UUID principal, exact Events-owned parent
identity and independently admitted Scheduling, Programme and Venue field
ceilings before dispatching the original editor exactly once. It renders the
actual shared Administration shell, then performs only protected read-only
recomposition and final scope/admission checks. Changed labels, history,
selected layers, review, staffing facts and owner form choices are withheld.
No outer transaction changes canonical cross-owner locking.

Optional links contain fixed task names and exact reversed/resolved paths, not
destination inventory, history, directory or private query-string content.
Missing routes, catch-all shadowing, foreign parents, denial and unavailable
dependencies omit the target. A changed optional link is removed after rendering
without invalidating an otherwise authorized workspace or command receipt.
Navigation never grants a destination's authority.

Native bound input, versions and retry keys are retained. Final reads cannot
dispatch a second command. Preview facts remain transient, and the existing
planner's source-read-dependent recovery is not misrepresented as the release
workspace's source-free receipt path. A post-command disclosure failure does not
claim the command failed. Existing dirty-input guards cover the new task links.

There are no migrations, runtime/profile additions, production route mounts,
owner writers, new retention stores, notification transports, excluded-module
side effects or CI policy changes. Recovery is ordinary code fix-forward; no
data migration/rollback is involved. Optional metadata-only link checks do not
replace required owner read audits.

## Local verification recorded before certification

- 191 focused Python tests across links and the three workspace adapters passed
  in 2.26s. Tests cover mounted/resolved/denied links, field ceilings, foreign
  parents, actual shell, one dispatch, late disclosure failures, original stale
  input and rich mode/preview recomposition.
- The complete **7,591 database-free unit tests passed in 46.15s**, with three
  existing Django URLField deprecation warnings. The initial full-unit attempt
  was interrupted after setup errors; a first-error rerun stopped with 2,293
  passes and WinError 5 on the user's existing pytest temporary directory.
  A new repository-local temporary root allowed the complete rerun. No shared
  temporary directory was deleted or its permissions changed.
- All **92 frontend tests passed**, seven files, in 9.43s. Existing actual-asset
  tests now explicitly guard both Programme task links, retain retry/version
  on cancellation and continue to allow same-page anchors.
- Focused Ruff, repository formatting, diff whitespace, mypy on six affected
  sources and NumPy docstrings passed. Early command fixtures omitted explicit
  confirmation; preview input assertions incorrectly included the separate UI
  namespace, and the unselected staffing test initially requested a real source.
  These fixtures/assertions were corrected. A propagated owner denial was moved
  to docstring notes to satisfy the direct-raise contract. No production error
  or acceptance threshold was hidden by those corrections.

Fresh clean exact-commit certification and hosted protected acceptance are
pending at this checkpoint. These iteration results do not certify a new head.

## Synthetic browser observations and limits

The temporary loopback fixture used real views, native forms, templates, assets,
canonical routes and navigation with explicitly substituted owner/policy seams;
all database connections were forbidden. No native domain persistence or
activated-profile behavior was claimed. At the actual 1,280 CSS-pixel viewport:

- Followed Programme items → timetable → release → timetable.
- Selected a labelled private draft and observed placed/unplaced/retired entries
  and the populated overnight board with explicit times.
- Opened Create a private draft. Submitting a name without the required reason
  left the name in place and identified the invalid reason control.
- Observed one H1/main, no duplicate IDs on the draft form and no page-level
  horizontal overflow in inspected item/planner states.
- Items-only role retained its inventory but had no other workflow links.
  Direct restricted/anonymous planner requests returned HTTP 403 in server logs.
  The in-app browser kept the previous document for those plain-text failures;
  visible denial-page rendering is therefore not claimed.

Both created tabs and the exact task-owned server were closed. Native discard
dialog interaction, keyboard/focus traversal, actual 200-percent zoom, reduced
motion, screen reader, the full responsive matrix and representative-human
comprehension remain explicit #92 acceptance debt. Existing #87 observations
are not reused as new connection evidence. #109 still owns integrated adoption.

## Deferred native evidence and next action

One existing `test_scheduling_candidates` native scenario now also asserts the
canonical wrapper cannot promote isolated component admission into current-profile
authority, cannot disclose private content, and cannot add a planning read before
denial. It was maintained but **not collected or executed** under ADR 0100.
#102 must additionally exercise admitted real-owner canonical rendering,
post-render field/source revocation, audit failures and exact retry semantics
alongside the retained editor/Workforce cases before final acceptance. No weights,
PostgreSQL timings, coverage or runtime success are inferred from unit tests.

Finish exact-head certification and ordinary protected delivery, record its
actual evidence separately, then continue #108's next owner connection.
#102, #97, #109 and #92 remain mandatory before activation or director pilot use.
