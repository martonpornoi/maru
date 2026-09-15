# My Programme proposals

- Status: Implemented dormant #108 personal workflow; no production mounting
- Routes: `/my/applications/programme/<organization>/<edition>/`, `calls/`,
  `calls/<call>/start/`, `<proposal>/` and `<proposal>/work/`
- Requirements: IDN-014, PRG-001, PRG-002, PRG-008, PRG-009, PRG-011,
  AUD-001, AUD-003, PRI-001, UX-005 through UX-008, UX-019, UX-020,
  UX-027, UX-029 and NFR-013
- Decisions: ADRs 0051, 0081, 0082, 0084 and 0100

## Outcome and increment boundary

A verified person can find an available call, deliberately start their own private
proposal with labelled track/format/duration and their own proposed-public profile,
then return to their personal inventory and exact proposal overview. This is
Applications intake, not submission, acceptance, hosting or publication.

This companion to the [proposal domain contract](programme-calls-and-acknowledged-proposals.md)
does not replace the rest of #108. Intake and the explicit editing/collaboration
continuation use dedicated dormant adapters and the existing owner commands.
Review/conversion and authorized typed reference/file selection remain separate
unfinished connections. Do not describe a created Draft as a completed journey.

## Accepted personal continuation

Under `<proposal>/work/`, explicit tasks are `selection/`, `profile/`,
`answer/<question>/`, `invite/`, `reinvite/`, `remove/<collaborator>/`,
`accept-invitation/`, `decline-invitation/`, `leave/`, `seal/`, `reopen/`,
`frozen/`, `acknowledge/`, `decline-revision/`, `submit/` and `withdraw/`.
Question and collaborator relationship selections originate in authorized labelled
cards, not raw identifier entry. Each POST confirms one command; a GET never writes.
Submission binds the explicitly displayed seal ID. Collaborator responses bind
that seal, their exact included contributor identity and their frozen profile ID.
Already-recorded current responses are not offered as new decisions. Existing
immutable response history remains visible within its independent field ceiling.

Use separate exact-proposal tasks for selection, shared answers, own profile,
invitation/roster changes, seal, exact revision acknowledgement/decline, reopen,
submit and withdrawal. Each destination proves its own existing owner capability;
navigation and an advertised action are not authorization. Preserve current
profiles, owner writers, schema and dormant production routing.

Two explicit non-persisted self-view field ceilings supplement the original
fields: `workflow_context` and `frozen_revision`. They are code-owned fields,
not new grants or a broader directory. The former discloses only the current
proposal identity/version, call status/schema/version and opening/edit/submission
deadlines, private-planning availability and role-appropriate task choices.
Only leads receive the complete bounded track/format catalog and collaborator
limit. Invitees may see their task's window context but no shared answers,
roster, profile or frozen content. Existing proposal context never invokes new-
call availability, submission allowance or current Department membership.

The latter requires a current lead/accepted-collaborator relationship and the
actor's inclusion in the selected current immutable seal. Show exact sealed
revision identity/digest, frozen selection and shared applicant answer revisions,
plus only the actor's included frozen profile and its exact revision identity.
Never substitute latest mutable values. Scope the profile query to the actor
before loading values; another contributor's private profile is not disclosed.
Acknowledgement binds the reviewed revision and the subject's frozen profile;
it does not assert that they inspected other people's private profile fields.
Required protected-read audit and bounded complete results apply. Compare the
proposal relationship/state/sole version and source call version/lifecycle
before and after building context and before/after rendering; discard stale
prepared output rather than leaking a partial response.

Editing requires Draft state and the active inclusive edit window. Reopening is
an explicit lead action on a sealed/submitted proposal within that window, not a
side effect of visiting an editor. Invitation responses also require an unexpired
own invitation. Acknowledgement and submission use the exclusive submission
close, which can be later than the edit deadline. Withdrawal remains a separate
lead action on Draft/sealed/submitted states with private planning, without a
current call/edit-window requirement. Commands remain final locked authorities.

Keep original aggregate cursors, retry identity, reason and confirmation on every
task. Never replace a stale bound cursor with the latest version. A lost-response
message directs to independently authorized own history; it does not promise that
the earlier mutation failed. Leaving/declining/removal can end access, so navigate
to the independently authorized personal inventory rather than reread lost detail.

Profile revision collects only the subject's role-visible fields and requires a
fresh deliberate publication/consent decision. Show retained own values but never
preselect consent for a new revision or silently clear them. Shared answers use
the existing typed owner normalizer and current applicability; ordinary choices
have labels and an explicit blank selection. Integers enforce both signed-32-bit
shape and inclusive configured numeric bounds. Retained invalid numeric answers
must be corrected through a new revision before a new seal; do not rewrite history
or retrospectively invalidate an already immutable seal merely by rendering it.
Use labelled structured address inputs and explicitly offset-aware instants;
never silently interpret an unzoned instant as server-local time. Required answers
may remain blank while drafting but block sealing. The separate
[Programme person-reference task](programme-person-references.md) supplies known-person
selection, deliberate clearing and current/exact-seal viewers for the registered
`person_reference` / `programme.person` pair. It creates no collaboration or host
relationship. The [same-call domain task](programme-domain-references.md) supplies
complete labelled track/format choices for registered extra private answers, with
original-target confirmation and exact current/sealed viewers; it never changes
the lead-owned selection. Safe-file and unknown-kind tasks still require authorized
owner choices: raw UUID input is not a substitute. Until their boundary exists,
show an honest unavailable explanation instead of an unsafe editor.

