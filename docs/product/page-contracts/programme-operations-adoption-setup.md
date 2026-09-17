# Set up Programme Operations contract

- Status: Accepted contract, runtime inactive. Dormant Applications, Programme,
  Scheduling, staffing, release, notice, continuity and guided task components
  are installed. Accountable setup, the complete isolated fixture, final
  acceptance and profile promotion remain incomplete; the production setup
  route and current-profile authority remain absent.
- Reserved route: `/admin/platform/setup/programme-operations/` (deliberately
  non-routable until the complete integrated profile is implemented and
  accepted)
- Requirements: IDN-011, IDN-012, IDN-014, EVT-001, EVT-002, EVT-005 through
  EVT-007, HR-009, HR-013 through HR-015, PRG-001 through PRG-011, SCH-001
  through SCH-012, OPS-001, OPS-002, OPS-005, OPS-008, OPS-009, INT-005,
  INT-007, INT-008, UX-005 through UX-008, UX-019, UX-020, UX-027, UX-029,
  UX-030, NFR-003, NFR-005, NFR-008, NFR-009, and NFR-013
- Decisions: ADRs 0051, 0053, 0078, 0080, and 0081 through 0084

## Purpose and primary user

Let a convention's Programme department adopt Maru from calls and organizer-
created items through reviewed readiness, conflict-aware timetable planning,
Workforce-owned volunteer coverage, one approved release, role-specific run
sheets, and a printable on-site fallback.

The primary setup user is an active platform administrator. Programme
coordinators, reviewers, hosts, planners, venue operators, Workforce
organizers, volunteers, independent approvers, publishers, and on-site readers
then use purpose-bounded workspaces. None of those relationships makes a person
an attendee or creates edition Participation.

This page describes a future composite capability. The installed dormant
Applications Programme-call/proposal and Programme item/readiness schemas and
catalogs are not adoption. No current page, API, navigation entry, setup
command, profile choice, or edition database value may imply that
`programme_operations@1` is executable. The reserved route must return the
ordinary safe not-found response until the complete manifest and its runtime
guards are implemented and validated.

The dormant Programme private item/readiness foundation retains the exact
Issue #61 containment contract. Applications now has separately dormant call,
acknowledged-proposal, preview-first import, and race-safe Department ownership
continuity foundations without weakening it. Ownership continuity resolves the
retirement prerequisite but does not activate the profile, its exact-ID
recovery capability, or any surface. Issue #71 additionally provides dormant
Applications-owned [exact-seal staged review and decisions](../../modules/programme-review.md)
under ADR 0085; its policy, role, disclosure, and recipient-acknowledgement
contracts must be honored by future surfaces. Review-side acceptance is not
accepted-item conversion or activation of this composite page/profile.

## Immutable profile manifest

`programme_operations@1` is one composite adoption profile. Every policy,
capability, destination, catalog, effect, background job, and conflict adapter
must resolve the same immutable `(profile code, profile version)` before
authority or disclosure. Adding a later capability does not silently expand
version 1.

| Kind | Exact namespaces | Contract |
| --- | --- | --- |
| Shared foundations | `audit`, `authorization`, `effects`, `events`, `identity`, `organizations`, `privacy` | Required for scope, accountability, evidence, delivery, recovery, and data rights; they do not imply adoption of another product workflow |
| Adopted products | `applications`, `programme`, `scheduling`, `venues`, `workforce` | Deliberately adopted together as the complete Programme Operations workflow |
| Excluded products | `accreditation`, `catalog`, `charities`, `communications`, `logistics`, `participation`, `registration` | Create no product record, destination, authority, Communications-owned/general notification, conflict claim, or hidden operational dependency; separately pinned purpose-specific Effects delivery remains permitted |

The profile does not adopt a general `operations` namespace. Its bounded
on-site views are projections of the approved Scheduling release, Programme
readiness, Venue approval, and current Workforce commitments. General
Communications, attendee personalization, payments, attendance, accreditation,
charity, merchandise, and broad Logistics remain outside the profile.

