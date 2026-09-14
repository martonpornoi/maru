# Independent Programme decision composition

Date: 2026-09-14. Owner: Applications. Scope: one bounded #108/#48 continuation,
from protected PR #125; no production activation or profile change.

## Outcome and safety

The [decision page contract](../product/page-contracts/programme-decision-composition.md)
implements PRG-003/004/006 under ADR 0085: independent labelled discovery,
all-stage readiness, exact pinned plain-text template/message preview separated
from private rationale, and explicit purpose-signed confirmation. The proof
contains an exact digest, not private text. Every actor/scope/case/version/retry/
outcome/text/reason component is bound; changing intent requires re-preview.
It never grants authority or bypasses canonical DECIDED admission. Original
confirmed POSTs reach canonical receipt recovery before private reads.

Discovery excludes leads, all retained collaborators/reviewers and prior
moderators before bounded pagination. Separate content and outgoing history
retain field/sensitive/independent-actor/audit guards. Decider outgoing history
does not expose a recipient directory, counts or other people's receipt state,
and is not added to moderator/reviewer projections. Wait-list can be followed by
an explicit final decision, not repeat itself. Acceptance is not conversion,
hosting, publication, volunteer work or delivery. Shared moderation changes are
pure already-authorized projection formatting, not permission inheritance.

No schema, dependency, manifest, production route, canonical writer or CI policy
changes. Existing signing-key fallback governs old proof recovery. There is no
arbitrary token expiry, cached-private-content fallback, destructive path or
new activity collection. The existing recovery runbook documents failure handling.

## Iteration evidence

- 223 focused database-free decision/moderation/containment cases passed in
  3.03s. Full inexpensive unit feedback: 7,175 passed in 64.80s with three
  pre-existing URLField warnings. No PostgreSQL collection/execution.
- Focused strict typing, NumPy and semantic Python documentation passed.
  Initial tests caught the reserved Django message-context name collision;
  dedicated `decision_messages` fixes real history rendering. Two fixture
  assertions were corrected to match canonical UUID and reserved-route semantics.
  Formatting and one optional-projection type annotation were corrected locally.
- The native review-services file gains one real-owner scenario for independent
  exclusions, pre-moderation denial, exact preview/no mutation, wait-list message,
  final successor, history continuation and original receipt replay. It remains
  unexecuted ADR 0100/#102 debt; no invented timing weights or coverage claims.
- Full clean-commit certification and exact-head hosted PR gate/CodeQL are still
  required after this checkpoint; this is not a success receipt or merge claim.

## Bounded browser evidence

Loopback-only synthetic fixture, real Django shell/forms and purpose signatures,
mocked authorization/query/command persistence, all database connections forbidden,
fixture-only CSRF bypass. Browser used ordinary labelled links and controls.
Observed at 1280 CSS pixels: independent discovery, blank deliberate outcome,
two-stage readiness, separated exact preview/rationale, unchecked confirmation,
changed-text rejection, explicit re-preview and minimal success receipt. Stale
confirmation kept original outcome/text/reason/version and checked confirmation;
the alert received focus. Read-only/final pages omitted a fresh decision task;
denied detail was generic. Escaped synthetic script-like labels stayed text.
One H1/main and document scroll/client width 1265 at viewport 1280; screenshot
reviewed. Pending input protection used shared assets. One explanatory sentence
was clarified after the rehearsal and is covered by final rendered-form tests.

No native persistence, message delivery, two-human independence, complete keyboard
journey, all responsive widths, genuine 200% zoom, reduced-motion or screen-reader
acceptance is claimed. #92 owns genuine manual acceptance; #102 native restoration,
#97 logical recovery and #109 integrated acceptance remain required before #108
promotion. Next bounded work is accepted conversion and the documented remaining
#108 journey connections, not unrelated issue work.
