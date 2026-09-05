# Programme calls and acknowledged proposals contract

- Status: Dormant domain contract; no mounted route, API, template, navigation,
  or Django admin writer
- Route: none reserved by issue #63
- Requirements: IDN-014, PRG-001, PRG-002, PRG-006, PRG-008, PRG-009,
  PRG-011,
  AUD-001, AUD-003, AUD-005, PRI-001, UX-005 through UX-008, UX-019,
  UX-020, UX-027, UX-029, NFR-002, NFR-003, NFR-008 through NFR-010, and
  NFR-013
- Decisions: ADRs 0041, 0051, 0081, 0082, and 0084

## Purpose and current boundary

Let a Programme Department define a call and let one proposal lead collaborate
with invited contributors on one exact, attributable proposal revision. The
human outcome is a fully acknowledged submission that a later Applications
review workflow can assess without reconstructing mutable current answers.

Issue #63 installs only the Applications command/query and database kernel.
This contract does not name a canonical URL because no route is mounted or
reserved. It adds no API operation, serializer, OpenAPI component, template,
navigation destination, search result, dashboard card, Django admin writer,
job, worker, effect handler, notification, or delivery. The current
`full_convention@1` and `workforce_only@1` manifests omit the capabilities,
purpose, target, and event declarations and retain their exact fingerprints.

No page or generic Applications route may expose the dormant rows. Every
legacy starter, definition, submission, answer, review, decision, acceptance,
target, and target-result seam denies or omits the `programme_item` kind. A
future mounted surface requires a separate accepted page/API contract and an
exact adopted profile member.

## Roles and purposes

- **Call editor:** `applications.manage_programme_calls` through exact current
  Department authority within the edition, with no hierarchy inheritance; no
  proposal answer or contributor-profile authority follows.
- **Source and destination call editors:** both exact current Departments must
  authorize a normal Draft-call reassignment; neither hierarchy ancestry nor
  edition-wide visibility substitutes for either decision.
- **Recovery operator:** a future separately activated, nondelegable,
  break-glass exact-Edition purpose may act on one caller-supplied orphan call
  identifier only; it receives no list, search, proposal, or content read.
- **Proposal lead:** accountable author of one proposal; owns selection,
  included roster, seal, reopen, submission, and withdrawal.
- **Invited collaborator:** may inspect and respond to their own invitation;
  expiry is derived and cannot be accepted after its deadline.
- **Accepted collaborator:** may edit shared applicant-writable answers and
  append their own proposed-public profile and consent revisions.
- **Included collaborator:** acknowledges or declines only the exact sealed
  revision and exact own profile revision included for them.

One active, verified person may hold more than one purpose, but each command
checks the relevant relationship separately. None of these purposes creates or
requires Participation, Registration, payment, attendance, Workforce,
membership, review authority, host status, Programme access, or public profile.
Proposal collaborator labels must never be rendered as host or co-host.

## Call experience

A future call editor starts from one Applications definition targeted to
`programme_item` and configures exactly one current-edition Department owner,
tracks, formats, contributor fields, questions, eligibility, deadlines,
content/consent policies, and retention policy. The interaction must:

- distinguish draft, domain-active, retired, and successor states;
- explain that activation makes content immutable but does not publish or make
  the call discoverable;
- preserve stable row ordering and names without using color or drag motion as
  the only meaning;
- provide equivalent keyboard and explicit-form reorder/edit operations; and
- preview the complete immutable successor rather than editing an active call.

Call ownership is a separate explicit action, not a configuration field. A
Draft may be reassigned with exact source/destination authority, expected
version, retry key, and reason. An Active call must retire before its owner
Department; it cannot be reassigned. A valid imported-call reassignment keeps
the permanent source binding unchanged and appends a contiguous owner-
transition receipt. Proposal self/history access survives a later Department
retirement, but organizer management, discovery, and new proposal starts
require a current owner.

Active and retired content is read-only. A stale expected definition or call
version retains entered data locally, names no foreign object, and offers a
safe reload/reconcile path.

## Proposal experience

The future proposal surface must keep one visible aggregate version across
every action. It separates four task regions without exposing hidden fields:

1. **Selection and roster:** lead-only track, format, and included-contributor
   choices with current invitation consequence.
2. **Shared answers:** only applicant-writable questions visible to the current
   lead or accepted collaborator; source-owned and conditionally inapplicable
   fields remain closed.
