# Scheduling module

Status: dormant candidate/conflict, physical-reservation and atomic-release kernel,
consumed by unmounted Programme components; no current profile or route activation.
Last updated: 2026-09-11. See [CURRENT](../project/CURRENT.md) for verification
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
Workforce owns Shift demand and volunteer commitments; their governed Programme
binding is delivered by #88.
Scheduling must use those owners' documented services, not their private models.
Cross-owner database integrity deliberately verifies the exact foreign graph;
it is not a user-facing data-access path.

`staffing_references.resolve_staffing_occurrence_reference` supplies only one
exact Programme-item-linked occurrence ID, metadata version and active/retired
consequence. The independently authorized caller holds the canonical edition
write scope. It provides no candidate, placement, public copy, host detail or
authority, and never selects a timetable alternative. Requirement changes do
not mutate Scheduling state. Exact candidate/placement demand binding is now
implemented through the Workforce owner and delivered by #88.

Neither `full_convention@1` nor `workforce_only@1` admits the new capabilities,
adapters or conflict sources. Scheduling tables and the Venue binding table
remain runtime SELECT-only. A schema migration, retained UUID,
platform role or successful isolated test does not activate this workflow.
There is no new production HTTP route, API, worker or effect-delivery handler.
The native editor and staffing continuation remain unmounted components. No
Registration, Participation, payment or attendance record is created.

## Owned state and commands

The #96 release work remains dormant and under delivery verification. Its contracts
are `release_inputs` (exact versioned intent), `release_dependency_rules`
(complete journal temporal consequences), `release_artifacts` (one mandatory
canonical identity-only manifest), and the private `release_authorship`
collector. The last walks complete candidate history through each exact copy
source, checks selected-placement introduction, and includes contributors whose
work was removed or restored. Later edits to a source candidate do not change
an earlier copy's ancestry; inactive former authors remain exclusions, not
required active approvers. Total ancestry metadata is bounded at 10,000 revisions
and 100 candidates; overflow is unavailable rather than partially independent.

The private `release_capture` compositor now assembles its entire owner-resolved
person set, including an independently selected approver, before taking sorted
Identity locks. It recollects Programme and Workforce references before acquiring
the complete Venue physical closure, and then repeats the ten-category preflight.
Its current result includes exact selected public-rendition identities and at most
65,536 typed dependency uses. Multiple operational uses of one source for the
same placement retain their latest immutable end; unrelated publisher-only
identity does not change approval source membership. The separate private
generation step locks and validates each native source before getting or creating
its unique tracking key. All writes and nested read audits share the outer
Scheduling command transaction. Collection alone creates no approval, artifact
or active pointer; the release commands below consume it under their complete
native review/publication graph.

The canonical artifact retains the exact release, approval, candidate revision,
complete source digest and occurrence/placement/approved-public-rendition
membership. It contains no private copy, calendar, human reason, account or
arbitrary file URL. A nonempty complete selection is required, up to 2,000
occurrences and 2 MiB. Verification reconstructs expected semantic bytes from
independently resolved source references: a recomputed checksum over altered
membership is not enough. This internal manifest does not authorize disclosure;
future outputs must use its exact references and current governing invalidation.

Dependency-key and journal state is owned by the #96 release boundary. Global Identity
and organization-level physical scopes are explicit closed exceptions to ordinary
edition-owned records. SQL authenticates and locks each native source before first
tracking, retains immutable identity, requires consecutive journal-backed advances
and supplies database-owned change times. No background refresh grants current
serving authority.

For Venue property, selected-space and booking sources, first tracking also
captures the completed native source version under its row lock. A pre-capture
change already represented by that sealed version needs no retrospective journal
entry. Post-capture operational changes must advance the native version and the
journal; raw reuse/regression and auxiliary writes after the source receipt are
rejected. Existing pre-baseline keys retain zero and remain conservatively
journal-governed. These baselines are database-owned, not caller declarations.

`release_changes.record_identity_release_deactivation` consumes live native Audit
evidence from Identity's emergency command. `record_programme_release_change`
uses Programme's SQL `maru_programme_release_mutation_sources(receipt_id)` seam:
closed operational receipt/result references, never caller-supplied host identity
or private values. SQL independently joins the exact audit, receipt, scope and
host revision. Source changes acquire no foreign release pointer and create no
Scheduling state for untracked sources. Private working edits, discussion and a
new approved rendition do not withdraw an older exact approved copy. Relationship
withdrawal affects host disclosure separately from availability changes.

