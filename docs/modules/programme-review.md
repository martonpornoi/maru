# Programme review and decisions

Owner: Applications. Status: implemented dormant kernel; no mounted workflow.
Contract: PRG-003/PRG-004 and
[ADR 0085](../architecture/decisions/0085-exact-revision-programme-review-and-decisions.md).

This boundary assesses one exact submitted, contributor-acknowledged Programme
revision. Acceptance is **not** conversion, hosting consent, publication,
Scheduling readiness, or a volunteer assignment. Neither current adoption
manifest admits it. Generic Applications review and target operations still
exclude Programme.

## Policy and source of truth

`ProgrammeReviewPolicy` retains append-only call policy versions. Each policy
explicitly configures one to eight ordered stages. A stage has a unique code,
one to sixteen required independent reviews, one to sixteen integer rubric
criteria with explicit inclusive bounds within 0–10,000, an explicit allowlist
of one to 500 existing call-question keys, structured identity withholding,
and peer-discussion policy. These are technical bounds, not recommended quorum
or scoring defaults. There are no automatic rankings, thresholds, or outcomes.

The four decision outcomes each have a pinned plain-text template and an
acknowledgement-required flag. Template and deliberate recipient text are each
bounded to 3,000 characters; the canonical message joins them with two newline
characters. Private rationale is separate. There is no interpolation or sender.

`ProgrammeReviewCase` pins the policy and exact submitted seal, not the current
mutable answer sheet. It has its own optimistic version; it never increments
the source submission's version. A new submitted seal needs a new case.
Policy changes affect only deliberately opened future cases.

## Roles and transitions

Every staff purpose also requires an active verified person, exact organization
and edition, current owner Department, and current policy/field proof.

| Role | Capability suffix after `applications.` | Bounded responsibility |
| --- | --- | --- |
| Review manager | `manage_programme_review` | Configure policy, open cases, assign/remove named reviewers; context and assignment roster only |
| Reviewer | `review_programme` | Declare own conflict status, score own active assignment, and join enabled discussion after own scoring |
| Moderator | `moderate_programme_review` | Inspect private evidence, append rationale, advance or explicitly reopen stages |
| Decision maker | `decide_programme` | Independently record a final or wait-list decision; nondelegable |
| Exact recipient | `view_programme_decision_self` / `acknowledge_programme_decision_self` | Read addressed messages and acknowledge only their own receipt |

The lead, every retained proposal collaborator, case opener, and prior
moderators/decision makers cannot become reviewers. A pending assignment
reveals no proposal content before that reviewer clears their own conflicts.
Recused and removed assignments never reactivate, and a stage retains at most
sixteen named assignments including removed ones. Moderators cannot be
contributors or assigned reviewers. A decision maker also cannot have
moderated the case. Opening a case does not itself exclude later moderation
or final decision, but the separate capability and independence rules do.

Scores are complete append-only rubric submissions. Only the latest score for
each live eligible assignment counts. Another score from the same reviewer
does not fill another required review. Reviewers cannot see peer scores or
private identities. Discussion is separate and visible to other active
reviewers only after their own complete score; it does not promise anonymity.

Moderation pins the current evidence version. Later assignments, conflict
changes, scores, or discussion invalidate it. Advancement moves exactly one
stage after the configured review count and fresh moderation are satisfied.
Explicit reasoned reopening is allowed only in open/wait-listed cases and
invalidates moderation for the chosen and subsequent stages. Still-valid
exact-revision scores remain attributable and may be reconsidered.

Acceptance, rejection, or request-revision follows all final-stage gates and
finishes the case. Wait-list may later move to one of those outcomes, retaining
both messages. It cannot repeatedly wait-list itself. Request-revision does not
reopen a proposal on the lead's behalf or extend the existing editing window.
Late recusal/removal can invalidate a historical acceptance without rewriting
it; accepted/rejected cases cannot reopen. Fresh work then needs a new seal.

## Commands and protected reads

`programme_review_commands.apply_programme_review_command` accepts a closed
`ProgrammeReviewCommandInput`, exact actor/tenant/Department scope, expected
version, retry key, reason, correlation ID, and registered source channel.
The action enum rejects irrelevant optional fields. Policy creation targets a
call and its policy version; case opening targets a submitted proposal at
version zero; all other commands target a case and its current version.
`reference_id` means an account for assignment, an assignment for reviewer
actions/removal, or an addressed decision for acknowledgement.

