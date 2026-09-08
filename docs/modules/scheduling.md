# Scheduling module

Status: dormant candidate/conflict and reciprocal physical-reservation kernel;
no Programme timetable editor, approval, release or current-profile activation.
Last updated: 2026-09-08. See [CURRENT](../project/CURRENT.md) for verification
and protected-delivery status; this guide is the owner contract, not a merge claim.

## Ownership and adoption

`maru.scheduling` owns service days, stable occurrences, comparable timetable
candidates, explicit required host presence, conflict evidence and deliberate
reservation intent. [ADR 0088](../architecture/decisions/0088-versioned-scheduling-candidates-and-venue-binding.md)
maps this boundary to SCH-001, SCH-003, SCH-004, SCH-007 through SCH-010,
PRG-008, VEN-001, VEN-002, VEN-008, AUD-001/AUD-003 and NFR-013.

Programme owns item content, readiness, hosting confirmation and deliberately
shared availability. Events owns edition lifecycle, dates and IANA zone.
Venues owns actual physical occupancy and independent physical approval.
Workforce remains the future owner of Shift demand and volunteer commitments.
Scheduling must use those owners' documented services, not their private models.
Cross-owner database integrity deliberately verifies the exact foreign graph;
it is not a user-facing data-access path.

Neither `full_convention@1` nor `workforce_only@1` admits the new capabilities,
adapters or conflict sources. All fifteen Scheduling tables and the new Venue
binding table remain runtime SELECT-only. A schema migration, retained UUID,
platform role or successful isolated test does not activate this workflow.
There is no new HTTP route, API, UI, worker or effect-delivery handler. No
Registration, Participation, payment or attendance record is created.

## Owned state and commands

Every command uses `SchedulingCommandRequest`: exact person, organization,
edition, UUID retry key, correlation, normalized reason and bounded channel.
Current versions are explicit optimistic preconditions. One edition control
serializes commands and receipts; an exact retry returns the retained result,
while reusing its key with different intent fails. Authorization and source
eligibility are checked before work and under the final transaction. Current
verified people are required; an ORM writer context is not database authority.

- `day_commands`: create, revise and retire a service day. Its immutable revision
  retains label, UTC window, minute precision and Events version. Days fit the
  current edition, may cross local midnight, and cannot overlap. Adjacent days
  remain distinct. Precision divides an hour and anchors to the day's start.
- `occurrence_commands`: create, revise and retire a stable exact Programme-item
  occurrence, with explicit group key and sequence. Retirement first requires
  cancellation of its active physical hold; it never deletes retained plans.
- `candidate_commands`: create, copy, restore, archive or remove a placement.
  Each revision is a complete immutable manifest with count and digest. Copy
  preserves the exact source revision; restore creates a successor. Archive is
  terminal. Other alternatives and historical manifests never change.
- `placement_commands.set_scheduling_placement`: place, move or resize by adding
  an immutable placement and successor manifest. It identifies exact day and
  occurrence revisions, selected room, requested capacity, four ordered room
  times and explicitly selected host presence intervals. Invalid structure or
  foreign scope fails; a structurally valid draft may still have conflicts.
- `evaluation_commands`: persist a current candidate evaluation or explicitly
  acknowledge one exact current warning. Neither operation approves a timetable.
- `reservation_commands.change_scheduling_reservation`: replace or cancel one
  physical reservation, through the independent Venue owner in the same
  transaction. Draft placement edits never implicitly reserve rooms.

The existing four writable edition states are Draft, Preparing, Ready and Live;
Closing, Archived, Cancelled and unknown states deny planning changes. This is
an Events-owned Scheduling-write consequence, not permission to reopen
Programme private content or invitations on-site.

Bounds are explicit: 32 active/128 retained days, 2,000 occurrences, 100
candidates, 1,000 ordinary metadata revisions plus final retirement, 10,000
candidate revisions plus final archive, 100 required-host selections per
placement, 10,000 findings and one million conflict comparisons. Bounded
overflow is unavailable or a refused command, never a truncated passing report.

## Current dependencies and explainable conflicts

### Planner read boundary

