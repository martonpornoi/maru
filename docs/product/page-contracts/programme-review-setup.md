# Configure Programme review and open exact cases

Status: dormant #108 implementation contract; no current profile or production
route. Owner: Applications. Requirements: PRG-003, PRG-004, PRG-006, PRG-009,
AUD-001, QRY-005 through QRY-008 and UX-005 through UX-008/UX-029.
Authority: [ADR 0085](../../architecture/decisions/0085-exact-revision-programme-review-and-decisions.md)
and the [review module](../../modules/programme-review.md).

## Purpose and independent scope

Delivery is incremental: policy configuration/history, the labelled exact-seal
chooser and confirmed case opening are implemented. Named assignment and
reviewer/moderator/decision/conversion remain the next #108 increments; no
nonfunctional management control is shown.

An exact Department review manager selects an owning call, deliberately defines
ordered review policy, inspects immutable policy versions and opens a case for
one selected submitted seal. This is neither proposal-content review nor final
decision authority. No answer, contributor profile, contact directory, reviewer
score or private case rationale is part of setup discovery.

The reserved root is
`/admin/applications/programme-review/{organization_id}/{edition_id}/{department_id}/`.
Every destination resolves the authenticated active verified person, exact
organization/edition and current Department independently. Navigation is not
a grant; call-management authority is not borrowed for review setup.

The existing `applications.manage_programme_review` capability gains the explicit
code-owned `review_setup` field ceiling for call/question configuration metadata,
immutable policy definitions and eligible submitted-seal references. This is
separate from its existing `review_context` case/assignment ceiling; neither
grants answers/evidence or reviewer/moderator/decider authority. Dedicated setup
queries require exactly `review_setup`, remain bounded and append sensitive-read
audit before release. Generic and production Programme fences stay closed.

## Stable call configuration and explicit policy

The guided composer starts after the call's question configuration is frozen by
domain activation. This can happen before its future opening date; it does not
publish a call, activate a profile or mount a route. Retired calls retain their
immutable configuration and can still support independently admitted review.
Draft calls are truthfully setup-pending: finish the call configuration with its
owner first. This is guided sequencing, not a removal of the existing trusted
kernel's Draft-policy operation. Ordinary review does not inherit call deadlines.

Policies explicitly choose one to eight ordered stages, one to sixteen required
independent reviews per stage, one to sixteen named criteria with inclusive
integer bounds within 0–10,000, and one to 500 labelled call questions per stage.
Structured identity withholding and peer discussion are explicit yes/no choices.
All four outcomes require deliberate plain-text templates and explicit receipt
policy. Technical bounds are not default quorum, score, threshold or ranking.
There is no automatic outcome, template interpolation or hidden author identity.

Compose one stage at a time, with ordinary labelled criterion and question
controls. Proposed stages/templates are carried only in a bounded closed request
state, validated as untrusted input on every request. They are not authority or
a second persisted policy model. Keep, edit, reorder and remove operations alter
only this proposed form state. Full raw JSON is not a user editing workflow.
Keep each stage's request below the existing framework field-count limit; do
not raise global upload limits or weaken CSRF to support large policies.

An explicit final review shows the complete proposed policy, source call and
original policy-version/retry proof, with reason and confirmation. Only final
save calls the existing owner command to append one immutable policy version.
The version belongs to the call's policy sequence, not its call aggregate.
Changing policy affects only deliberately opened future cases, not prior cases.
Unsaved policy state is identified as unsaved throughout; leaving it is protected
by the shared pending-input grammar. Any refresh of stale intent is deliberate,
retains the proposed policy and creates a new explicit version/retry proof.

## Exact case opening and retained retries

The immutable policy page links to
`{call_id}/policies/{version}/cases/` beneath the reserved root. Its bounded
ascending UUID cursor lists current submitted seals for that exact call and
Department. Lead, every retained collaborator (including pending/removed),
noncurrent sources and already-opened seals are excluded before pagination.
One lookahead produces a complete page of at most 100, default 50; no hidden
total, truncated option list or private answer-derived title is exposed.

