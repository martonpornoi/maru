# My Programme decisions and receipts

Status: dormant guided #108 adapter; not mounted by either current profile.
Owner: Applications. Requirements: PRG-004, PRG-006, PRG-009, AUD-001,
QRY-005 through QRY-008, UX-005 through UX-008 and UX-029.
Authority: [ADR 0085](../../architecture/decisions/0085-exact-revision-programme-review-and-decisions.md)
and the [review module](../../modules/programme-review.md).

## Audience, task and source

An exact included contributor reads their addressed immutable decisions and
deliberately acknowledges their own required receipt. The canonical personal
route is `/my/applications/programme/{organization_id}/{edition_id}/decisions/`;
`{decision_id}/` opens an exact message and its receipt form. The independent
query authorizes the current person and exact edition before a label-bearing
read. No raw UUID entry or current proposal membership is required.

The bounded chronological history uses the owner query's exclusive opaque
cursor. Detail uses a dedicated exact-recipient getter, not unbounded scanning.
Only outcome, canonical message, decision date/version, current case version
and the caller's own acknowledgement state/time are projected. No staff
rationale, reviewer identity, score, other recipient or response is exposed.
The message is historical: acceptance here is not proof of currently effective
review, conversion, hosting consent, publication or a timetable slot.

## Separate authority and command proof

`applications.view_programme_decision_self` independently admits the exact
`decision_message` and `own_acknowledgement` field ceiling. This is not proposal,
call, manager, reviewer, hosting or general self-history permission.
`applications.acknowledge_programme_decision_self` separately admits mutation.
Reads and own receipt remain available after withdrawal, collaborator removal,
owner Department retirement or private-planning closure under the owner contract.
The surface never imports proposal editing or call deadline restrictions.

The closed POST confirms receipt of the route's exact decision, retains a
canonical retry key and original current-case version, and calls only
`apply_programme_review_command` with `ACKNOWLEDGED`. The exact case and
decision IDs come from the authorized projection. No principal, Department,
action, subject, message or outcome override is accepted. No unnecessary
private explanation is collected; the personal owner command receives a blank
reason. There is no automatic acknowledgement on GET or page opening.

Receipt means only that this person received this message, not agreement or
consent. The form appears only for an unacknowledged required receipt with
separate mutation authority. An exact retry still reaches the canonical writer
and its retained replay logic; the view does not substitute newer version proof.

## States, navigation and disclosure

- Empty: no addressed decisions available to this person in this edition.
- Populated: chronological labelled outcome/date links and explicit own status;
  a next-page link only when the owner returns a cursor.
- Detail: escaped multiline exact message, date, historical-decision warning,
  required/not-requested/received status and an independently admitted form.
- Read-only: the message remains readable when mutation is not authorized,
  not required or already recorded. No disabled action suggests another grant.
- Validation: HTTP 400, visible linked field errors, retained retry/version and
  confirmation values. Duplicate/foreign/oversized transport is refused.
- Stale/conflict: HTTP 409, focused error and retained original proof; inspect
  current history before a deliberate reload. Never silently rebase a POST.
- Denied: generic HTTP 404, including foreign or unknown decision/cursor; discard
  all prepared private content if authorization or source changes during render.
- Dependency failure: generic HTTP 503, no partial projection or success claim.
- Success: redirect to the same independently authorized exact message; GET
  reads actual receipt state. An uncertain attempt is not assumed successful.

Use the shared personal shell, one H1 and one main landmark. History/detail
navigation stays in this independently authorized purpose; the wider #108
navigation must authorize connections separately. Current generic Programme
API and adoption exclusions remain unchanged. No schema or new domain writer.

## Interaction and verification

Use ordinary labelled links, fields, confirmation and submit controls, shared
responsive cards and the existing pending-input guard. Long plain messages wrap;
color, hover and animation carry no exclusive meaning. Errors receive visible
focus without removing input. Native confirmation protects unsaved navigation.
No custom modal or new motion is introduced.

Automated evidence must cover exact recipient/tenant/field fences, query bounds,
audit-before-disclosure failure, before/after-render revalidation, independent
read/write denial, retained historical access, escaped content, malformed input,
CSRF/method fences, exact writer signature, stale/replay proof and shell/route
contracts. Maintain native recipient/lifecycle cases without executing them
during ADR 0100. Synthetic view/template browser evidence is not database proof.
Full viewport, keyboard, screen reader, native zoom and pending-input checks
remain explicit #92 tasks; native execution remains #102. Final integration
and promotion still require #109, #102, #97 and #92.