The in-progress [editor child #85](https://github.com/martonpornoi/maru/issues/85)
adds `planning_queries` without mounting a surface or granting runtime writes.
`load_scheduling_planning` returns all bounded current day, occurrence and
candidate summaries, plus the complete explicitly selected candidate manifest.
No selection means inventory only, not an implicit first-candidate choice.
Overflow and missing current revisions are unavailable, never silently omitted
records. The edition mutex, final scope/field authorization and required
read audit protect the multi-query snapshot.

`list_scheduling_candidate_history` requires independent history authority and
returns explicit newest-first pages of fifty changes with an exclusive version
cursor. `load_scheduling_historical_manifest` validates the exact immutable
manifest count and digest before releasing geometry and retained rationale.
Neither query dereferences Programme or Venue private models. Current planning
omits historical actor/reason, host identity/presence and availability, Programme
copy and room names. Owner links are opaque, not dereference authority. Owner
content/layers and current conflicts remain separate protected queries.

`planning_inspector.load_scheduling_item_inspector` loads exactly one selected
working, approved-copy, delivery, readiness, host-roster or shared-availability
layer through its public Programme query. Scheduling planning permission does
not grant any Programme layer, and denial never falls back to another query.
Private Applications answers/review are not selectable inspector layers.

`planning_hosts.load_scheduling_host_requirements` validates the exact current
candidate manifest and occurrence, then composes retained required-presence
times with Programme's independently authorized complete host roster. Unplaced
occurrences have no invented presence requirements. Missing/foreign sources,
manifest mismatch, overflow or stale candidate version fail closed. The roster
and names are current; required times are the selected placement's immutable
intent, not shared availability. Both owner audits and final Scheduling scope
checks precede release, under canonical edition/person locking.

`planning_preview.preview_scheduling_candidate` uses `scheduling.view_conflicts`
and its existing `conflicts` / `dependency_versions` ceiling. It evaluates an
exact current draft, optionally replacing or adding one unsaved placement, with
the same owned revision resolution and evaluator as saved commands. Stale
candidate versions are not rebased; missing/stale structural sources fail
closed. Programme and Venue authorize their complete dependency sets separately.
The edition mutex precedes the complete Programme person set and the final
actor recheck. Read-only labels are composed in separate owner transactions,
not in an actor-first transaction surrounding a multi-person preview.

Preview returns only closed findings, exact candidate version, source
availability and explicit deferred concerns. It exposes neither calendars nor
persisted evaluation identifiers, dependency digests or warning fingerprints.
Only read audits are appended: no placement, history, receipt, evaluation,
acknowledgement, reservation, domain event or outbox message is created. A new
unsaved placement cannot claim an existing physical hold as its own; retained
holds continue to participate in conflict detection until explicitly replaced
or cancelled. Complete means implemented sources were available, not that
blockers, warnings or deferred release concerns are satisfied.

`planning_interactions` provides database-free exact local-minute conversion and
comparison of already-authorized manifests. Offset-free daylight-saving gaps
and folds fail explicitly; an offset identifies an exact instant. Comparisons
use stable occurrences and never describe a changed placement revision as
unchanged merely because its visible geometry happens to match. These helpers
do not authorize, persist, reserve or publish anything. See the
[page contract](../product/page-contracts/programme-timetable-planning.md) and
[ADR 0092](../architecture/decisions/0092-dormant-accessible-timetable-editor.md).

### Native editor submissions

`planning_forms` provides strict service-day and placement controls. The base
planning snapshot supplies the Events-owned IANA zone; browser/machine zones
do not choose the instant. Inputs reject unknown fields, duplicate single
values, noncanonical identifiers/numbers and ambiguous/nonexistent minutes.
The four room-envelope boundaries and each selected host's required interval
remain explicit. Selecting no host never infers a presence from leftover time
values or claims that hosting is not required. Private draft conflicts are
checked by preview/evaluation, not mistaken for form validation success.

`planning_actions` reauthorizes before binding private input, then delegates
to the existing preview, placement or service-day commands. Preview creates
no command request. Saving needs a human reason and retains the exact submitted
retry key and optimistic version; replay and stale failures use the existing
command semantics. Invalid/recoverable input remains in the same bound form.
These adapters do not mount a route or reserve, approve, publish or confirm a
host.

`planning_record_forms.PlanningRecordForm` and
`planning_record_actions.submit_planning_record` provide the remaining explicit
record operations through the same owner commands: candidate creation, exact
history copy/restore and terminal archive; occurrence creation/repetition,
group revision and retirement; day retirement and unplacement; saved conflict
evaluation and warning acknowledgement; and physical reservation replacement
or cancellation. Only the server-selected operation's fields are accepted.
An explicit group/sequence pair either uses an already-authorized group choice
or deliberately starts a new group. The new form supplies one opaque group key;
bound validation/retry retains it and requires an explicit sequence. This key
is edition-local grouping, not a foreign-record reference or authority, and the
existing owner command still enforces group/sequence uniqueness. Neither option
infers recurrence or creates additional occurrences. Creating the first
candidate/occurrence may observe edition control
zero; copying retained history requires a positive current control version.
Every successful Scheduling mutation advances that shared control, not merely
creation. A new command uses a fresh observed snapshot; stale pending input is
never automatically rebased.

Retirement, restore, archive, unplacement and physical changes require explicit
consequence confirmation. Draft changes leave physical holds unchanged.
Reservation reasons are visibly Venue-shared, and reservation commands retain
their separate exact Venue authority and transactional replacement/rollback.
Cancellation can select retained historical placement evidence after a draft
edit, but still requires the current physical booking version. Neither a valid
form nor warning acknowledgement bypasses fresh domain checks, overrides a
blocker or confers approval/publication.

### Fresh review and current physical readouts

`planning_review.load_scheduling_candidate_review` uses the existing conflict
and dependency-version field ceiling. It compares the latest saved report for
the exact current draft revision with freshly authorized owner dependencies.
No report from a previous candidate revision is silently presented as current.
Saved evidence is explicitly not recorded, current, stale or unavailable;
historical completeness is separate from current source availability. Only a
fresh complete matching warning without retained acknowledgement is eligible
for the acknowledgement command, which still independently authorizes and
rechecks all inputs. Blockers have no acknowledgement path. Closed findings
and acknowledgement existence may be shown, but source JSON, dependency
digests, fingerprints, calendars, acknowledgement rationale and actors are not
returned. Missing/overflowed/inconsistent findings withhold the projection.

`planning_reservations.load_scheduling_reservation_review` uses that same
independent Scheduling field ceiling and the existing exact-resource Venue
dependency query. It resolves the occurrence's latest reservation intent by
immutable receipt **control version**, not wall-clock timestamp. No intent
means no recorded reciprocal request; no Venue bookings are enumerated in that
case. Otherwise Venues independently proves the bound room and current physical
booking version/review state. Generic Venue cancellation is observed, while
draft movement/unplacement still shows an unchanged previous hold. There is no
new capability, edition-wide Venue grant or duplicate physical writer.

An active result includes only its exact same-edition booking version, source
candidate/version/placement and bound envelope needed for explicit replacement
or historical cancellation. This is the consequence of a current authorized
physical binding, not permission to browse arbitrary candidate history or
read private reasons, titles or approvers. Unexpected owner bindings fail
closed. Both readouts retain canonical edition/person order and required owner
and Scheduling audits; final denial/audit failure withholds all results and
rolls back success audits. Neither reader writes a report or domain command.

### Board and native rendering composition

`planning_board.build_scheduling_planning_board` is a database-free composition
of already-authorized Scheduling, Programme-title and Venue-label snapshots.
It distinguishes items before occurrence creation, occurrences before candidate
selection, unplaced/placed occurrences and retained retirement. Duplicate or
missing owner references withhold the whole board, rather than silently hiding
work. Stable day identifiers retain saved placements under revised day metadata;
changed day/occurrence revisions are labelled without rewriting geometry.
Nonempty day/room lanes are ordered by exact delivery instants; complete empty
day and room choices remain available separately for placement controls.

The initial `scheduling/planning_board.html` component reuses the management
shell, one H1/main, responsive labelled cards, explicit overnight dates/offsets,
current physical-hold readout and native form rendering. Owner labels are
escaped; generic forms retain input and link errors to controls. Submit buttons
provide the action exactly once, with Preview first for placement forms.

`planning_selection` separates transient `ui_` fields from exact command input
without flattening repeated values or discarding unknown fields. The caller
must authorize base scope before parsing. Candidate/day/room/item/occurrence
selection is checked against complete authorized projections before filtering;
selecting an item never implicitly selects its first repeated occurrence.
Text/state/day/room filtering changes only visible cards and lanes, retaining
complete form choices and the separately resolved selection. History/finding
IDs and history cursors still require their own protected queries. Neither
selection nor mutation input is persisted in a URL or browser storage.

`planning_controls.build_planning_control` composes one ordinary form from those
complete owner projections. It does not authorize, query or write. New forms
use the observed edition control or exact target version and a fresh retry key;
bound forms supply no new initial values and never rebase submitted versions.
An exact occurrence and service day are selected before opening the placement
form, so changing a target cannot silently reuse another target's version.
The same four instants and explicitly required host intervals prefill the
native fields. Missing context produces guidance, not an inferred selection;
read-only lifecycle hides new forms without rewriting an already bound retry.
Current-hold cancellation retains its original candidate/placement source,
while explicit replacement uses the current draft and the observed booking
version. Historical copy/restore never falls back from a missing selected
historical revision to current timing. Every submitted form still requires the
existing independently authorized owner command.

### Dormant HTTP workspace

`planning_views.scheduling_planning_view` is an unmounted GET/POST adapter with
ordinary CSRF protection, no-store responses and sensitive-POST masking. Actor
identity comes only from the authenticated request; organization, edition and
the parent label are server-resolved arguments. A successful audited base read
precedes private selection binding. Query-string filters, file uploads, unknown
actions, duplicated single-value fields and action/mode mismatches are rejected.
Native query forms carry the closed `ui_` namespace separately from exact
command fields. A query never becomes a writer because of hidden selection.

`planning_workspace.compose_planning_workspace` checks the selected task's
independent capabilities, queries Programme titles and Venue room labels, then
resolves selection against the complete board before filtering visible cards.
It loads only explicitly requested inspector, history, conflict or physical
layers; placement separately authorizes the current host roster. Both current
and historical candidate copy require independent history authority. Access and
task choices are computed from current policy and lifecycle, not a new ACL.
Owner transactions retain their canonical person-lock sets; the whole page is
not wrapped in an actor-first cross-owner transaction.

Native filters, the selected item, information layers, immutable history and
comparison, and current/saved conflict findings are rendered explicitly. Current
item labels beside historical geometry are marked as current, not retained
content. Shared availability discloses periods only for a shared relationship
and does not silently load host names. The closed `planning_presentation`
explanations identify each finding's cause and safe next action without owner
lookups or automatic overrides. Missing checks, saved completeness and fresh
source availability remain distinct.

Submissions delegate through the existing strict action adapters. Success
reloads actual owner state and selects the affected day, occurrence or draft;
preview keeps the exact unsaved form and retry key. Recoverable command errors
retain authorized input without rebasing optimistic versions. Permission loss
withholds all prior private context. A failed post-command refresh may follow
a committed command: the generic unavailable response never asserts failure,
and an exact retry confirms the retained result without duplicate writes. The
adapter does not log raw exception details or persist private form/filter input
in URLs, sessions or browser storage.

The lightweight `planning.js` enhancement uses the same native selection POST
for drag placement/movement. Only currently offered exact destinations are
accepted; the server reloads their versions before opening a form. Private
identifiers stay out of external drag payloads. Keyboard selection is equivalent,
including empty boards where an explicit day and room must first be chosen.
Day/room filters retain unassigned work while constraining placed entries; text
and explicit state filters still apply. Repeated occurrences have concise visible
references and full exact identities in native choices and submitted values.

Four unnamed range controls prefill individual native time fields on the selected
service day's grid. They use Events' explicit zone, preserve offsets through DST
and midnight, and neither clamp existing invalid input nor alter host intervals.
They do not supply a second command payload. Input remains unsaved until the
explicit native command; Preview still does not save. Navigation and unload
guards protect changed or server-retained pending forms without storage, autosave,
background requests or automatic version rebasing.

Browser rehearsal and protected acceptance are incomplete; consult CURRENT and
the checkpoint for verified cases and tool limitations. The page contract
documents a loopback-only opt-in fixture and local accessibility diagnostics.
No production URL or navigation entry is mounted; isolated component admission
and owner database tests are not provisioned runtime/profile evidence.

### Conflict-source boundary

The exact source descriptors are:

- `scheduling.service-day-and-placement@1`: current edition, day and occurrence
  versions, grid and time bounds;
- `programme.item-and-host-availability@1`: current item lifecycle and hosting
  applicability, selected confirmed current people, and only their currently
  deliberately shared per-item availability or preferences;
- `venues.physical-scheduling-dependencies@1`: active selected rooms and physical
  members, configured/fire capacity, current hard windows and live occupancy.

Programme's `load_programme_scheduling_dependencies` independently authorizes
the exact edition and restricted fields. Venue's
`load_venue_scheduling_dependencies` independently authorizes every exact space
for `physical_dependencies`. Both are audited and bounded. Current host periods
are consumed in memory, not copied into Scheduling history. Draft, withdrawn,
unconfirmed or unavailable host information does not mean that someone is free.
Empty host selection does not establish that hosting is unnecessary: Programme
must explicitly identify that concern as not applicable.

Required person presence is distinct from preparation/effective/teardown room
occupancy. The ordinary presence is effective delivery; preparation and
teardown do not silently require every host. Same-person contention uses a
Programme-provided edition-bounded conflict key. Room contention uses ADR 0053's
two-clique rule across every physical member, including room combinations.
Only the permitted preceding teardown/following preparation overlap becomes
an inspectable turnover warning.

Same-organization busy occupancy from another edition is clipped to this
edition's envelope. No foreign edition UUID, booking UUID, title or private
content is disclosed. The opaque physical source key is the first 128 bits of
SHA-256 over ASCII `venue-physical-conflict@1:<edition_uuid>:<booking_uuid>`,
formatted as a UUID. It is a scoped correlation key, not a generated identity,
capability or consent token. PostgreSQL verifies the same derivation without
an extension. Independent Venue approval advances the Booking version but
does not rewrite its still-valid version-one occupancy.

Persisted evaluation evidence has a closed three-source JSON schema: versions,
current membership/status, manifest digest, opaque busy sources and exact
binding status. It contains no calendars, person keys, host contact, private
Programme copy or proposal/review material. `is_complete` means those declared
sources completed, not that the candidate is approved or conflict-free.
`not_evaluated` explicitly lists staffing, rest, accessibility-fit and release
readiness; equipment/travel checks also remain future declared adapters.

Findings distinguish blockers, warnings and unavailable checks. Warning
acknowledgement requires explicit rationale and the current complete source
digest and finding fingerprint. Any relevant dependency change requires a
fresh evaluation; the old acknowledgement stays historical. PostgreSQL rejects
stale acknowledgement even if application freshness validation regresses.

## Reciprocal Venue reservation

Scheduling reserves a command receipt and immutable intent identity before
calling `venues.scheduling_reservations.apply_scheduling_reservation`. Venue
reloads live exact proof through
`scheduling.reservation_sources.resolve_scheduling_reservation_source`; the
receipt must be active in its original owner transaction. Reusing a retained
intent outside that command is not authority.

Both `scheduling.venue-reservation@1` and `venues.scheduling-reservation@1` must
be admitted, as must Scheduling reservation authority and independent exact
Venue-space management. New reservations require current draft candidate,
occurrence/day revisions, grid, capacity, physical lifecycle and hard availability.
Cancellation can reference the retained historical placement even after the
candidate or day has changed; it still requires the exact current Booking version.

Venue creates an unpublished draft `programme` Booking named only
`Programme reservation`, physical occupancy, immutable source binding and its
own history/receipt/audit/event/outbox. Only the new explicitly Venue-visible
reservation reason crosses the boundary; original private placement rationale
and item text do not. A replacement cancels the previous hold and creates the
new hold atomically. At most one active hold exists per occurrence. Any late
failure restores the prior occupancy and both owners' evidence.

The original placement author, reservation creator and last physical editor
cannot independently approve the hold. Approval requires another current
verified person and does not publish Programme timing. Generic Venue reschedule
and publication are denied for linked bookings. Generic cancellation remains
available and retains the binding; subsequent evaluations expose the missing
active reservation. Public/My Maru Venue schedule queries exclude linked rows.
Historical placement authorship survives account inactivity or loss of
verification: another current authorized planner can reserve the retained
placement. The original identity remains excluded from approval after account
recovery; the current reserver and approver must still be verified active people.
The future release child must coordinate activation or invalidation atomically;
this kernel has no released timetable to invalidate.

## Integrity, observation and remaining work

Commands lock the exact edition, canonical people, owner records and complete
sorted physical-member union before selected rooms. Ordinary Venue writers
share the physical lock order, including replacement across rooms. PostgreSQL
independently enforces closed evidence, scope, contiguous versions, immutable
manifests, same-command child evidence, reciprocal holds and exact effects.

`scheduling.planning.changed.v1` retains only the closed operation code in its
payload, scoped to the edition/control version with actor and correlation.
Operational diagnosis uses denied/unavailable/version-conflict categories,
receipt/correlation identities and readiness status. Do not log source JSON,
private rationale, host periods or private owner records as debugging payloads.

The [migration/recovery runbook](../operations/scheduling-migration-and-recovery.md)
describes exact schema/readiness, runtime ACLs and populated contraction fences.
An accessible editor, staffing adapter, independent Programme approval, atomic
release, role-specific outputs, on-site continuity, guided activation and
integrated acceptance remain separate mandatory children of #48.
