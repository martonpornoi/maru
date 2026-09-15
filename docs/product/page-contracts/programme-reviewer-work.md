# My Programme reviews

Status: dormant #108 implementation contract; Applications owns this surface.
Requirements: PRG-003, PRG-006, AUD-001, QRY-005 through QRY-008 and UX-029.
[ADR 0085](../../architecture/decisions/0085-exact-revision-programme-review-and-decisions.md)
remains authoritative. No production route, profile, schema or permission grant
is introduced.

## Purpose, scope and disclosure

The reserved review root's `mine/` discovers only the current person's own
pending/active assignments, with call labels rather than private answer-derived
titles. `mine/{case_id}/{assignment_id}/` retains one exact own assignment;
`clear/`, `recuse/`, `score/` and `discuss/` are separate deliberate tasks.
Every route requires independent exact Department `applications.review_programme`
authority with `review_context`. Manager, assignment and navigation grant none.

Content-free retained metadata includes call/seal references, current case state,
original assignment state/stage and that immutable stage's configured rubric.
It includes removed/recused assignments for original receipt recovery, never
peers, private answers or evidence. Discovery uses complete bounded exclusive
assignment cursors; unknown/foreign assignments share a non-disclosing denial.

Pending reviewers declare their own no-conflict status or recuse with a reason.
Only a current active assignment and current exact submitted seal may read the
owner's protected projections. Context, answers and evidence are independently
authorized field ceilings; sensitive review authority remains additional.
Answers respect the pinned question allowlist and structured anonymity. Plain
free text can identify people; this is not a guarantee of anonymous authorship.
No unsafe file download, identity resolution or reference chooser is invented.

## Readable typed answers

The shared reviewer/moderator/decider presenter uses only the permitted exact-seal
answer projection. For choice answers, the owner additionally projects the selected
code/label pairs from that same immutable question, never the current call's schema
or an unselected option directory. Selection order is preserved; absent answers,
explicit empty multiple selections, false and zero have distinct truthful output.
Addresses show labelled components in a stable order, with empty optional components
omitted; country codes remain codes, without external lookup or inferred geography.
Dates, times and instants retain their explicit meaning/offset without assuming a
viewer timezone. Text, email, phone and HTTPS values remain escaped plain text,
not automatically actionable links. Unknown types, malformed selected metadata or
incoherent value shapes produce an unavailable projection, never a raw object dump
or silently wrong label. Registered `person_reference` / `programme.person` answers
link to the independently admitted [person viewer](programme-person-references.md)
below the exact own assignment's `answers/person/<question-key>/` route. It requires
the current submitted seal and nonanonymous allowed answer before Identity lookup;
current account labels are not frozen proposed-public contributor names. Domain,
file and unregistered-reference values remain non-disclosing placeholders.

This is presentation only: stage allowlists, structured anonymity, sensitive-read
admission, mandatory audit, source currency and before/after-render checks remain
unchanged. It does not authorize answer editing or new read purposes.

## Scoring, discussion and recovery

Each score is an explicit complete integer rubric with configured inclusive
bounds, required private rationale and confirmation. No score is prefilled,
totalled, ranked or recommended. Each update appends evidence; the latest valid
own score counts. Discussion is distinct from private rationale, requires the
policy to permit it and an own prior score, and may be shown to eligible peers.
The role-filtered evidence projection never supplies peers' scores or identities.
Evidence has complete exclusive case-version pagination, not a partial history
silently presented as complete.

Each POST retains its original assignment, immutable rubric, case version, retry
key, input and confirmation. Current fresh eligibility never replaces original
intent or blocks canonical receipt replay. Commands are attempted from scoped
own metadata, not a protected content GET that may now be denied. A minimal
successful receipt needs no current answer/evidence access. Fresh recusal may
remain available for an earlier stage or final case where the owner permits it;
it does not erase history or silently reactivate anyone.

## States and acceptance

Ordinary shared-shell links and labelled forms retain one H1/main, visible focus,
focusable errors, explicit pending-input protection, wrapping labels and no
page-level horizontal overflow. Readonly, stale-source and ended assignments
explain unavailable fresh work. Empty discovery, invalid input, version conflict,
service failure and denied reads are distinct, bounded and non-disclosing.
Reauthorize and compare protected projections before and after rendering; never
return cached content after revocation. Scoped read/audit failure fails closed.

Tests cover tenant/edition/Department/actor/field boundaries, pending-no-content,
retained original-stage rubric, closed transport and CSRF, score bounds, evidence
filtering, discussion conditions, late recusal, original receipt replay, stale
input preservation, readonly/empty/dependency states and render-time revocation.
Native cases are maintained but not executed under ADR 0100; debt belongs to
#102. Browser synthetic evidence is not native persistence or human acceptance.
Full keyboard, responsive widths, native zoom, reduced motion, screen-reader and
independent-person checks remain #92. Moderation, decision and conversion are
separate #108 tasks; this workspace cannot exercise those capabilities.
