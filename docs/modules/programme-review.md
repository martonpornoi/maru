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

The dormant [independent decision workspace](../product/page-contracts/programme-decision-composition.md)
reserves labelled decider-only discovery, all-stage readiness, exact pinned
template/message preview and explicit signed confirmation. Leads, all retained
collaborators/reviewers and prior moderators are excluded before pagination.
`get_programme_decision_work` reads templates through the existing protected
context; `get_programme_decision_evidence` retains separate evidence authority.
`list_programme_decision_messages` is a decider-only, audited and sensitive-checked
outgoing history with no recipient directory/counts or acknowledgement states.
It does not widen moderator/reviewer projections. Preview signs only an exact
actor/scope/case/version/retry/outcome/text/rationale digest; it creates no decision.
Confirmation uses the unchanged canonical writer before any fresh private read,
preserving old receipt recovery. All-stage readiness, final-stage position and
independent decision authority remain canonical owner checks. Wait-list can be
followed by an explicit final decision but cannot repeat itself. No schema,
current manifest, production route, conversion or delivery effect is introduced.

The dormant [moderation workspace](../product/page-contracts/programme-moderation.md)
adds independently authorized exact-Department case discovery, protected
version-bound evidence and separate reasoned moderation, advance and reopen
tasks. Discovery excludes leads, every retained collaborator and every retained
reviewer assignment before pagination. Content-free metadata never grants
answers, attribution or sensitive content. `get_programme_moderation_evidence`
uses the existing protected detail query and canonical current-stage readiness
rule under the owner lock; it does not average scores or change quorum semantics.
History pages pin the inspected version and fail with conflict guidance if it
moves. Fresh reopening remains limited to open/waitlisted current-or-earlier
stages. Original POST receipt recovery precedes private metadata/content reads;
current route authority and canonical replay admission remain mandatory. No
Identity directory, schema change, production mount or profile activation is
introduced. Final decisions use their separate independent task; conversion
remains a separately authorized #108 continuation.

The dormant [review setup workspace](../product/page-contracts/programme-review-setup.md)
now reserves Department-scoped call discovery, one-stage-at-a-time policy
composition and exact immutable policy history. It uses independent
`manage_programme_review` authority with exactly `review_setup` requested;
the separate `review_context` ceiling still owns case/assignment context.
Setup metadata contains no proposal answers, contributor directory or private
review evidence. `list_programme_review_setup_calls` uses a bounded UUID cursor;
`get_programme_review_setup` returns a complete maximum-500-question graph and
the current policy sequence; `get_programme_review_setup_policy` reads one
explicit positive version with its creation reason. All audit before release.

`list_programme_review_intake_seals` uses that same exact `review_setup` ceiling
to list only current submitted sources for the chosen call, filtering existing
cases and all retained contributor conflicts before exclusive-cursor pagination.
`get_programme_review_intake_seal` returns exact retained seal metadata with
advisory eligibility, not answers or a case roster. Retained metadata remains
readable after source changes so the original confirmed POST can reach canonical
receipt replay. The dormant policy-to-source-to-confirmation journey supplies
the exact seal and immutable policy, canonical creation version zero and original
retry key. Reason/confirmation and safe error recovery reuse the shared shell.
Named assignment, content review, moderation, decision and conversion remain
separate independently authorized tasks; opening alone performs none of them.

The guided composer starts only from activated or retired immutable call
configuration; Drafts remain setup-pending without removing the kernel's
existing Draft-policy operation. Proposed stages/templates are validated
request-carried form state, not persisted drafts or authority. Ordinary labelled
controls explicitly choose quorum, rubric bounds, question visibility,
structured anonymity, discussion and all four decision templates/receipt rules.
Only final reasoned confirmation calls the canonical policy writer. Stale
recovery retains the proposed policy and original proof; only explicit refresh
creates a new version/retry intent. No schema, profile or production route changes.

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

`CASE_OPENED.reference_id` may bind the exact selected submitted seal. The
canonical writer checks it under existing locks and includes it in the existing
command digest. A newer seal conflicts instead of being silently substituted.
Trusted current-seal callers may retain None; command fields and absent-reference
digest shape remain unchanged for historical retry receipts. The dormant browser
case-opening task requires this proof and connects to separate named assignment
management. Moderator/decider work and accepted conversion remain #108
continuations.

## Roles and transitions

