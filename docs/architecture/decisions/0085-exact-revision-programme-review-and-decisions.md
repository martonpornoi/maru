# ADR 0085: Review exact Programme revisions before accepted-item conversion

- Status: Accepted
- Date: 2026-09-05
- Extends: ADRs 0051, 0081, 0082, and 0084
- Partially supersedes: ADR 0082 only for the absence of a dedicated dormant
  Programme review and decision kernel; every legacy target fence remains.
- Requirements: PRG-003, PRG-004, PRG-006, PRG-009, PRG-011, IDN-014,
  AUD-001, AUD-003, AUD-005, NFR-002, NFR-003, and NFR-013
- Issue: [#71](https://github.com/martonpornoi/maru/issues/71), child of
  [#48](https://github.com/martonpornoi/maru/issues/48)

## Context

Applications owns sealed, contributor-acknowledged Programme revisions.
Programme owns a separate private item/readiness kernel. Generic Applications
review and target operations deliberately exclude Programme. A reviewer must
assess the exact submitted content, not a mutable answer sheet; accepting that
assessment must not implicitly create a host, Programme item, or public copy.

The next child therefore needs explicit review policy, attributable review and
moderation, exact-revision decisions, and separately bounded contributor
messages. The accepted-item adapter and host relationships remain successors.

## Decision

### Own review policy and evidence in Applications

A Programme call has append-only review-policy versions. Each version contains
one through eight ordered stages. Each stage declares its stable code, one
through sixteen required independent reviews, one through sixteen bounded
integer rubric criteria with explicit inclusive minimum/maximum values,
an explicit nonempty allowlist of the call's question keys,
whether peer discussion is permitted, and whether structured contributor
identities are withheld. There is no implicit quorum, weighted total, pass
score, automatic ranking, or automatic decision. Configuration explicitly
chooses these values within the technical bounds; the bounds are not policy
recommendations.

Each policy also declares a bounded plain-text template for each of accept,
reject, wait-list, and request-revision and whether that decision requires
recipient acknowledgement. Templates contain no executable expressions or
implicit private-field substitution. The final message combines the pinned
template with deliberately supplied recipient-visible text. Private decision
rationale is a separate field and is never appended to the message implicitly.

A review case binds one exact submitted proposal revision and one immutable
policy. A new seal requires a new case, retaining the old case and decisions.
The case has one optimistic version shared by assignment, conflict response,
scoring, discussion, moderation, stage movement, decisions, and acknowledgements.
One command appends one corresponding immutable evidence entry and receipt.

### Require independent, attributable reviewer work

Assignments name an exact active verified person for one case and stage.
Current or historical proposal contributors, the proposal lead, and the case
opener or a person who already moderated or decided the case cannot review it.
A named assignment alone grants no content
access: the reviewer needs the exact current owner-Department review capability
and must first make their own explicit no-conflict declaration. A conflicted
reviewer recuses themselves, or a review manager removes the assignment with a
reason. Removed and recused assignments never silently reactivate.

Scores are append-only complete rubric submissions. A current-stage reviewer
may replace their scores by appending a new entry; the latest valid score per
currently eligible assignment counts. Reviewers cannot see another reviewer's
scores or private identities. Peer discussion, when enabled, is separate from
scores and becomes visible only after the reader has submitted their own
complete score. Discussion contains no implied anonymity guarantee.

Moderation requires a separate capability and an actor who is neither a
proposal contributor nor an assigned reviewer. It appends rationale against
the current stage evidence version. Any later assignment, conflict, score, or
discussion change makes that moderation stale. Stage advancement requires the
configured number of current eligible scores and fresh moderation; stages
advance one at a time and cannot be silently skipped or reopened. A reasoned
moderator command may explicitly reopen an earlier stage in an open or
wait-listed case; subsequent stages require fresh moderation before advancing
again. Prior evidence is retained, and still-valid exact-revision scores may
be considered again rather than impersonating new reviewer submissions.
Late recusal or reasoned assignment removal remains possible after a stage or
decision: it invalidates affected score counts and moderation, never silently
rewrites the decision. Final accepted/rejected cases cannot reopen; an affected
accepted decision becomes ineffective for the later adapter. New work then
requires an explicit new submitted revision and review case.

The decision maker has separate exact-Department authority and is neither a
proposal contributor, reviewer, nor a moderator of the case. Review-management
authority alone does not grant reviewer, moderator, decision, or content-read
authority. Every protected content projection additionally observes the
definition/question classification and the stage's question allowlist; sensitive
content requires the existing independently checked sensitive-review authority.

### Keep exact revisions current without rewriting history

Fresh staff review operations require open edition planning, a current owner
Department, and the proposal still submitted against the case's exact seal.
They serialize with proposal writers and Department retirement through the
existing edition mutex before acquiring Applications aggregate locks. Moving
to a new revision, reopening, withdrawal, or retirement cannot race a fresh
decision. Those changes never rewrite historical review evidence.

Proposal self-write authorization also acquires the canonical shared barriers,
Organization, ConventionSeries, EventEdition, edition mutex, then actor and
relationship locks. It must not acquire the actor or edition first and later
wait for an organization held by review. The self path supplies no Department
requirement, preserving retained contributor access after owner retirement.
Real separate-connection tests force both source-first and decision-first
orders for withdrawal and reopening; transaction rollback is not a substitute
for this race evidence.

Accept, reject, and request-revision finish the review case after the last
stage has sufficient valid reviews and fresh moderation. Wait-list retains a
pending final outcome after the same review gates; a later separately reasoned
decision may move it to accept, reject, or request-revision. Final cases do not
return to scoring or silently replace a decision. A new submitted revision
gets a new case under explicit current policy. A request-revision decision is
an attributable request, not a command impersonating the lead: reopening still
uses the existing lead-owned command and applicable edit window.

An accepted decision is currently effective only while the proposal remains
submitted against that exact revision and its owner scope remains valid. A
future accepted-item adapter must recheck those facts and the final decision
under the same lock boundary; a historical accept record alone is insufficient.
This child creates no ApplicationTargetRecord, Programme item, host, readiness
fact, occurrence, Shift, public rendition, or schedule.

### Separate contributor messages from private review history

Decision recipients are the lead and exact included contributors from the
reviewed seal, not whoever happens to be on the latest roster. An active,
verified exact recipient may read only their decision messages and append
their own acknowledgement when required, including after withdrawal or owner
retirement. Acknowledgement means receipt, not agreement, hosting consent, or
acceptance on another person's behalf. It never exposes another recipient or
response. Later removal does not erase an already-addressed decision or its
receipt. There is no email sender, delivery claim, general conversation inbox,
or general Communications workspace in this kernel.

Anonymized reviewer projections omit structured contributor identifiers,
profiles, names, source-system identifiers, and invitation/consent material.
They expose only stage-allowlisted sealed answers and minimized
review context. Free text and submitted files may still identify an author;
anonymization is a field projection, not a promise of perfect de-identification.
The immutable generic `staff_visible` and `reviewer_visible` flags remain false
on Programme questions. The dedicated stage allowlist is the new review-purpose
ceiling; it never enables generic Applications review or mutates the sealed call.

### Preserve dormant, governed execution and recovery

Declare the dedicated capabilities and minimized event without adding them to
either current immutable adoption manifest, roots, routes, UI, APIs, workers,
or delivery handlers. Production runtime access to new relations is SELECT-only.
The established two-factor isolated-test authorizer guard is the only substitute
admission seam; it never bypasses database, audit, event, or outbox execution.

Use bounded typed inputs and explicit versions. Shared Applications retry-key
serialization covers the new receipt relation in both directions. Receipt
replay returns only the actor's minimized retained identifiers and versions
after current adoption/identity proof, not stale content or renewed authority.
Commands atomically retain state, immutable entry/decision/acknowledgement,
receipt, minimized audit, event, and outbox evidence. Sensitive reads are
bounded, reauthorized, and audited before disclosure.

Database guards enforce scope, exact source binding, closed record shapes,
immutable evidence, contiguous versions, and receipt-backed transitions.
Readiness fingerprints relations, constraints, functions, triggers, and runtime
ACLs. Empty reversal is supported; durable review evidence fences downgrade
before any table or evidence can be removed. Recovery fixes forward or restores
Applications and its Identity, Organization, Event, Workforce, Authorization,
Audit, Effects, and migration evidence from one consistent database point.

Review data uses the existing applications-programme-restricted retention
purpose: administering and explaining a voluntarily submitted proposal with
purpose-limited organizer access. It is not user activity analytics or a public
performance score. Existing privacy review and retention execution gates remain;
this kernel authorizes no production personal data or automated erasure.

## Consequences

- Review decisions become reproducible without duplicating proposal answers.
- Explicit policies avoid hidden scoring or acceptance thresholds.
- Recusal, scoring, moderation, and final decisions have distinct authority.
- Contributors receive deliberate messages without private review disclosure.
- Current profiles remain unchanged, and the department journey remains gated
  by accepted-item conversion, hosting, Scheduling, surfaces, and continuity.

## Alternatives considered

Generic Applications acceptance remains unsuitable because it lacks exact
sealed-revision and collaborator semantics. Combining review, conversion, and
hosting would hide separate authority and acceptance boundaries. Storing only
the latest score or decision would erase rationale. Treating anonymization as
automatic text redaction would promise safety this projection cannot prove.

## Requirements affected

PRG-003 gains explicit versioned stages, scoring, recusal, and moderation.
PRG-004 gains pinned decision messages and exact-recipient acknowledgement.
PRG-006 and PRG-009 retain private/public separation and exact reviewed seals.
PRG-011 preserves Department retirement serialization and retained self history.
IDN-014, the Audit requirements, and NFR-013 preserve purpose-bounded identity,
attribution, and dormant modular adoption. PRG-005 and PRG-008 remain successor
work and are not satisfied by an accept decision in this child.