Invitation and reinvitation take a deliberately entered exact known login email
and explicit expiry, not a browsable account directory. Display labelled existing
relationships for removal, retain expired-invitation explanation for the lead,
and never infer acceptance, hosting, notification or delivery. Exact confirmation
precedes each roster mutation, sealing, acknowledgement, submission or withdrawal.

## Ownership and disclosure

Same-edition fixed-label connections lead to independently admitted own hosting
and personal timetable tasks. They use the actual viewer and current mounted
routes, not a selected collaborator, staff context or Participation. Navigation
loads no relationships, names, proposal content, work or timetable data and creates
no new purpose. Missing, denied, unavailable or shadowed optional destinations
are omitted. Recheck after rendering; on movement rerender without the optional
connections and repeat the original source authorization before releasing bytes.
Do not repeat a command or replace original bound values/cursors to recover links.
This is not cross-edition discovery or profile activation.

Use the shared personal shell, not staff membership or a second account portal.
Applications owns every projection and the existing `start_programme_proposal`
command. No direct model save, new writer, schema, current-profile member, generic
Applications discriminator, production URL mount or notification is introduced.

Separate the inventory from available-new-call discovery: existing relationship
access survives owner Department retirement and does not depend on the availability
window or remaining new-submission allowance. Both destinations authorize exact
person/organization/edition independently; no organizer capability is substituted.
Use bounded complete owner projections and required protected-read audit.

The inventory uses only `proposal_summary`, `selection` and `own_invitation`.
Its labelled links distinguish role, selection and exact retained proposal reference;
people select a card rather than find/paste identifiers. The detail first proves
that same minimal ceiling. Only a proven lead or accepted collaborator may request
the additional `contributor_profiles` field for **their own** configured values.
Invitees get no other profiles, shared answers or roster. Never request a full
projection and filter it client-side. Compare summary scope, relationship, state
and sole aggregate version with fresh authorization before and after rendering;
discard the complete prepared response on change. Expired/removed/foreign/unrelated
relationships share the same unavailable response. Expired-invite explanation is
retained for a later lead roster task, not a new expired-self access grant.

Available calls use the existing exact-self query and show call name, stable code,
immutable schema version, purpose, description, classification, policy identity,
track/format guidance and explicit UTC deadlines. UTC-labelled instants are not
editable local-time inputs. Starting requires separate exact-self edit authority
and open private planning. Recheck selected availability before rendering and let
the existing command recheck its canonical locked availability/owner boundary.

## Draft creation

Track and format are closed labelled choices from the selected call; show stable
codes to disambiguate equal labels. Duration is a positive whole number within
that format's stated bounds. Do not guess a duration or silently change another
selection. Initial proposal version is zero. Bind the displayed immutable call
schema and call aggregate version so a changed source cannot reinterpret input.

Only configured, lead-visible public-name/biography/pronouns/website fields are
collected. Their required-before-sealing policy is explained without requiring
publication consent merely to save a private draft. The person explicitly chooses
whether to propose populated values for later publication; no choice or consent
is preselected. Declining publication requires values to be deliberately blank,
not silently erased. The exact policy code is visible; this page does not invent
policy text or claim that a policy was supplied/read. Acknowledgement means the
person confirms having reviewed the organizer-supplied policy identified here.
If unavailable, they may save a blank, non-public draft and request that policy.
The typed owner input remains authoritative for normalization and consent rules.

Explain that the values remain private proposal input pending later review. A
short retained reason and explicit confirmation accompany the existing command;
avoid unnecessary private explanations. Keep original retry key and version fields
across invalid/stale responses. A successful command redirects to independently
authorized personal detail, never a manager page. If the response was lost or the
call is no longer available, guide to the personal inventory: an earlier attempt
may have committed. Do not manufacture a retry-authority lookup from submitted IDs.

## Interaction, failure and evidence

One H1 and the shared main landmark, ordinary labelled forms/cards, wrapping long
content, visible focus, error/status announcement and existing pending-input guard
support non-pointer use. No page-level horizontal scrolling, custom modal or new
animation is required. Links authorize again; context is not a grant.

Reject query parameters, files, unknown/oversized POST fields, scalar duplicates and
invalid route/task combinations. Keep login, CSRF, no-store, same-origin forms,
strict response headers and sensitive-POST redaction. Denial discloses no prepared
names or partial counts. Invalid input is 400; a visible original-source/version
conflict is 409 with retained bound input; missing/foreign/lost authority is a
generic 404; dependency/audit/overflow failure is 503 without partial content.
An empty list states only that no entries are currently available to this person.
Closed planning shows no creation link/form, but preserves authorized history.

Tests cover typed normalization, choice provenance, no implicit consent, exact
actor/cursors, scope/role ceilings, retirement-independent history, request fences,
changed-authority suppression, lost-response guidance and generic containment.
Maintain native owner cases under #102 without collection/execution during ADR 0100.
Synthetic browser evidence must distinguish real forms/assets from stubbed authority
and non-persisting commands. Genuine widths, 200% zoom, keyboard, screen-reader,
reduced-motion and user-comprehension acceptance remain explicitly tracked in #92.
No component result completes #108/#48 or authorizes a director pilot.

Only an authorized multiple-choice answer accepts multiple `value` entries;
all proof and scalar fields remain single-valued. The transport caps any value at
65,536 characters and a repeated choice at 100 values; typed configured owner
bounds remain final. Invalid or no-longer-applicable selected questions are denied
without substituting another question. Incomplete sealing/submission is an
actionable 400, not an unhandled server error. Commands returning answer, profile,
transition or revision IDs redirect using the original proposal, never those IDs.

See the [personal workflow checkpoint](../../checkpoints/2026-09-14-programme-personal-workflow.md)
for database-free and synthetic-browser evidence and its explicit limits.