Selecting `{revision_id}/` retains that exact route-bound source and policy.
Its audited metadata getter requires current Department setup authority but
does not require fresh-opening eligibility: changed/withdrawn/previously opened
seals remain identifiable for uncertain-response retry. It returns only seal
and proposal references, sequence/sealing time, advisory eligibility, existing
case presence and planning status, never case evidence or a reviewer roster.
Fresh writes still pass the canonical owner transaction and independence checks.
No call window or active-call requirement is added to review.

Select from independently authorized eligible submitted seals and explicit
immutable policy versions for the same call. Use call labels, seal sequence/time
and a stable disambiguating reference, never a guessed UUID or private answer
substituted as a title. Case opening confirms the selected seal and policy;
it does not assign reviewers, score, decide, convert or create a Programme item.

The browser supplies the original exact seal through `CASE_OPENED.reference_id`.
The canonical command checks that reference under its existing writer locks and
includes it in the existing request digest. A newer submitted seal cannot be
silently selected after the manager has confirmed another one. Trusted callers
that intentionally request the current seal may retain the existing absent
reference behavior. No dataclass field or unconditional digest key is introduced:
old same-intent retry digests remain unchanged. Other actions retain their closed
required reference meaning. Unknown/foreign/wrong-call policy, stale seal,
contributor opener and duplicate seal-case remain denied/conflicting through the
owning command; no browser preflight substitutes for transaction checks.

The creation form requires canonical version zero, original retry key, explicit
reason and confirmation. Duplicate, unknown, oversized and uploaded controls are
rejected. Original POSTs still reach the writer after source/planning changes;
same-intent replay can return the original receipt. A successful response shows
only the owner's case/opening-version/receipt references. Conflict and recovered
dependency errors retain bound controls when the protected source can still be
reauthorized. A persistent read/audit failure returns generic unavailability,
not cached private data. A different source or policy requires deliberately
returning to its chooser; reload never silently substitutes a newer revision.

## States, safety and interaction

- Empty or setup-pending: truthful guidance, no fabricated policy or case.
- Ordinary/history: bounded labelled call, immutable policy and eligible seal
  pages; complete next-cursor semantics and no hidden total counts.
- Proposed: explicit unsaved state, no domain write or claim of saved policy.
- Validation: HTTP 400, linked field errors and retained recoverable input.
- Stale/conflict: HTTP 409 with original source/retry proof and explicit recovery;
  no silent rebasing, automatic replacement or new case for a different seal.
- Read-only: authorized configuration/history remains visible when planning is
  closed, without enabled mutation controls.
- Denied: generic HTTP 404; unknown and foreign exact references share failure.
- Unavailable/overflow/audit failure: no partial private disclosure or success
  claim; generic dependency failure. Reauthorize before/after protected rendering.

Use the shared management shell, one H1/main, ordinary labelled links/forms,
visible focus, wrapping cards and focused error summaries. No custom modal or
animation. Avoid page-level overflow; long question/rubric text stays readable.
Separate view and command scope, validate duplicate/unknown fields and bounded
state before use, and keep privileged rationale inspectable in the owning policy
history without leaking case review evidence. No production data or new retention
purpose; existing review retention, audit and recovery contracts apply.

## Evidence and continuations

Test exact Department/field/query bounds, manager-only disclosure, immutable
policy round trips, complete explicit choices, malformed/oversized/duplicate
state, stable legacy and changed-seal retry digests, stale/foreign case selection,
CSRF/method guards, no preview writes, original input recovery, audit failure,
late-render denial and dormant route/manifest containment. Maintain native
transaction/lifecycle/concurrency cases without collecting or executing them
under ADR 0100. Synthetic browser fixtures must not claim persistence.

Genuine responsive/keyboard/screen-reader/zoom and representative manager
comprehension remain #92 work; native acceptance remains #102. Named assignment,
reviewer conflict/scoring/discussion, moderation/decision, accepted conversion,
readable recipient source context, wider connections and setup remain #108
continuations unless separately delivered. #109/#102/#97/#92 still precede final
promotion; no component alone closes #108/#48.