`record_workforce_release_change` uses Workforce's native SQL receipt seam with
the exact retry-key hash, actor, scope, operation and target. Shift commitments
advance their demand dependency; changes to current shared availability and
assignment endings advance separate sources. These changes do not silently edit
Shift commitments. A plan saved privately after sharing no longer supplies
future coverage. Deferred owner guards require the same-transaction consequence.

`record_events_release_change` joins envelope changes and operational ending,
not ordinary Ready/Live progression. `record_venues_release_change` joins exact
property, availability and physical-booking receipts, excluding independent
Venue publication/withdrawal. Venue auxiliary rows cannot change a tracked sealed
source version; a new native version must carry a fresh journal consequence.

These joins call `maru_scheduling_record_native_release_change`, a narrow
SECURITY DEFINER function which rechecks current owner proof and source-before-key
locks, and can only advance an existing key with immutable native evidence. It
cannot create keys, approvals, releases or pointer state. The explicit v4
runtime function allowlist and genuine-login tests retain SELECT-only table
containment, including Audit witnesses; historical audit UUIDs cannot be replayed.
Venue immutable retry receipts are read without an unnecessary UPDATE lock.

The native guard manifest pins complete migration sources, exact SQL operations,
required recorders, supporting-owner trigger attachments and literal arguments,
and live function metadata. `release_integrity.with_native_release_integrity`
is the documented composition seam for Programme, Venues and Scheduling probes.
Only the explicitly listed helpers may have owner-plus-configured-runtime ACLs;
all other guards stay owner-only. Missing grants, PUBLIC, an extra grantee,
delegated grant options or an undeclared helper keep readiness unavailable.
The execution-boundary migration revokes defaults, creates no grants,
and refuses to reopen execution once native witness or tracking evidence exists.
Scheduling 0020 fences the full extension before earlier used-evidence checks
could permit partial reversal. This guard proof supplements, not replaces,
the complete runtime-role probe and persisted release graph/schema checks.

`workforce_person_obligations` is a distinct global account-only source for
unpublished approval freshness. Its native attribution remains the actual
Workforce receipt and scoped Audit. It detects claim/withdrawal round trips
without persisting foreign work identifiers in another edition's dependency
manifest. Account source tracking and native work changes serialize in both
orders, including first capture; source capture itself proves neither person
eligibility nor an approved timetable. This approval-only generation does not
replace reciprocal ongoing published-host work/rest protection.

The additive release schema separates reasoned exact warning
acknowledgements, independent approvals, selected immutable placements/public
renditions, captured dependency uses, verified artifact bytes, retained
publications and withdrawals, and one monotonic edition pointer. Its schema is
not command, complete SQL integrity or acceptance evidence. Canonical publication
locks, full raw-source containment, readiness/recovery, release commands and
checked serving remain unfinished.
No preparatory component constitutes a published release, a satisfied artifact
pipeline or an activation permit.

Release authority is separately declared by
`scheduling.acknowledge_release_warnings`, `scheduling.approve_release`,
`scheduling.publish_release` and `scheduling.withdraw_release`. All are exact
edition-scoped, restricted and reason/audit obligated. Neither current adoption
profile includes them; declaring their vocabulary creates no grants or route.

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

## Native staffing continuation

The [staffing page contract](../product/page-contracts/programme-staffing.md)
extends Timetable planning, not a second shell or route.
`planning_staffing_workspace` composes one exact item/occurrence purpose under
canonical owner locks without adding staffing reads to the base planning query.
Requirements/history, binding/history/choices and minimized coverage retain
independent owner admission and audit boundaries.

`planning_staffing_forms` defines closed requirement and work preview/apply inputs;
`planning_staffing_actions` dispatches public owner commands after checking trusted
scope and exact selected identities. Original versions, source references, reason
and retry key survive recoverable failures. Preview adds its digest but neither
rebases versions nor applies work. Apply needs fresh authority from both owners,
explicit confirmation and a separate submit action. Read-only users may preview
authorized impact but have no apply action. Withheld coverage has null counts.

