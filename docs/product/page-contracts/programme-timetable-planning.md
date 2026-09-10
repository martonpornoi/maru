# Programme timetable planning

- Status: Accepted contract; implementation in progress, not activated.
- Child: [Accessible editor #85](https://github.com/martonpornoi/maru/issues/85).
- Parent: [Programme Operations #48](https://github.com/martonpornoi/maru/issues/48).
- Predecessor: [Scheduling #81](https://github.com/martonpornoi/maru/issues/81),
  delivered through [PR #82](https://github.com/martonpornoi/maru/pull/82).
- Requirements: SCH-003, SCH-004, SCH-007 through SCH-011, PRG-008,
  UX-003 through UX-008, UX-019, UX-020, UX-027, UX-029, AUD-001, AUD-003,
  and NFR-013.
- Decisions: ADRs 0081, 0087, 0088 and
  [0092](../../architecture/decisions/0092-dormant-accessible-timetable-editor.md).
- Intended canonical destination: **Timetable planning**, in the existing
  selected-edition Programme Operations journey, not a second shell.
- Intended canonical route:
  `/admin/platform/organizations/<organization>/series/<series>/editions/<edition>/programme/timetable/`.
  It is not mounted in a production URL configuration by this child.

## Human outcome and scope

A Programme planner can organize accepted and organizer-created items into
explicit occurrences, place them in comparable private drafts, understand
conflicts, and recover an earlier alternative without losing the evidence.
The preceding task is Programme item/host readiness. Staffing, independent
approval, release, and on-site operation are subsequent mandatory tasks. They
are named as unavailable, not rendered as broken or executable-looking links.

This is a complete dormant editor component and its server adapters, not an
adoptable workflow. Neither current profile admits Scheduling. Routes,
navigation, runtime write permissions, and `programme_operations@1` activation
remain closed until the guided integration child and full acceptance. Tests
must distinguish synthetic component/domain evidence from genuine provisioned
runtime evidence. A test authorizer or database owner is never runtime proof.

## Authority and field boundaries

Resolve authenticated actor and exact trusted organization/edition before
loading labels or binding private input. Scheduling planning, history,
conflict-read, each mutation, and Venue reservation authority are independent.
Mutation permission does not imply any read permission. Closing, Archived and
Cancelled editions are read-only according to each owner's current policy.

The base planning projection contains bounded Scheduling-owned day, occurrence,
candidate, and placement facts. Programme working labels, approved public copy,
delivery instructions, readiness and host relationships are separate owner
queries with independent capability/field decisions and read audit. The item
inspector loads only the explicitly selected authorized layer; unauthorized
layer values, names, counts and relationship identifiers never reach the DOM,
JSON, logs or errors. Private proposal answers and review text never enter this
workspace. No host contact or withdrawn/unshared availability is copied into
Scheduling or browser persistence.

Venues supplies selected-room labels and minimized physical consequences
through its public owner boundary. Restricted room facts require their own
authority. Busy occupancy does not disclose another edition's booking identity
or content. Generic read permission is not physical reservation authority.

## Workspace and interaction

One H1, the shell's single `main`, a purpose statement, and computed **Access**
disclosure introduce the workspace. Show **Private draft — not published or a
room reservation** beside candidate identity and version, not only in help.

- A bounded, complete-or-explicitly-unavailable inventory distinguishes items
  with no occurrence, unplaced occurrences in the selected candidate, placed
  occurrences, and retained retired occurrences. Repeated occurrences remain
  distinct. No silent first-page truncation may imply a complete programme.
- Candidate, service-day, room, text and placement-state filters keep a stable
  selection through actions and validation. Clear filters is always available.
  Day/room filters constrain placed work, but keep unassigned items and
  occurrences available to place there. Text and explicit placement-state
  filters still apply to that backlog. Filtering never assigns a day or room.
  Persist no sensitive filter or form value in local/session storage or a URL.
- An ordered day/room board displays exact local date/time, edition IANA zone,
  preparation, effective delivery and teardown. Overnight days do not reset at
  browser midnight. Narrow screens have equivalent labelled ordered cards;
  only an explicitly labelled board region may scroll horizontally.
- Selecting an item exposes an ordinary explicit placement form. Choose exact
  occurrence, service day and room, requested capacity, the four ordered
  envelope times, and explicitly required host-presence intervals. Group and
  sequence fields create/revise ordinary occurrences; repetition creates an
  explicit additional occurrence, never an implicit recurrence rule. A planner
  may deliberately start the first group with an explicit sequence; its opaque
  pending group key survives validation and retry without creating extra work.
  Select the exact occurrence and service day before opening a placement form;
  a target change must never reuse another target's optimistic version.
- Pointer placement/movement is a form-prefilling accelerator. Keyboard users
  select the same item and destination using ordinary controls. Resize edits
  the same four times. No pointer path saves, reserves, confirms a host,
  acknowledges a warning or invents a person's explanation automatically.
- Local-time input rejects ambiguous/nonexistent minutes; explicit UTC offsets
  can disambiguate an instant. Show the edition zone and offsets where needed;
  the browser's own time zone never chooses the instant silently.
- Native submit buttons supply the closed action exactly once. Do not render a
  second hidden action with the same name; repeated single-value fields fail
  validation. The placement form's default submit path is Preview, never Save.
  Transient selection uses a separate closed POST namespace; neither unknown
  fields nor repeated values are discarded, and selection cannot supply actor,
  tenant, command versions or retry attribution.
- Record forms accept only their selected existing command's fields. Retirement,
  restore, archive, unplacement and physical changes require explicit consequence
  confirmation. Reservation rationale is labelled as shared with Venues. A
  fresh planning snapshot supplies the shared edition control for a new intent;
  every successful Scheduling mutation advances it, not only creation.
- Preview reports the proposed envelope and exact available conflict sources
  without committing a placement. Save invokes the same versioned Scheduling
  command from every input method. Invalid structure cannot be saved. A
  structurally valid conflicting draft is explicitly blocked/unchecked, never
  presented as approved, conflict-free or a physical reservation.

## Conflict and reservation review

Use text labels for **Blocker**, **Warning**, **Unavailable** and historical or
stale evidence. Every finding states the cause and safe next action. Display
checked sources and the explicit not-evaluated staffing, rest,
accessibility-fit and release-readiness concerns. A missing source is not a
pass. Historical evaluation and warning acknowledgement cannot appear current
without fresh dependency comparison.

A warning acknowledgement requires a fresh complete evaluation, exact finding
fingerprint and explicit human rationale. Hard blockers and unavailable checks
have no override action. Draft save, conflict evaluation, explicit physical
reservation and independent physical approval remain separate operations.
Reservation replacement/cancellation explains the existing hold and requires
human rationale, exact versions and independent Venue authority. Moving or
unplacing a draft leaves any existing hold unchanged and explains that fact.

## History and recoverable draft state

History and comparison require independent read authority. Compare selected
immutable candidate revisions using stable occurrence identity, including
added, removed, moved/resized and unchanged placements. Show source versions
and exact envelopes; current owner labels do not masquerade as historical
content. Copy preserves the exact source; restore adds a new revision and
requires explicit rationale. Archive is terminal and recoverable by copying,
not by deleting history. An unplacement removes only the current manifest
membership, not the occurrence or physical reservation.

Safe entered values survive validation and recoverable request failure within
the current authenticated page. Keep one retry key for the exact same pending
intent; a new intent receives a new key. Stale state requires deliberate
refresh/rebase, never automatic retry against a newer version. Switching
candidate, day or edition while editing warns before discarding unsaved input.
No offline write queue, autosave claim, personal-data browser cache or hidden
background mutation is introduced.

The native request adapter uses ordinary CSRF protection, sensitive-POST
masking and no-store responses. After a completed command it reloads actual
owner records, rather than presenting optimistic browser state as persisted.
If that reload fails, completion is uncertain from the page's point of view:
do not claim that nothing changed. Retrying the exact pending intent confirms
the retained result without duplicate writes. If current permission or a
complete owner read cannot be proved, withhold the whole private workspace;
recoverable command failures retain input only while that context remains
authorized.

## Failure and accessibility acceptance

Cover empty setup, populated planning, denied base and restricted layers,
read-only lifecycle, field validation, stale source/candidate, incomplete
dependencies, explicit overflow, retry collision, network/audit failure,
successful save and historical recovery. Denial is non-disclosing. Failed
commands leave no success message or partial owner state. Return focus to the
selected occurrence or linked error summary and announce save/preview results
without depending on color, position, animation, hover or drag.

Complete the same synthetic journey using pointer, keyboard and explicit forms.
Inspect 320, 390, 768, 958, 1024, 1280 and 1920 CSS pixels plus 200% zoom,
reduced motion, focus order, one H1/main, duplicate identifiers, overflow and
automated accessibility findings. Record unperformed screen-reader or real
runtime/profile evidence explicitly; a component fixture is not production
acceptance.

## Verification and non-goals

### Repeatable synthetic browser fixture

After provisioning an isolated disposable PostgreSQL instance and installing
the existing frontend dependencies, run from the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = 'postgresql://maru:maru@127.0.0.1:<isolated-port>/maru'
$env:MARU_EDITOR_REHEARSAL = '1'
.venv/Scripts/python.exe -m pytest tests/rehearsals/programme_timetable.py --reuse-db --liveserver=127.0.0.1:0 -s -q -p no:cacheprovider
```

Use only the printed `REHEARSAL_READY` loopback URL. Never point this command at
production or a shared development database. The explicit file is outside normal
pytest discovery, requires isolated-test authorizer admission, asserts a test
database and loopback host, and creates synthetic accounts/records through the
existing fixtures and owner commands. Its visible role buttons select pre-created
planner, view-only, manage-only, independently restricted-layer or anonymous
sessions; they are fixture controls, not an application login or grant path.
Current-profile denial remains independently available. Fault controls simulate
an unavailable title owner or a real concurrent edition-control change.
Additional fixture controls use the synthetic host's existing owner command to
share availability with a non-preferred placement or withdraw that availability.
Use them to rehearse exact warning acknowledgement and stale dependency recovery;
they do not give a Programme planner authority over another person's availability.

The fixture alone serves the already installed axe-core asset and a visible
**Run automated accessibility check** button. Results inspect the actual rendered
document, excluding fixture diagnostics, without downloading scripts, sending
page data or persisting results. Record violations and incomplete/manual-review
rules separately. A successful analysis does not prove all keyboard, screen-reader,
zoom, reduced-motion or production states. These diagnostics never enter production
routing or assets.

Finish through **Finish and close synthetic fixture**, which releases its database
lease; a one-hour ceiling also prevents an indefinite fixture. Do not run another
database suite against that same instance while the fixture is open. Pytest's
passing fixture and elapsed time report cleanup/lease duration, not completed
browser acceptance or PostgreSQL test performance. Record actual roles, actions,
widths, outcomes and gaps in the checkpoint. Reopen a fresh fixture after changing
templates or assets so server/browser caches cannot validate an old version.

### Required evidence and exclusions

Issue #87's [assisted observations](../../checkpoints/2026-09-10-programme-browser-assisted-observations.md)
record maintainer-operated native Cancel/discard, populated 200% Chrome zoom
and interaction with Windows Animation effects off. Browser-control timeouts
prevented automated preference/viewport readback. Chrome 152.0.7977.83 (64-bit)
and normal fixture closure are recorded. The maintainer also confirmed visible
Tab focus kept in view at 200%. Protected PR #90 delivered the evidence and
closed #87; its [delivery checkpoint](../../checkpoints/2026-09-11-programme-browser-protected-delivery.md)
records exact-source verification and the approved local recovery exception.
This is bounded synthetic evidence, not full
UX-029 or activated Programme acceptance.

Use focused unit/adapter tests for strict inputs, time conversion, safe errors,
comparison, interaction parity and retained form state. Real PostgreSQL tests
exercise owner-backed queries/commands, field/scope denial, immutable history,
stale/version/retry behavior, audit-before-disclosure and rollback. Retain
current-profile, unmounted-route and SELECT-only runtime denial tests. Run the
required exact-head local and hosted protected gates before closing the child.

No staffing writer, approved Programme release, attendee/personal/public
schedule, export/print continuity pack, profile/root-role expansion, unrelated
side effect, production data or general Docker cleanup is included. Issues
#22, #23, #24 and #42 remain independent. #48 remains open after this child.
