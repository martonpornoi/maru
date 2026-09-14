# Manage named Programme reviewers

Status: dormant #108 implementation contract; no current profile or production
route. Owner: Applications. Requirements: PRG-003, PRG-004, AUD-001,
QRY-005 through QRY-008 and UX-005 through UX-008/UX-029. Authority:
[ADR 0085](../../architecture/decisions/0085-exact-revision-programme-review-and-decisions.md).

## Purpose and separate authority

An exact current Department review manager can discover labelled cases, inspect
their pinned source/policy and complete named assignment roster, deliberately
select one reviewer, or remove a pending/active assignment with a reason. This
requires exactly `review_context` under `applications.manage_programme_review`,
not `review_setup`, proposal-content review, moderation or final-decision access.
No answers, contributor profiles, peer scores or private review rationale are
shown. Navigation independently checks its destination and is never a grant.

The reserved review root's `cases/` lists complete cursor-bounded case summaries;
`cases/{case_id}/` shows one case; `cases/{case_id}/assign/` owns named selection
and confirmation; `cases/{case_id}/assignments/{assignment_id}/remove/` owns one
reasoned removal. Production routes remain unmounted. The existing shared shell
retains one H1/main, ordinary links, labelled forms, focusable errors and pending
input protection. Long labels/references wrap without document overflow.

## Named selection and exact intent

The manager supplies one known exact email after independent case authorization.
Identity owns normalization and active/verified/person resolution; this extends
the documented purpose-limited invitation seam to accountable named reviewer
selection, not prefix search, an account directory, contact disclosure or access
provisioning. The owner audits before returning any candidate label. Invalid,
unknown, unusable and unsuitable choices have one non-disclosing outcome.

Preview does not assign. It returns a minimized current label and a bounded,
purpose-signed request selection pinning exact actor, organization, edition,
Department, case, person, original case version and retry key. It contains no
email or cached name. Confirmation requires reason and explicit agreement;
the canonical assignment writer receives the pinned person ID, not a fresh
email lookup. Altering scope/person/version/retry or the signature fails closed.
The signature establishes request integrity, never capability, current person
state or mutation eligibility. Every read and command authorizes independently.

No arbitrary expiry blocks recovery of an uncertain same-intent submission.
Ordinary Django signing-key governance applies: preserve configured fallback
keys for retained in-flight intent during rotation; a lost key means the page
cannot validate that selection, not that the assignment failed. Inspect the
independently authorized roster/receipt before starting a new selection. Do not
disable signature validation or invent a new person/retry to conceal uncertainty.

Current labels use Identity's bounded active-verified-person projection only
after the relationship or signed selection is scoped. An unusable retained
person has a neutral label; it does not prevent the original POST from reaching
canonical receipt replay. No identity directory or email is included in roster,
audit, domain events or signed selection. Existing restricted review retention
and voluntary proposal-administration purpose apply, not activity analytics.

## Existing owner rules and recovery

Assignment uses the existing exact case version and writer locks. It rejects
the case opener, lead, every retained collaborator, prior moderator/decider,
duplicate current-stage assignee and more than sixteen stage assignments,
including removed ones. A named assignment grants no reviewer capability or
answer access; the person independently needs current Department review
authority and their own conflict clearance. No email or invitation effect is
implicitly sent, and no authorization grant, host or volunteer record is made.

The complete roster retains all stages, removed/recused entries and stable
assignment references. Current pending/active assignments can be removed by
reasoned manager command, including late after stage/final-decision progress
where the existing writer allows it. Source/planning guards remain authoritative;
the UI does not invent permission for a withdrawn/newer seal. Removal never
rewrites scores or decisions and cannot silently reactivate a relationship.

Fresh eligibility hints must not preempt canonical old-receipt replay. Stale,
validation and recoverable service failures retain original reason, confirmation,
selection, case version and retry. Read/audit failure returns generic denial or
unavailability, not cached private names. Changing person or refreshing intent
is an explicit new selection, never silent rebasing after source/stage progress.

## Acceptance and limits

Test scope/field/actor admission before identity lookup, bounded complete queues
and rosters, label lifecycle, signed-selection tampering and cross-scope replay,
known-email preview/final exact-person binding, original retry after email/state
changes, current and late removal, CSRF, closed transport, before/after-render
revocation, readonly/empty/denied/dependency states and preserved pending inputs.
Maintain native owner/guard/retry scenarios without execution under ADR 0100.
Synthetic actual-form browser evidence is not database or human acceptance;
full widths, native zoom, keyboard, reduced motion, screen reader and real
independent people remain #92 tasks. Review/scoring, moderation, decisions and
conversion are separately admitted successors, not implied by this increment.