Fixed-ceiling history shows retained terms/reasons without loading a personnel
directory. Overview, control, error and impact headings receive purpose-specific
focus. Exact demand references identify the continuation in existing Shift
planning; production cross-route hosting remains later activation work. This
panel never opens, independently confirms or locks a Shift.

The opt-in `tests/rehearsals/programme_staffing.py` lease uses real owner-backed
fixtures and ordinary synthetic sessions on a loopback test server. Explicit
`MARU_STAFFING_REHEARSAL=1`, a disposable test database and sealed policies are
required. Run it directly through pytest, finish with its visible control and
record browser evidence separately; a passing lease proves cleanup only. Never
share its database with a concurrently running integration suite.

## Complete release eligibility

[ADR 0094](../architecture/decisions/0094-complete-programme-release-eligibility.md)
and SCH-012 define `release_eligibility.evaluate_release_eligibility`, a pure
database-free rule boundary. It requires all ten release categories against one
exact scoped snapshot. Missing checks remain unavailable; stale/blocked checks,
hard findings and unacknowledged warnings prevent eligibility. Only the closed
hosting/staffing/person/rest categories permit owner-proven inapplicability.
The rule itself adds no caller-facing success flags, owner collector, route or
command. The independently authorized collector is described below.

Checks, findings and acknowledgement references use immutable tuples and exact
enums. Digests are lower-case SHA-256, category count is bounded by the vocabulary,
and findings/acknowledgements retain the 10,000 limit. Unknown, duplicate,
over-bound, foreign-snapshot or orphaned evidence raises the content-free
`scheduling_release_evidence_invalid` validation error. Results use stable
category/fingerprint ordering, expose no copied calendars or private rationale,
and neither read nor write database state. The result is not an approval receipt.

The protected collector independently authorizes and audits every owner source,
proves complete membership and applicability, and computes the scoped candidate/
policy/dependency digest. Authenticating retained release acknowledgements is a
mandatory approval-workflow successor, not part of this source-only boundary.
Approval/publication must recollect and reauthorize under canonical locks.
The rule function does not authenticate supplied facts and must never be exposed
as an alternative authorization path. Existing `is_complete` planning reports
still declare staffing, rest, accessibility-fit and release-readiness deferrals.

No migration or runtime ACL change is needed for this prerequisite. Ordinary
code rollback removes only unused policy code; it creates no durable state to
reverse. Independent persisted approval, atomic publication,
physical invalidation, shared projections and current privacy consequences are
mandatory successors before any release can be offered.

### Trusted complete release preflight

[ADR 0095](../architecture/decisions/0095-trusted-programme-release-sources.md)
adds `release_preflight.load_release_preflight`. It takes trusted scope and exact
candidate/revision/version, independently requires `release_preflight` under
`scheduling.view_conflicts` and the unpinned `scheduling.release-preflight@1`
adapter, and returns exactly the ten closed categories, minimized selected-
occurrence findings and pure eligibility. It accepts no caller facts, calendars,
applicability flags, warning acknowledgements or approvals. The companion
`release_candidate_queries.load_release_candidate_source` requires the separate
`scheduling.release-candidate-source@1` adapter and complete planning authority.
Empty, stale, foreign, archived or incomplete exact manifests are unavailable.

The compositor first resolves the complete Programme/Workforce person union and
globally ordered Identity locks through the combined-person owner query, under
the shared parent transaction. Only then may narrower source readers lock people.
Failure to establish that union aborts; it must not continue with actor-only locks.
Every category comes from the owner: seven current Programme concerns and current
independent copy; selected hosts; current independent physical approval and
constraints; exact Programme accessibility-fit decisions; current bound staffing
or explicit no-staffing; and complete combined person/rest consequences.

`release_staffing_sources` composes current requirement/manifest/binding/coverage
proofs. Only active requirements need current covered or locked-covered work;
retired requirements still retain operative predecessor demands as blockers.
Claims, draft/open gaps, review-required confirmation, stale binding and accepted
underfill cannot satisfy coverage. Cancelled/completed work stays in the source
fingerprint but cannot cover active needs. A complete empty need/work set still
requires the explicit Programme placement decision. No later publication of past
work is implicitly exempted; the publication successor must contract safe retained
history/current-duty behavior before Live activation.