Each fresh command atomically retains its transition, immutable entry,
decision/acknowledgement where applicable, receipt, minimized audit, domain
event, and outbox row. The event is
`applications.programme_review.changed.v1`; its only payload fields are action,
opaque aggregate ID, and canonical resulting version. There is no handler or
delivery claim. Shared retry serialization covers generic Applications,
Programme intake, import, and review receipts in both directions. Exact replay
requires current minimal adoption/identity proof and returns retained IDs and
versions before reacquiring a write scope; it grants no fresh content access.

Protected reads accept `ProgrammeReviewReadRequest` with explicit purpose,
nonempty field ceiling, and audit correlation:

- `list_programme_review_cases`: management queue or the caller's pending/active
  assignments, without submission content. Current-stage assignment convenience
  fields and the caller's `(assignment_id, stage, state)` tuples permit late
  recusal of an earlier stage.
- `get_programme_review_detail`: `review_context`, `review_answers`, and/or
  `review_evidence`, filtered independently. Management is context-only.
  Reviewer content requires a live current-stage cleared assignment; moderator
  and decision reads independently prove their role exclusions.
- `list_self_programme_decisions`: chronological exact-recipient history, with
  the decision's own version/time and the current case version. Message/outcome
  and own acknowledgement/time have separate field ceilings. Another person's
  recipient or acknowledgement data is never projected.

Pages contain one to 100 results. Case queues use an exclusive UUID cursor;
evidence uses exclusive case versions; recipient history uses the prior
addressed decision's opaque ID in `(decision time, ID)` order. A foreign or
unknown recipient cursor is denied. JSON strings in detail projections are
immutable serialized **projections**, not raw model dictionaries:

- Context contains stage/state/current-revision facts, policy identity and
  stages. Managers additionally receive the bounded named assignment roster.
  Content readers receive the sealed track, format, and requested duration.
  Nonanonymous content readers receive only public-name/biography profile
  fields; decision makers also receive the pinned templates. Moderator/decision
  context exposes effective review-side acceptance after current owner proof.
- Answers contain only allowlisted sealed question key, label, type,
  classification, and value/explicit absence; no mutable current answer lookup.
- Evidence contains a complete page of permitted entries. Reviewers see their
  own score/rationale and allowed peer discussion text, not peer scores,
  account IDs, assignment IDs, or manager rationale. Independent moderators
  and decision makers can inspect attributable private history.

The generic question `staff_visible` and `reviewer_visible` flags remain false.
The dedicated stage allowlist is a separate review-purpose ceiling. Anonymized
reviewer projections omit structured profiles, automatic source bindings,
contact/reference/file/URL question types, and source-system identifiers.
Free text can identify someone: this is not automatic de-identification.
Restricted definitions and restricted projected questions additionally require
the independently checked `applications.review_sensitive` capability.

Reads hold the shared edition consistency boundary, reauthorize, and append
the sensitive-read audit before returning. Audit failure prevents disclosure.
Unknown/foreign reviewer objects are denied without exposing their version.

## Lifecycle, privacy, and recovery

Fresh staff work requires open private planning and the same submitted seal.
Reopening, withdrawal, newer seals, and Department retirement serialize with
review through the existing edition lock chain. A future conversion command
must independently revalidate exact source, effective review evidence, current
owner/adoption authority, and its own adapter contract under that lock.

Recipients are the exact included contributors from the reviewed seal, not
the latest roster. Later removal, withdrawal, or owner retirement does not
erase their addressed message or prevent their own required acknowledgement.
Acknowledgement means receipt, not agreement, contributor consent, or hosting.

The seven review relations use the existing
`applications-programme-restricted` purpose. This is voluntary proposal
administration and accountable review, not activity analytics or public
performance scoring. Scores, rationale, conflicts, messages, and identities
never enter the domain-event payload. Existing retention/privacy approval
gates remain; this child authorizes neither production data nor automated erasure.

See the [migration and recovery guide](../operations/applications-programme-review-migration-and-recovery.md)
for guards, read-only runtime ACLs, exact readiness fingerprints, populated
downgrade refusal, and consistent-point recovery. Programme conversion, hosts,
Scheduling, staffing, timetable surfaces, and composite adoption remain
separate successors under [#48](https://github.com/martonpornoi/maru/issues/48).
