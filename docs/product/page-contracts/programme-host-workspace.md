# Programme host workspace

- Status: In development within #108; dormant components, not profile activation.
- Requirements: PRG-005, PRG-006, PRG-008, IDN-014, UX-013, UX-029, NFR-013.
- Decision: ADR 0087; retain ADR 0100's deferred native execution.
- Owner: Programme, using documented Identity and Events references.
- Reserved organizer route: `/admin/programme/hosts/<organization>/<edition>/<item>/`.
- Reserved personal route: `/my/programme/hosting/<organization>/<edition>/`.

## Outcome and boundaries

An organizer explicitly invites a known active verified person for one item,
using deliberate host-visible invitation title and briefing. The person chooses
whether to confirm or decline and controls purpose-owned availability. An
organizer may reinvite an ended relationship or remove current hosting with a
retained reason; they never confirm on the person's behalf. No proposal
collaborator, volunteer, attendee or previous confirmation is silently reused.

Invitation creation is an in-app owner command, not proof of email delivery.
The exact-address invitation seam returns an identifier or a uniform unusable
result, not contact details or a searchable directory. No account is created.
Reinvitation selects an existing labelled roster relationship and requires new
deliberate invitation copy and a fresh response. Private working prose is not
copied into host-visible fields.

Fresh invitations use a separate preview/confirmation step. Under current
independent manager and private-item/roster authority, resolve the exact address
once and pin that person with a purpose-signed original-intent proof. The proof
binds actor, tenant, item, person, original item version/retry, role, deliberate
title/briefing, rationale and selector text; it contains only an identifier and
digest, not the address or private text. Preview records no invitation. Explicit
confirmation verifies the proof without looking up the address again. Changing
the person selection or other intent requires deliberate re-preview, not silent
retargeting. Reinvitation continues to select the exact retained relationship.

Original confirmed invitation POST reaches the unchanged owner command after
current actor/tenant/adoption admission, before fresh manager, private roster or
recipient reads. The owner independently enforces fresh admission and current
person state when there is no receipt. A minimal original result is not current
hosting state, email delivery, recipient confirmation or permission to read the
roster. Offer a roster continuation only under its separate current read grants;
losing that optional continuation must not hide an admitted receipt.

Keep proof, selector, version, retry and entered copy after uncertainty. No
arbitrary proof expiry is introduced; the existing signing-key fallback policy
applies. Missing/invalid proof cannot reconstruct an old target from a mutable
email or bypass canonical idempotency. Explain that no success is established and
require fresh selection authority for deliberate re-preview; do not replace the
retry automatically. Legacy unconfirmed forms without proof require inspection
of retained history before a new intent, not a fabricated old receipt.

## Organizer scope

The shared Administration shell uses a separately authorized working title and
complete roster. `programme.view_hosts` and `host_roster` are independent from
private item reads and `programme.manage_hosts`. The latter governs invitations,
reinvitation and reasoned removal during open private planning. History additionally
requires `host_history`; shared availability additionally requires
`shared_host_availability`. Load only explicitly selected layers. Current related
display labels are not historical identity snapshots or contact information.

Roster and history retain owner limits and completeness checks. Show unknown,
not-shared, ended, inactive, outside-edition and explicitly unavailable states
truthfully; a private draft is not shown to organizers and absence is not free
time. No exact historical availability periods are introduced.

## Personal scope

Use the shared My Maru shell without querying private item, roster, discussion,
reviewer, delivery or organizer-rationale layers. Discovery lists only the exact
authenticated person's retained invitation purposes, with deliberate invitation
copy and current relationship state. It does not enumerate people or discover
editions through Participation. Every selected item rechecks its own relationship.
Use truthful host-task audit attribution rather than labelling a response page as
a timetable export. Existing timetable callers retain their current contract.

The person alone may confirm/decline the exact current invitation, withdraw
confirmed hosting and save/share/withdraw availability for that exact purpose.
Routine self actions have code-owned reasons; do not demand a private explanation.
Ending history is not active work. Approved public copy is visible only to a
currently confirmed host and never falls back after withdrawal.

Availability is a complete replacement, capped at 128 positive, non-overlapping,
whole-minute periods within the Events-owned edition envelope. Native date/time
controls show the edition zone explicitly and reject nonexistent or ambiguous
local minutes. Preserve the displayed edition version so a zone/date change
cannot silently reinterpret a stale browser form. Owner commands still normalize
UTC, recheck the current envelope and serialize writes. Shared empty periods mean
explicitly unavailable, not unknown. A separate explicit withdrawal action carries
no periods; it must not require the person to manually delete existing rows.
No silent copying from Workforce or another item is permitted.

Privacy exits retain their owner lifecycle rules after private planning closes;
they do not reopen invitations, confirmation or availability editing. The owner
still applies exact item/relationship state, history-reserve and current-person
constraints. No screen bypasses those commands or fabricates success.

## Interaction and acceptance

Use labelled roster cards, ordinary links, explicit forms and one H1/main.
High-impact removal and withdrawal explain consequences and require deliberate
confirmation. Versions, invitation sequence and retry keys are hidden immutable
intent references, not user-entered UUID tasks or authority. Reject extra/duplicate
fields, files, forged targets and oversized formsets before owner calls.

Keep source versions and entered values after validation or conflict; never
replace a stale version automatically. Reauthorize before retaining private input.
Bounded unavailable responses disclose no partial roster or person information.
Preserve error focus, no-store/CSP, escaping and pending-input protection. Person
and organizer destinations independently authorize any navigation continuation.

Database-free tests exercise the real adapters/forms and independent seams; native
command/tenant/audit cases are maintained under #102 without execution. Synthetic
browser fixtures substitute owners and do not certify persisted writes. Full
viewport, genuine zoom, keyboard, screen-reader and native discard acceptance
stays explicitly under #92. No production routes or current profiles are enabled.