Missing documented owner evidence is unavailable, never omitted or zero. Field
denial, mandatory audit failure and database errors abort disclosure. Programme,
Workforce and Scheduling authority is rechecked at the final composition boundary.
Venue physical/access sources are re-read for consistency without taking a new
physical lock in an inverted order. Findings retain the existing 10,000 bound;
the complete source fingerprints cover any deduplicated safe conflict projection.

The digest binds exact scope, profile, policy, candidate, source versions and
minimized consequences. It excludes caller-only identity/locks, correlation and
audit IDs so independent authorized workflow roles observe identical evidence.
Private source DTOs, copy, reasons and calendars are not persisted by Scheduling.
Only required sensitive-read audits are written. Old planning acknowledgements
do not apply: all release warnings remain unacknowledged in this source-only
preflight. Neither a successful response nor its digest is portable authority.

No current profile, route, writer, output or worker is activated. The following
child must retain independent approval and release-warning evidence and repeat
collection inside atomic publication/invalidation. See
[source migration/recovery](../operations/programme-release-sources-migration-and-recovery.md).

### Dormant review and publication commands under development

Issue #96 adds `acknowledge_programme_release_warning` and
`approve_programme_release` through the existing Scheduling command boundary.
Their closed inputs select an exact candidate/version/source digest; they accept
no caller-supplied eligibility result. Independent owner admission, complete
source recollection and warning checks precede writes. Working/copy/restore
authorship remains an exclusion even after an earlier author leaves.

`publish_programme_release` rechecks that retained approval using a separately
authorized publisher distinct from the approver. It may not create replacement
tracking keys or refresh captured generations. The required internal
`programme.release.canonical@1` artifact contains exact release/approval/source
and placement/rendition references, not a public timetable or permission to
disclose content. Both Python and PostgreSQL compare its semantic canonical
bytes with retained selections; checksum consistency alone is insufficient.
The database requires the artifact before the active-pointer write. Release,
artifact, pointer, command receipt, native Audit witness, event and outbox remain
one transaction. Failures preserve the previously committed pointer.

`withdraw_programme_release` uses separate reasoned authority and exact pointer
identity/version. It locks captured person references before changing the
pointer, but does not require an unsafe or withdrawn source to become eligible
again. Withdrawal retains immutable release/artifact history and advances the
pointer to explicit absence; later publication cannot reset the version.
Added/changed/removed counts compare exact occurrence/placement/rendition choices
with the prior active release, not private draft labels.

Migrations 0015–0017 add owner-only native dependency-membership derivation,
bounded complete review membership, independent retained authorship and exact
review/publication graphs. Same-transaction child evidence joins the original
receipt's unique edition/control event and native Audit witness, so a new audit
cannot reopen a committed approval. Ordinary role authorization and the complete
ten-category business checks remain application/owner contracts; structural SQL
membership or an Audit witness is not an eligibility or capability grant.
New helpers have no PUBLIC execution or runtime writer grant. Populated review
and publication downgrades are fenced for fix-forward recovery.

`release_queries.load_programme_release_manifest` is the dormant checked-reference
read boundary. Current selection requires `scheduling.view_planning`; explicitly
selected history independently requires `scheduling.view_history`. Both require
the `release_manifest` field ceiling, current exact-scope reauthorization and a
successful sensitive-read audit. They return no private reasons, people, artifact
bytes or owner content. Withdrawn/invalidated releases yield no selections.
The reader verifies the exact semantic artifact and obtains all current dependency
generations and complete indexed journal-range aggregates in one statement
snapshot. Gaps, scope errors or missing evidence fail closed. Operational changes
are interpreted against immutable obligation ends; disclosure has no historical
expiry. Superseded history uses the same checks, not a last-good fallback.

Ended intervals retain their exact approved history: a later operational change
does not assert that the earlier approval was unsafe, and a previously recorded
invalidation does not disappear when its interval ends. This is approval history,
not attendance or proof that work happened. A fresh release still requires complete
current eligibility for every selected placement; historical staffing is not future
coverage, and historical references cannot waive current source checks. Explicit
copy withdrawal continues to govern even an ended historical interval.

