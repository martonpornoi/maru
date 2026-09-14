# My Programme proposals

- Status: Accepted dormant #108 personal-intake contract; no production mounting
- Routes: `/my/applications/programme/<organization>/<edition>/`, `calls/`,
  `calls/<call>/start/` and `<proposal>/`
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
does not replace the rest of #108. Shared-answer editing, selection changes,
profile revisions, invitations/responses, roster management, exact seals and
acknowledgements, reopen/submission/withdrawal, review and conversion remain
separately unfinished tasks. Do not render executable-looking links for them or
describe a created Draft as a completed proposal journey.

## Ownership and disclosure

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

Reject query parameters, files, unknown/multi-valued/oversized POST fields and
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
