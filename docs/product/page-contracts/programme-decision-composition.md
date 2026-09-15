# Programme decision composition

Status: dormant #108 implementation contract. Applications owns this surface.
PRG-003, PRG-004, PRG-006, AUD-001, QRY-005 through QRY-008 and UX-029 apply;
[ADR 0085](../../architecture/decisions/0085-exact-revision-programme-review-and-decisions.md)
remains authoritative. No current profile, production route or schema changes.

## Independent discovery and protected inspection

The reserved exact-Department review root's `decisions/` discovers cases using
call/seal labels, excluding leads, every retained collaborator, every retained
reviewer assignment and prior moderators before complete bounded pagination.
Every page requires independent `applications.decide_programme` authority;
management, reviewing or moderation grants none. Metadata grants no content.

Exact-case work reads pinned policy/templates through the existing independently
authorized `review_context` projection, including its additional sensitive
authority. Separate context/answers/evidence sections reauthorize their own
ceilings. Evidence shows every stage's configured review count and existing
canonical readiness, never averaged scores, ranking or recommended outcomes.
History continuations bind the inspected case version and reject moved snapshots
without mixing pages or refreshing an old intent.

A dedicated decider-only retained-message history uses `review_evidence` and the
same independent actor, exact source/Department, classification and audit guards.
It shows immutable decision version/time, outcome, recipient-visible message and
pinned acknowledgement policy; it exposes no recipient directory, counts or other
people's acknowledgement state. It is not added to general moderator/reviewer
history. Earlier wait-list messages remain readable after a subsequent decision.

## Explicit composition and exact confirmation

The `decide/` task deliberately selects accept, reject, wait-list or
request-revision with no default, and separates recipient-visible additional text
from private rationale. Preview displays the exact pinned plain-text template,
additional text, resulting message and acknowledgement policy, with rationale
clearly private. No interpolation, sender, consent, invitation or delivery claim.

Confirmation binds actor, organization, edition, Department, case, original
version/retry, outcome and canonical text/rationale digest using a purpose-signed
proof. It contains no copied message/rationale, is POST-only, never a credential
or permission grant and has no arbitrary age cutoff that breaks original receipt
recovery. Changing any intent requires another explicit preview; never silently
refresh the original version or retry identity. Ordinary signing-key fallback
recovery applies, and raw proofs must not enter logs or issue reports.

Fresh preview checks current source, planning, final-stage position and every
stage's existing readiness. Waitlisted cases can receive accept, reject or
request-revision, never repeated waitlisting. The canonical DECIDED command
rechecks all authority, evidence and lifecycle inside its transaction. Acceptance
does not convert an item, create hosts, publish content or imply attendance.
Request-revision does not reopen the proposal or extend its editing window.

An original confirmed POST verifies its proof and reaches canonical receipt
handling before any private source/evidence read. A minimal receipt still needs
current route admission, not renewed content access. Failed attempts retain
original fields and proof only after fresh independent disclosure checks; revoked
scope returns a generic failure without cached private content. Preview is not a
decision, and a receipt is not permission to follow a separately guarded task.

## States, navigation and acceptance

Use the shared shell/assets, one H1/main, ordinary labelled forms, focusable
errors, pending-input protection and wrapping cards. Cover empty, populated,
preview, confirmed, final/readonly/stale-source, invalid, conflict, unavailable,
denied and overflow states. Reauthorize and compare protected projections before
and after rendering. Each history/content/continuation link authorizes again;
recipient self receipt and accepted-item conversion remain distinct tasks.

Permitted answers reuse the [typed review presentation contract](programme-reviewer-work.md#readable-typed-answers):
immutable selected choice labels, labelled address components, explicit absence
and escaped plain values. Registered Programme person answers additionally link to
the [dedicated person viewer](programme-person-references.md), which requires the
exact independent decider, current seal, nonanonymous allowed question and sensitive
field authority before minimized Identity labels. No lookup occurs in the pure
presenter; domain-reference and file viewing remain separately unfinished.

Database-free tests cover purpose/field/independence, complete filtered paging,
all-stage readiness, exact template/message separation, proof tampering and
scope reuse, fallback keys, stale original intent, replay before private reads,
CSRF, closed transport and disclosure revocation. Maintain native owner scenarios
without collection/execution under ADR 0100; debt remains #102. Genuine independent
people, keyboard, all responsive widths, native zoom, reduced motion and screen
reader acceptance remain #92. #102/#97/#109/#92 still gate final promotion.