This is a point-in-time manifest, not an enduring permission token: role-specific
consumers must independently authorize and check current owner disclosure while
rendering its exact retained references. No normal consumer, route, profile or
worker is activated. Focused native-command, raw-bypass, reciprocal host/Workforce,
shared physical and foreign-publication races exercise both commit and rollback
orders. Complete source-pinned readiness, genuine-runtime containment and
same-image physical recovery have focused evidence. See CURRENT for exact
certification/delivery status; this contract is not production acceptance.

## Dormant release-derived public output

[ADR 0097](../architecture/decisions/0097-release-derived-programme-output-boundaries.md)
defines #99's output boundary. `public_release_references.load_public_release_reference`
requires the exact edition's `scheduling.public-release-output@1` adapter, which
no current profile pins. It accepts no actor, planner policy, candidate, historical
release selection or caller-provided source evidence. The checked active manifest,
complete selected effective geometry and exact immutable service-day windows are
internal owner references, not portable serving permissions. Private planning day
labels and preparation/teardown phases are not public output fields.

`output_queries.load_public_programme_timetable` composes independently resolved
Programme reviewed copy and Venue wayfinding under canonical shared parent locks,
then rechecks the complete current reference. Every owner re-resolves admission
and the release itself. Absent, withdrawn and invalidated states have no entries;
missing, changed, incomplete or unavailable owner evidence raises rather than
returning partial or last-good content. Public reads create no visitor audit actor
or activity stream and perform no Participation/Registration discovery.

The result explicitly separates immutable release publication time from the
server's last checked time. Venue labels carry their own current room/venue
versions; they are not a historical label snapshot. The query returns no host
identity, contacts, availability, staffing names, working copy or private reasons.
Personal and operator layers remain independent, purpose-bound #99 work.

`output_rendering` implements `scheduling.public-timetable@1` JSON and a public
iCalendar download from the same freshly obtained typed projection. Strict shape,
text, identity, instant and state validation rejects cross-audience dictionaries,
duplicate occurrences, over 2,000 rows and output over eight MiB. JSON uses UTC
ISO timestamps and an explicit public audience. It must be served as JSON with
`no-store` and `nosniff`, never interpolated into HTML.

Calendar encoding follows [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html),
including escaped TEXT, CRLF and UTF-8-safe 75-octet folding. Occurrence UIDs
remain stable across releases; extension properties retain release, pointer,
rendition, service-day and current wayfinding versions. Effective start/end
instants are UTC. `DTSTAMP` records the materialized observation; no invitation
method, attendee, organizer, alarm, recurrence or external URL is emitted.
Public events are transparent, not a claim of personal work. Unavailable states
cannot produce a calendar download. Already imported or printed content cannot
be remotely erased or guaranteed current by these ordinary adapters.

No production route, profile, runtime writer or new background effect is mounted
by these boundaries. CURRENT owns focused versus exact-commit delivery evidence.

## Integrity, observation and remaining work

### Personal host release reference

`personal_release_references.load_personal_host_release_reference` uses the
non-persistable `scheduling.view_host_self` capability with only
`own_host_schedule` fields. No current profile pins it, and it grants no planner,
roster or public-copy authority. The real exact-self policy is followed by
Programme's independently authorized own-purpose query. No confirmed hosting
means no release lookup; the result's release state and pointer are `None`,
not a false claim that no timetable was published.

For confirmed purposes the canonical active manifest and native dependency
consequences select only their own approved presence. Each presence retains
stable occurrence, exact placement, room and service-day identity, required
presence start/end, and the separate three-phase placement envelope. The envelope
is context, not an instruction that the host must cover every phase. Selected
presence completeness, scope, item ownership and interval bounds are checked;
Programme purposes and release state are rechecked before final Scheduling
authorization and mandatory `scheduling.query.personal_host_release` audit.
Unavailable/withdrawn/invalidated sources provide no approved host intervals.
Retained invitations remain private own history, and accepted Workforce work
is never changed by this reference. Room labels and private rendered transports
still require their separate owner/composition boundaries under #99.

The new self capability adds no persistable grant or schema permission; existing
native grant allowlists remain unchanged. Its catalog, self scope and exclusion
from every current profile are covered separately from edition planner grants.