3. **My proposed public profile:** only the current contributor's display name,
   biography, pronouns, website, and consent, clearly labelled private input
   pending later review rather than public content.
4. **Seal and responses:** exact revision identifier/digest, summarized included
   facts without over-disclosure, each person's own response, aggregate
   acknowledgement status for the lead, and explicit reopen/submit consequence.

The UI must not load all contributor profiles and filter them in the browser.
It requests a relationship- and field-bounded projection after authorization,
reauthorizes before release, and audits a protected read where required. The
lead may see who is included and whether each required response is pending,
acknowledged, or declined; they do not gain another person's private profile
history, invitation delivery data, or response rationale.

## States and transitions

```text
draft edits
  -> sealed exact revision
      -> collaborator acknowledgements or decline
          -> lead submission

sealed or submitted -> explicit reopen -> draft -> new seal
draft, sealed, or submitted -> lead withdrawal
```

Sealed state blocks answer, selection, roster, profile, and invitation changes.
A response advances the submission aggregate version but does not mutate the
seal. Any content change requires reopen and therefore a new exact revision.
Expired invitations do not block seal, while unresolved unexpired invitations
do. Invitation and reinvitation expiry may equal, but cannot follow, the
inclusive applicant edit deadline. A decline blocks submission until the lead
explicitly reopens and changes the proposal or roster.

The submit confirmation identifies the exact revision and acknowledges that it
creates Applications submission evidence only. It cannot promise review,
acceptance, a Programme item, host relationship, public copy, timing, room,
staffing, or publication.

## Safe failure and disclosure

- **Dormant:** every attempted route or generic discriminator path is absent or
  denied before loading call/proposal values.
- **Empty:** explain the task and next action without exposing another call,
  Department, proposal, person, or count.
- **Invited:** show only the current person's invitation, purpose, expiry, and
  accept/decline actions; never enumerate other invitees.
- **Expired:** acceptance is unavailable; explain that the lead may reinvite.
- **Stale:** apply nothing, retain local input safely, and identify only the
  caller-visible aggregate/version conflict.
- **Sealed:** every content control is read-only and names the explicit reopen
  consequence.
- **Declined:** block submit without copying another person's profile or private
  reason.
- **Denied or unavailable:** use one non-disclosing shape for absent, foreign-
  tenant, foreign-edition, unrelated, inactive-account, and unauthorized rows.
- **Dependency or evidence failure:** commit no state, receipt, allow audit,
  event, or outbox artifact; show a retry-safe correlation reference only.
- **Orphan recovery:** accept one exact opaque call ID only, disclose no other
  call or Department facts, and collapse missing, foreign, non-orphan, and
  lifecycle-incompatible targets into the same safe refusal.
- **Overflow:** fail closed before partial roster, answer, snapshot, or
  acknowledgement projection.

## Accessibility and responsive acceptance

Future surfaces use the shared shell and one semantic `main`/`h1`, associated
labels and errors, visible focus, announced status, meaningful headings, and
touch-sized controls. Track/format/roster ordering and acknowledgement state
must be understandable without color, icons, hover, or pointer motion. Every
action is keyboard-complete and retains focus at the changed row or status.

At 200 percent zoom and 320, 390, 768, 958, 1,024, 1,280, and 1,920 CSS pixels,
the proposal uses ordered sections/cards rather than page-level horizontal
scroll. Long biographies, labels, validation summaries, and contributor names
wrap without hiding actions. Acceptance includes keyboard-only, touch, and
representative screen-reader journeys through dormant, empty, invite,
expired, draft, stale, sealed, pending, declined, submitted, withdrawn, denied,
overflow, and dependency-failure states.

## Evidence and non-goals

Every successful future mutation must atomically retain the exact aggregate
version, dedicated Programme receipt/proof, minimized allow audit, dormant
event, and outbox record. The page never renders receipt internals, raw audit,
answers/profile values in timeline metadata, or an idempotency key.

This contract includes no mounted acceptance evidence yet. Preview-first import
and Programme Department ownership continuity are installed as dormant service
contracts. Structured review and decisions, the accepted
Programme adapter, Programme items, host/co-host relationships, reviewed public
copy, readiness, Scheduling, Venues, staffing, timetable publication, and
on-site use remain outside this contract. No recovery route, job, UI, current-
profile capability, or platform-root shortcut exists.
