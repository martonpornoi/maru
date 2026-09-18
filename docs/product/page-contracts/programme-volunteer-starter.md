# Request and approve the Volunteer starter

- Status: Implemented dormant surface; native and human acceptance deferred.
- Owner: Workforce; #175 inside #108/#48.
- Requirements: HR-012, IDN-012, IDN-014, AUD-001, NFR-013, UX-005 through
  UX-008, UX-019, UX-020, UX-027 and UX-029.
- Decision: ADR 0107; no production profile or route activation.
- Dormant route family:
  `/admin/programme/volunteer-starter/<organization>/<series>/<edition>/`;
  `new/` previews/requests, `<request>/` reviews one original intent.

## Purpose, audience and authority

An ordinary verified accountable controller can prepare the single immutable
Volunteer template needed before creating Positions. Both author and named
approver need current Organization role-management and exact-Edition structure
authority backed by real source control. Neither a platform session, selected
context, visible link nor emailed name is another person's approval.

Explain the Organization-wide reusable definition separately from the exact
Programme edition motivating its creation: `workforce-volunteer@1`, limited
basic event/Workforce visibility, volunteer capacity and default headcount one.
Publication grants nobody access and creates no Position, assignment, Shift,
Participation, Registration, payment, attendance or unrelated communication.
Later Position and staffing tasks authorize independently.

## Creation and review

The creation form accepts one known approver address and bounded administrative
reason. Fresh preview resolves exactly one different person, displays the fixed
meaning and signs the original selected UUID, author, route scope, rationale and
retry key. Confirmation verifies that original selection without re-resolving a
mutable address; it creates only a request with a seven-day deadline.

The bounded inventory contains only this actor's authored or assigned, pending,
unexpired requests, complete or unavailable above 100. An exact known link may
show expired or terminal history. There is no directory, search across tenants,
arbitrary capability picker or general history export. Person labels are current
active verified display names or neutral unavailable-person text; no email,
credentials, availability, qualification or unrelated private content is shown.

The named approver submits their own approve/decline; the author may cancel, never
approve. Show both original rationale and the deciding person's separate reason.
Require deliberate confirmation and recent own-session authentication for a
decision. Expired or closed-planning intent cannot approve; permitted cancellation
or decline remains separate. Every command reauthorizes under locks. Terminal
history shows exact approved output or no output, not current effective authority.

## States, failure and recovery

Empty inventory explains how to request the starter and how another named person
reviews it. Creation is unavailable outside Draft/Preparing. Existing compatible
meaning may be reused only through the same own approval; conflicting reserved
meaning is never overwritten. Denial and unknown/foreign request return the same
non-disclosing response. Overflow or readiness failure shows no partial content.

Malformed, duplicate, oversized, file-bearing or unrelated input is rejected.
Invalid fields retain original bounded input and retry key. Signature mismatch
requires deliberate new preview, never silently selecting somebody else. Database
uncertainty retains the exact original input; do not auto-resubmit or start a new
request/decision. Exact retry recovers the original outcome; changed intent
conflicts. A stale render is discarded after fresh owner authorization/query.

## Placement and presentation

Use the existing administration shell, one H1 and one main landmark. The creation
entry belongs beside Positions and the accountable setup continuation, not a new
top-level workspace. Expose links only when the real dormant route is joined and
the current actor is eligible; every destination checks again. Current production
URLs/profiles remain unchanged. No dead links or platform operational shortcut.

Use ordinary labels, fieldsets, buttons, text consequences, visible focus and
error summaries. Forms remain usable on narrow widths and at 200% zoom, with no
page overflow or animation-dependent behavior. Preserve keyboard focus and original
input after errors. Sensitive pages are private/no-store with CSP, CSRF protection
and revalidated post-render disclosure. Step-up must not silently discard or
replace a pending decision identity.

## Acceptance

Cover actual actor/scope/field ceiling, complete inventory/overflow, named-person
binding under email change, malformed proof, expiry, original retries, native
command failure, post-render revocation/label change and route/profile dormancy.
Maintain native cases without collecting/running them while #102 is deferred.
Record real-browser and genuine-human comprehension separately under #92; no mock
or synthetic role switch can stand in for that acceptance. Connect the actual
two-controller command journey to blank setup and P06 before closing #175.