`personal_output_queries.load_personal_timetable` composes only independently
adopted hosting and Workforce layers. `None` means unadopted; empty means an
authorized owner found no own records. A missing half of a layer's profile
contract or adopted-but-denied/unavailable/moving data fails closed. Independent
Venue wayfinding covers only approved own host rooms. Workforce-only needs no
Programme or release query. No returned layer edits accepted work, creates an
attendee relationship or claims attendance.

`personal_output_rendering` provides `scheduling.personal-timetable@1` JSON and
private RFC 5545 calendar snapshots. It accepts only the closed private DTO graph,
not a dictionary, public response or extra owner fields. Bounds cover 2,000 host
purposes, 2,000 own released occurrences, 4,096 retained Shifts and eight MiB of
encoded output. Dates are aware/UTC, source collections deterministically sorted,
and complete room/purpose membership, interval ordering, lifecycle and source
state are validated. Public and private serializers cannot interchange payloads.

Private calendars use stable host-purpose/occurrence and Shift-commitment IDs.
Required host presence remains distinct from surrounding preparation/delivery/
teardown context. Claims are `TENTATIVE`, confirmed work `CONFIRMED`, removed
records `CANCELLED`; completed work is labelled historical and transparent.
Operative claims and confirmations remain opaque time commitments, not attendance.
Current demand location is explicitly described with its instruction version,
not emitted as an allegedly immutable accepted `LOCATION`. Withdrawn/invalidated
host release state blocks a combined calendar while JSON/rendered views may
still show unchanged retained work. No recipients, invitation method, alarms,
remote-erasure, reliable client-update or offline-freshness promise is emitted.

`personal_output_views` provides the dormant exact-person shared My Maru surface
and complete freshly checked HTML/print, JSON and calendar transports. It binds
only the authenticated account, rejects subject/filter/duplicate query arguments,
and never falls back to another owner's data. All responses are private/no-store;
denied scope is 404, invalid input 400, incomplete evidence 503, and withdrawn or
invalidated hosting calendar requests 409. HTML still shows unchanged work.
Actual own records justify a minimized Events edition label/version; empty own
scopes never discover names. The chronological agenda labels own required host
presence, surrounding event context, tentative claims, confirmed and historical
work independently. The [personal page contract](../product/page-contracts/personal-programme-timetable.md)
retains source, responsive, print and deferred human-acceptance requirements.

### Native integrity and recovery

All command transactions and locking planning reads acquire the shared Workforce
parent scope before the Events edition, person set and Scheduling rows. The
Events fact read reuses that held edition lock. This matches Programme source
commands and binding operations: edition-first locking can otherwise deadlock
against a binding's Organization lock during deferred receipt foreign-key checks.
The source-movement, source-edit/read and binding races exercise this order.

Commands lock the exact edition, canonical people, owner records and complete
sorted physical-member union before selected rooms. Ordinary Venue writers
share the physical lock order, including replacement across rooms. PostgreSQL
independently enforces closed evidence, scope, contiguous versions, immutable
manifests, same-command child evidence, reciprocal holds and exact effects.

`scheduling.planning.changed.v1` retains only the closed operation code in its
payload, scoped to the edition/control version with actor and correlation.
Release decisions use the separate dormant `scheduling.release.changed.v1`
schema with only their four closed operation codes. Each family rejects the
other's operations. Neither event activates a handler or profile route; the
dormancy check covers both families. Release notifications and projections
remain separate successors, not side effects of registering this schema.
Operational diagnosis uses denied/unavailable/version-conflict categories,
receipt/correlation identities and readiness status. Do not log source JSON,
private rationale, host periods or private owner records as debugging payloads.

The [baseline migration/recovery runbook](../operations/scheduling-migration-and-recovery.md)
and [atomic-release extension](../operations/programme-atomic-release-migration-and-recovery.md)
describe exact schema/readiness, runtime ACLs and populated contraction fences.
The native editor and staffing were delivered dormant through #85 and #88.
Neither release eligibility nor dormant approval/publication adds a live workflow.
Role-specific outputs, on-site continuity, logical-restore compatibility (#97),
guided activation and integrated acceptance remain mandatory #48 work.
#87 is delivered; representative-human
and integrated acceptance remain separate gates.