`programme` and `scheduling` now have installed dormant owning implementations,
including release and continuity surfaces. Neither current adoption profile
admits the Programme workflow. Profile activation is forbidden until their public commands,
queries, events, capabilities, destinations, database boundaries, and recovery
behavior exist and the whole versioned manifest passes integrated acceptance.

## Ownership and cross-module boundaries

Each module keeps one source of truth:

- **Events** owns edition identity, dates, time zone, lifecycle, and the
  immutable adoption-profile code and version.
- **Applications** owns call definitions, typed tracks/formats/contributor
  fields, private collaborative proposals, shared answer revisions,
  contributor-owned proposed-public profiles and consent, exact sealed
  revisions and included-collaborator acknowledgements. Its dormant review kernel
  also owns explicit staged policies, reviewer conflicts, moderation, decisions,
  deliberate recipient messages, and individual acknowledgements. General
  applicant-visible conversations remain later work. ADR 0086 now implements the
  dormant reciprocal accepted-target receipt. Proposal collaborators are not hosts.
- **Programme** owns the accepted Programme item, host and co-host purpose
  relationships, readiness evidence, approved public renditions, and
  organizer-created core events. It never imports private review answers as
  operational fields.
- **Scheduling** owns occurrence identity, public timing, service days,
  planning layers, candidate versions, conflict results, overrides, approval,
  immutable releases, supersession, and change impact.
- **Venues** owns reusable properties and spaces, edition selection, hard
  availability, capacity, composite-space membership, physical occupancy, and
  independent Venue approval. A Programme-linked occupancy cannot publish a
  second timetable; its current approval is an input to Scheduling approval.
  Unrelated Venue-owned bookings keep their accepted lifecycle.
- **Workforce** owns Departments, Positions, Assignments, person-owned
  Availability, Shift demand, claims, confirmations, coverage locking, and
  retained commitments. The profile adopts the complete current Workforce
  journey, not a hidden subset.
- **Audit and Effects** own minimized evidence, registered events, the
  transactional outbox, and purpose-limited delivery state. The Effects
  foundation does not create a general Communications workspace or audience.

Cross-module orchestration uses versioned public commands, minimized queries,
registered events, and opaque identifiers. It never imports another module's
private models or writes another module's tables directly. Every command
reauthorizes its own organization, edition, principal, relationship, resource,
version, and lifecycle.

## Placement and navigation

Once implemented, Platform administration may expose **Set up Programme
Operations** beside other explicit adoption actions. It must use the shared
administration shell and cannot appear as a live link, setup choice, search
result, Staff Console destination, API option, or specialist record before the
runtime profile is supported.

The guided setup reuses the highest trustworthy foundation available:

| Choice | Reused | Created after review |
| --- | --- | --- |
| Start a new organization and convention | nothing | Organization, convention series, edition, accountable Maru operators, and the first Programme Department |
| Use an existing organization | Organization and current representation when valid | convention series, edition, representation only when absent, and the first Programme Department |
| Use an existing convention series | Organization, series, and current representation | edition, representation only when absent, and the first Programme Department |

The exact setup command must be atomic, optimistic, idempotent, profile-pinned,
and fail closed. It creates no call, proposal, Programme item, occurrence,
Venue booking, Position, Assignment, Availability, Shift, Participation,
Registration, payment, attendance, notification, or public page. It creates a
minimum Department because Applications ownership, Venue edition selection,
and Workforce planning use the current Workforce-owned responsibility
boundary.

Existing truthful Executive Board representation is reused. Otherwise setup
provisions **Maru operators**, which names responsibility for this Maru
deployment rather than constitutional office. Two distinct verified people
must accept their own invitations before activation. Existing
`maru-operators@1` authority must not silently gain Applications, Programme,
Scheduling, Venue, or additional Workforce capabilities; a separately
accepted, independently approved, immutable role version is required.

[ADR 0106](../../architecture/decisions/0106-scoped-programme-operational-approval.md)
defines that continuation: an ordinary current controller proposes exact scoped
access and a named independent controller approves or declines in their own
session. Selecting an approver's email is not their decision; representation
acceptance is not approval of supplemental access. The author can cancel pending
intent; after seven days it expires without a grant. Approval must not backdate
authority or exceed either controller's current horizon.