The dormant [named-reviewer management task](../product/page-contracts/programme-review-management.md)
connects setup and case-opening receipts to independently admitted manager
context. `list_programme_review_management_cases` supplies content-free call,
seal, policy and stage labels with an exclusive UUID cursor; the exact getter
returns every retained assignment across up to eight stages and sixteen people
per stage, including removed/recused rows. Overflow fails closed instead of
silently dropping history. Only already-scoped person IDs reach Identity's
active-verified-person label projection; unavailable people use a neutral label.
Neither API returns answers, scores, contact details or private rationale.

Known-email preview uses `prepare_programme_reviewer_selection`, after exact
`review_context` manager and case admission. Identity owns normalization; all
unusable/unsuitable selections share one empty response and audit precedes label
release. The purpose-signed identifier-only selection binds actor, tenant,
edition, Department, case, person, original case version and retry key. It grants
no authority. `read_programme_reviewer_selection` reauthorizes the retained case
and refreshes only its minimized label, never the email lookup or original intent.
Its neutral inactive-person result does not preempt canonical receipt replay.
Ordinary confirmed forms call the unchanged assignment/removal owner command;
they send no invitation/email and grant no review access. Pending/active historical
stage assignments may be removed late where the canonical source/planning guards
allow it. Navigation checks `review_setup` and `review_context` independently and
checks projection/admission again before and after rendering. See the recovery
runbook for signing-key rotation and uncertain-intent handling. Moderation,
final decisions and accepted conversion remain separate #108 tasks.

The dormant [own reviewer workspace](../product/page-contracts/programme-reviewer-work.md)
adds independently authorized own-assignment discovery, conflict clearance or
recusal, complete explicit integer rubrics, and separately labelled peer
discussion. `list_programme_reviewer_work` filters own pending/active assignments
before bounded pagination and batches score-existence flags; the exact getter
also retains removed/recused metadata for recovery. Shared call/seal labels do
not import manager authority. Original immutable assignment-stage rubric and an
own-score-exists eligibility flag are content-free `review_context`, not answer
or evidence disclosure. No score is prefilled, totalled, ranked or recommended.

Separate context, answer and evidence pages call `get_programme_review_detail`
with the independently requested field only. Current active assignment, exact
submitted seal, contributor exclusions, anonymity and additional sensitive
authority still apply. Rendered output is compared against reauthorized owner
projections before and after rendering. Pending assignments never load content.
Each command POST first reads only scoped retained own metadata, preserving its
original rubric/version/retry across stage or source changes. Successful old
receipt/late recusal renders no now-denied submission content. Typed safe file,
person/domain reference and other dedicated structured-answer viewers remain
explicit #108 work; no unsafe reference resolution or download is invented.

Every staff purpose also requires an active verified person, exact organization
and edition, current owner Department, and current policy/field proof.

| Role | Capability suffix after `applications.` | Bounded responsibility |
| --- | --- | --- |
| Review manager | `manage_programme_review` | Configure policy, open cases, assign/remove named reviewers; separately admitted setup metadata or case/assignment context, never answers/evidence |
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
- `get_self_programme_decision`: one exact addressed message through the same
  recipient/field/audit boundary, selected without scanning history pages.
  Foreign and unknown identifiers are denied alike.

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

### Dormant personal decision workspace

The [decision receipt page contract](../product/page-contracts/programme-decision-receipts.md)
defines reserved personal history/detail routes. The adapter uses only the
queries above and the existing closed acknowledgement command. A person sees
escaped immutable messages and their own receipt, never staff evidence or other
recipients' responses. Independent mutation authority permits an explicit
receipt; no private rationale is requested. The form retains the original case
version and retry key, including after a conflict or uncertain attempt.

These tasks do not depend on current proposal membership, an active call,
current Department or open planning. Addressed history and own receipt retain
their existing lifecycle exception. Before/after-render reads prevent stale
private disclosure; missing scope/object and unavailable dependencies produce
generic failure. Shared shell/assets provide ordinary labels, focused errors,
wrapping messages and pending-input protection. The exact template's asset
markers are admitted by containment tests, while production routes and every
generic Programme fence remain closed. Organizer review/conversion and wider
navigation/setup remain #108 work; no current profile is activated.

### Retained owner lifecycle

Fresh staff work requires open private planning and the same submitted seal.
Reopening, withdrawal, newer seals, and Department retirement serialize with
review through the existing edition lock chain. The dedicated
[accepted conversion](programme-conversion.md) independently revalidates the
exact source, effective review evidence, current owner/adoption authority, and
its own adapter contract under that lock. Conversion is explicit and preserves
review history; the review decision command does not create a Programme item.

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
downgrade refusal, and consistent-point recovery. Host relationships,
Scheduling, staffing, timetable surfaces, and composite adoption remain
separate successors under [#48](https://github.com/martonpornoi/maru/issues/48).