The dormant Authorization catalog provides 27 optional task recipes, not another
root or a single all-powerful Programme role. Present their exact consequences:
Department call/review tasks, Edition Programme/planning/Workforce tasks, separately
requested Organization-wide Venue facts and exact selected-room powers. On-site
run sheets and additional delivery layers remain separate choices. The request
binds all scope identities and exact versioned contents; labels and fingerprints
never establish authority. Definitions/inputs and dormant immutable request/terminal
decision storage with native integrity/readiness are implemented. The dormant
owning request and actual-person decision commands now compose the existing
dual-control role commands atomically. Protected own-request projections and
decision controls are implemented dormant; guided request creation and foundation
continuation remain unfinished. Current profiles are unchanged. Storage alone cannot prove a
person's action or grant access.
See the [owning contract](../../modules/authorization.md#dormant-programme-operational-role-contracts).

### Scoped operational approval workspace

The reserved `/admin/programme/access/` route family is isolated-fixture-only
until final promotion. Its route carries the exact organization, Programme
edition and explicit Organization, Edition, Department or selected-room target.
The shared Administration shell labels both the Programme context and actual
grant scope. Organization-wide Venue access is explicitly broader than one
edition. Route identifiers are locators, never grants or primary task labels.

Only a current ordinary persistent controller with `authorization.manage_roles`
may read their own authored or named-approver requests in that exact scope.
Platform fallback, being the recipient, or knowing a request ID is insufficient.
The read ceiling contains independently authorized scope labels; active verified
person display labels (otherwise a neutral unavailable-person label); the exact
recipe, capabilities, interval and reason; and retained decision facts. It
excludes email/contact directories, other requests, retry keys, source audits,
controller provenance and unrelated product content. Sensitive reads, including
an authorized empty inventory, are audited before disclosure.

The inventory is the complete bounded set of up to 100 currently unexpired,
undecided requests authored by or assigned to this person in this scope. It is
not a history export. Overflow releases no partial list. Original receipt links
remain the route to exact expired or terminal requests while current authority
continues to permit them. Request detail never claims a retained approved
assignment is still effective. Every request grants nothing until its own
independent approval; representation acceptance is not that approval.

The named approver can personally approve or decline; the original author can
cancel. An expired request cannot be approved. Reason, explicit confirmation and
the original retry identity bind a submitted action. Changed intent and competing
decisions conflict; retries recover the original result, never regrant access.
Strict input and CSRF protect POSTs. Validation/conflict/dependency failures keep
safe original input and retry identity while fresh protected reads still permit
disclosure, without automatic resubmission. A loss of
authority or changed rendered source suppresses private output. Empty, expired,
terminal, denied, unavailable and overflow states explain the next safe action.

The screen uses one H1/main, the shared Access explanation, ordinary labelled
forms, keyboard-visible focus, stacked narrow cards and pending-input protection.
Synthetic component rehearsal is not native independent-approval proof or human
acceptance; #102/#92/#109 retain those gates. Foundation creation, invitation
acceptance and the guided creation of new operational requests remain subsequent
continuations, not implied by this review screen.

### Original setup intent

The dormant Events input contract distinguishes all three modes explicitly.
New-foundation setup supplies organization and series names and no reused IDs.
Existing-organization setup supplies its exact ID, a new series name and the
original Organizations source fingerprint. Existing-series setup supplies both
exact parent IDs and that fingerprint, with no rename fields. The future platform
surface must present independently authorized labels rather than asking the
operator to discover IDs. Inapplicable names/IDs, an unknown mode or a changed
original request must not silently select another foundation or retry intent.

All modes require edition and first-Department names, actual calendar dates
within Events' supported interval, an IANA time zone and a bounded setup reason.
Control characters and oversized input are rejected; canonical Unicode/spacing
normalization defines exact retry comparison. The digest includes all normalized
facts and the exact v1 Programme setup purpose. Actor and retry-key binding,
current admission, canonical owner locking, durable receipts and atomic writes
belong to Events' dormant `setup_programme_foundation` command. A source fingerprint is not a grant,
locked snapshot, invitation acceptance or profile activation.

The command denies both current profiles before database work. Its future supported
path atomically creates the selected missing foundations, retains truthful
representation, creates one edition and its first Department, and binds owner
receipts/audit to the complete setup result. Exact replay requires current platform
admission but does not repeat writes or grant access. Independently approved
operational authority, two people's own continuation, the guided surface and the
complete isolated fixture remain separate unfinished acceptance checkpoints.

On successful activation, the accepted owner sequence is:

```text
Programme structure
  -> calls and acknowledged proposal revisions
  -> preview-first import
  -> review and decisions
  -> accepted Programme items and host relationships
  -> accepted-item readiness
  -> timetable candidates and conflicts
  -> volunteer coverage
  -> independent approval and release
  -> role-specific run sheets and continuity pack
```

Each destination authorizes again and exposes only currently implemented work.
The profile must never advertise a dead end to a Programme or Scheduling route.

## Purpose accounts and personal discovery

A Programme proposal lead or collaborator is an Applications-owned purpose.
Accepted collaborators may edit shared applicant-writable answers, while the
lead alone manages selection/roster/seal/submission and each contributor alone
manages their proposed-public profile and consent. Each included collaborator
alone acknowledges or declines the exact seal and own included profile
revision; the lead's attributable seal is the lead action. Invitation,
acknowledgement, submission, or withdrawal creates no Programme host or co-host relationship.

A host or co-host receives one exact Programme-item relationship after their
own invitation and acceptance following the later accepted Programme
transition. A reviewer receives one named or immutable-role
review assignment. A volunteer uses Workforce Assignment, Availability, and
ShiftCommitment evidence. These are separate purposes even when the same
platform account holds more than one.

No relationship in this profile creates or requires `Participation`,
`ParticipationCapacity`, attendee Registration, attendance, public profile,
payment, membership, or a broader convention identity. Workforce Assignment
approval and ending must derive their null Participation-evidence rule from
the profile manifest rather than a hard-coded `workforce_only@1` exception.

Personal timetable discovery is authorized by either:

- an exact current or retained Programme host relationship; or
- the person's own retained Workforce Shift commitment.

It does not enumerate editions through Participation. A person sees only the
released Programme fields needed for their host role, their own Shift state
and briefing, and explicitly shared change information. It reveals no other
host contact, volunteer identity, Availability values, reviewer identity,
score, internal rationale, or restricted layer.

## Programme information and review layers

Applications keeps private proposal and review evidence separate from the
accepted operational item. Programme and Scheduling expose distinct layers
with independent field ceilings, ownership, history, and publication rules:

| Layer | Typical fields | Audience ceiling |
| --- | --- | --- |
| Released programme | approved title, summary, host rendition, classification, effective time, public room and access information | Public after release |
| Host readiness | confirmation, call time, approved copy, material deadlines, host-visible changes | Exact accepted hosts and responsible Programme operators |
| Technical and accessibility delivery | requirements, reviewed accommodations, cues, responsible owner, readiness evidence | Explicit responsible roles only; no unnecessary diagnoses or private proposal text |
| Venue operations | setup/effective/teardown envelope, configuration, capacity, occupancy, approved layout reference | Authorized Venue and Scheduling operators |
| Staffing | Position demand, required headcount, minimized coverage state, current version consequence | Authorized Programme planner and Workforce organizers; volunteers see only their own work |
| Department discussion | decision-focused notes, owners, blockers, and retained rationale | Exact authorized Department roles |

Changing one layer invalidates only dependent evidence. A comment, review,
technical note, or staffing change cannot silently alter approved public copy
or the active release.

## Timetable candidates and interactive editing

The timetable editor changes one Scheduling candidate, never the active
release. It combines an unscheduled-item tray, service-day and room grid,
filters, layer controls, conflict summary, candidate comparison, and a
purpose-based item inspector. Every visible placement retains explicit
preparation, effective delivery, and teardown instants in the edition time
zone.

Drag and drop may accelerate pointer use but is never the only command. The
same operation must be possible by keyboard and by an explicit form that can:

- select an item and occurrence;
- choose an exact service day, start time, and approved space;
- move before or after another occurrence using stable labels;
- change preparation or teardown without changing public timing;
- review the old and proposed envelope plus consequences; and
- cancel, retry, or submit one reasoned move without losing context.

Focus returns to the moved item or conflict summary. Status text names the item,
room, local time, result, and candidate version. Color, grid position, pointer
motion, hover, and animation are never the sole carriers of meaning. Narrow
screens provide an equivalent ordered list/card editor instead of forcing the
whole page to pan; any spatial-grid scroll region is labelled, keyboard
reachable, and not the only representation.

Conflict evaluation distinguishes hard constraints from reviewable warnings.
It explains Venue occupancy/capacity, service-day bounds, host overlap and
unavailability, explicit accessibility mismatch, current staffing coverage,
and stale source versions. A warning override requires a retained reason; hard
authorization, physical, safety, consent, and edition-boundary rules cannot be
overridden. An excluded Logistics or Communications source is reported as not
adopted and unchecked, never queried, fabricated, or described as passing.

Automatic assistance may suggest placements or explain tradeoffs. It cannot
accept a proposal, assign a room or person, dismiss a conflict, approve a
candidate, or publish a release.

## Workforce staffing and change impact

Programme records a versioned staffing requirement and calls a documented
Workforce adapter. Only Workforce commands create or mutate draft Shift demand
and commitments; Scheduling reads only minimized, authorized coverage and
version consequences.

A candidate move may update a linked draft demand through its public Workforce
command. It can never silently rewrite open or locked `ShiftDemand`, or a
claimed, confirmed, removed, or completed `ShiftCommitment`. A later change
previews affected commitments and requires the accepted cancellation,
recovery, or successor workflow. The previous public release and current
commitments remain truthful until the complete change is approved.

The last candidate modifier cannot approve it, and the approver cannot publish
it. Approval transactionally rechecks Programme readiness, source versions,
Venue approval and occupancy, host constraints, staffing consequences,
conflicts, overrides, and authority. Publication validates every required
artifact before atomically switching the active release pointer; failure keeps
the previous release wholly active.

If a required Venue approval or hard physical constraint later becomes
invalid, the Venue command and Scheduling release-invalidation command join one
transaction. They either activate an already approved safe successor or append
a reasoned invalidation that suppresses the unsafe room assignment everywhere
and exposes relocation pending. Cached, printable, and last-published degraded
views must consume the invalidation overlay and cannot continue to claim the
space is approved.

## On-site version 1 boundary

The first profile's on-site view is a projection of one approved Scheduling
release plus current confirmed or locked Workforce commitments. It supports:

- personal, host, volunteer, Department, room, and Programme run sheets;
- current and next released occurrence, reporting time, location, briefing,
  approved operational layer, and source age;
- staffing gaps and stale coverage for authorized organizers;
- released change impact and exact-version acknowledgement; and
- a version-stamped printable pack and last-published degraded snapshot, both
  superseded immediately by any known withdrawal or relocation-pending
  invalidation overlay.

It does not implement or imply check-in, lateness, absence, Shift actual time,
correction or dispute, Shift handover, payroll, surveillance, live dispatch,
or life-safety command. Issue #24 owns the stable contract for those Workforce
facts. A Programme run-sheet note or acknowledgement cannot masquerade as
attendance or handover evidence.

## Reusable Venues and profile scope

Reusable Venue properties are organization-scoped and may legitimately serve
several editions with different profiles. Organization authority to maintain
that catalog is therefore not manufactured or revoked by this exact-edition
profile. Programme Operations setup and policy still expose only the catalog
actions for which the actor has current organization authority.

Selecting a property or space for the edition is a separate, edition-scoped,
profile-authorized command. It snapshots the current approved physical facts
needed by the edition and creates no Programme occurrence. Programme-linked
occupancy remains Venue-owned and approved, but only the Scheduling release is
public timetable truth.

## Coexistence, continuity, and stop-use

Incumbent Registration, payment, attendance, accreditation, Logistics,
Communications, website, and attendee-personalization systems remain
authoritative for their excluded purposes. Import is preview-first, validates
scope and provenance, and writes only through the same current commands.

The profile must provide versioned public and authorized exports, iCalendar,
room/day/host/volunteer print layouts, a continuity manifest, and deterministic
regeneration from the active release. When general Communications is absent,
only the exact version-pinned Effects handlers may deliver a Programme
invitation, decision, or released change. Every other change produces a
reviewed manual communication package and records no false delivery claim;
neither path creates Communications-owned campaigns, audiences, workspace, or
message history.

Stop-use disables new work and access predictably while retaining required
history under policy. There is no destructive self-service uninstall and no
mutable profile checkbox. Recovery fixes forward or restores a mutually
consistent whole database; a printable or last-published snapshot is degraded
operation, not an alternate writable source of truth. Known Venue or release
invalidation revokes the ordinary snapshot and requires a versioned withdrawn
or relocation-pending overlay before degraded display.

## States and safe failure

- **Dormant components:** Applications, Programme and Scheduling owner commands,
  review/conversion, connected reserved task routes and continuity components
  exist. Neither current profile admits the complete workflow; production
  mounting, accountable setup and final promotion remain gated. A reserved
  route exercised in a synthetic fixture is not an activated destination.
  No current-profile writer/effect route is enabled by these dormant components.
- **Empty setup:** explain the composite boundary, excluded modules, and
  existing-authority requirements before collecting foundation facts.
- **Existing foundation:** show only authorized reusable organizations,
  series, representations, and Venue catalog consequences.
- **Accountability pending:** continue to Representation & access without
  creating product work.
- **Configuration incomplete:** name the next adopted task without advertising
  an unavailable destination.
- **Draft and conflict:** preserve the candidate and explain stale sources,
  hard constraints, warnings, and recovery actions.
- **Approval or publication failure:** retain the previous active release and
  every immutable candidate and decision record.
- **Degraded:** show source age, release version, sync state, and the printable
  fallback; disable unavailable writes.
- **Denied:** disclose no tenant, edition, person, proposal, venue, staffing,
  or schedule existence.
- **Overflow:** fail closed with no partial conflict, coverage, or impact
  projection.

## Accessibility and responsive acceptance

Every surface uses one `h1` and the host's one `main`, semantic sections,
associated labels and errors, visible focus, announced status and conflicts,
edition-time-zone labels, touch-sized controls, reduced-motion behavior, and no
page-level horizontal overflow. High-volume planning remains usable at 200
percent zoom and at 320, 390, 768, 958, 1,024, 1,280, and 1,920 CSS pixels.

Acceptance covers pointer, keyboard-only, touch, and representative screen-
reader journeys across empty, populated, validation, stale, hard-conflict,
warning, denied, dependency-failure, read-only, approval, publication,
degraded, and recovery states. Automated accessibility checks are necessary
evidence, not a substitute for representative assistive-technology and owner
review.

## Verification and non-goals

The contract is complete only when documentation-policy assertions protect the
profile code, exact included and excluded namespaces, ownership links,
Participation prohibition, inactive route, and issue #24 boundary. Warning-
fatal Sphinx/AutoAPI, requirement and ADR validation, link checking, and the
protected pull-request gate remain authoritative for this documentation slice.

Runtime successors require focused unit, PostgreSQL, API, frontend, browser,
accessibility, concurrency, migration, recovery, and complete synthetic
setup-to-on-site acceptance. Passing this contract or either dormant domain
child does not activate the profile, expose a usable Programme workflow,
approve production data, or certify
deployment, owner acceptance, recovery, or production readiness.

The [integrated rehearsal protocol](../../operations/programme-integrated-rehearsal.md)
maps preparation, native, recovery, human and joined evidence to #108/#102/#97/#92/#109.
Its checkpoint list is not an executable fixture or evidence that a gate passed.
