# Announcements workspace

Status: Implemented with bounded synthetic browser verification; protected delivery pending
Last updated: 2026-10-09
Requirements: ANN-001, ANN-003 through ANN-005, ANN-007 through ANN-009, UX-031
Decision: [ADR 0117](../../architecture/decisions/0117-standalone-manual-announcements.md)

## Purpose, audience and routes

Help a convention team prepare consistent approved announcements, publish through
its existing channels, and keep corrections understandable. The canonical native
workspace is `/admin/announcements/<organization_id>/<edition_id>/`, in Overview.
Platform setup starts at `/admin/platform/setup/announcements/`. Creation belongs
beside the announcement inventory; settings and each announcement's draft, review,
publication reports, corrections and downloads belong to this workspace.

One page H1 and the shared main landmark identify the task. The selected event is
always visible. The starting explanation is: "Prepare announcements here, then
publish them through your existing channels." No unrelated adoption is suggested.
Setup names the foundation it creates or reuses and continues into accountable
access when the two operators have not yet accepted and activated their roles.
Announcements editions must be created and retried through this dedicated setup;
the generic edition page and API cannot skip its representation and setup receipt.

## Authority and disclosure

The exact edition profile and current authority are checked before private labels,
counts, text or person facts are loaded. `announcements.view` admits the workspace
and exact approved-copy projection; composing, review, publication reports, settings
and private evidence export have separate capabilities. Every destination authorizes
again. Computed Access explains the current actions without exposing a people
directory or becoming another permissions system.

Missing, denied and foreign objects have the same non-disclosing unavailable result.
A dependency failure cannot release partially collected evidence or download bytes.
Private responses are no-store. Technical IDs and approval/retry versions are not
human labels; required choices, authorization consequences and errors stay visible.

## Task sequence and content ceiling

1. **Record-keeping rules:** A settings operator records the real applicable rules,
   their owner and review date and explicitly confirms their scope. Names and
   explanations are readable; Maru never invents an approval or disposal promise.
2. **Write announcement:** Enter headline, canonical text and language. Select
   actual manual destinations and prepare each exact channel/language text. Nothing
   is silently translated, shortened or selected for publication.
3. **Request review:** Preview every selected rendition and explain that another
   organizer must check it. Selecting or mentioning a reviewer does not notify them
   or grant access.
4. **Review announcement:** Show the exact version, every channel rendition and the
   independent-review rule. A person who edited the draft cannot approve it. Review
   notes stay private; requested changes explain the next writer action.
5. **Copy approved text:** Offer selectable text and a plain-text download. Explain
   that copying does not publish anything. Omit reviewer notes and private history.
6. **Record publication:** Record the operator's actual external claim, including
   claimed publication time and optional safe post link. Show who reported it and
   when; never label the report as provider verification or audience receipt.
7. **Make a correction:** Keep the last approved text visible while a correction
   is prepared. After independent approval, compare "Previously posted text" with
   "New approved text" and identify only the channels whose copy needs updating.
8. **Download and stop:** Separate approved copy from the privileged handover
   export. Stopping work retains authorized history and explicitly leaves external
   posts to their channel owners. Explain that new writing and review are stopped,
   while reporting earlier publication of approved copy and correcting retained
   reports remain available.

Writing states use **Draft**, **Waiting for review**, **Changes requested** and
**Ready to publish**, with cancellation/stopped state explained separately.
Per-channel evidence uses **No publication recorded**, **Publication reported**,
**Update needed** and **Report withdrawn**. A reported update returns to
**Publication reported**, with its exact copy and dates retained in history.
Writing state and publication evidence are distinct; avoid an ambiguous overall
Published badge. A correction of a mistaken report retains the
previous claim and the actor's reason; it never implies deletion of an external post.
History identifies each report's exact copy, destination, dates and correction chain,
with correction actions for every eligible retained report. A corrected older claim
does not replace a newer publication status. Requested changes direct the writer to
edit before asking for another review.

## States, recovery and accessibility

An empty inventory explains the workflow and offers only authorized next actions.
Lists remain bounded and navigable as they grow. Required setup is actionable:
"Announcements setup is incomplete. An accountable organizer must confirm the
record-keeping rules before you can continue."

Validation has a summary and associated field errors, preserves entered values,
and expands any section containing an error. Stale forms retain their original
announcement/settings version and retry proof, explain that another person changed
the announcement or settings and provide a safe reload/compare action. A changed retry cannot silently become a new
mutation. Success states describe the exact action performed, without a claim that
a message was sent. Cancel and stop actions explain remaining external work and
require the applicable reason.

Desktop, intermediate and narrow layouts keep labels and text readable without
page-level horizontal scrolling. Long channel names, multilingual copy and URLs
wrap. Semantic headings label comparisons; color alone never carries meaning.
Ordinary links navigate and buttons submit actions. Visible keyboard focus,
labelled controls and predictable error focus are required. The full native journey,
selectable text, downloads and print work without JavaScript. Reduced motion does
not hide progress or state. Technical details use an ordinary expandable disclosure.

## Verification boundary

Automated coverage must include authorization, independent authorship, exact-version
review, replay/conflict recovery, cross-organization/edition denial, correction
status and export field ceilings. Native database tests must prove immutable history,
atomic evidence and runtime authority. Browser evidence must name synthetic roles,
actual viewport widths, keyboard/error/no-JavaScript states and denied deep links.
Assistant-operated rehearsal is separate from independent human comprehension,
specialist accessibility and deployment-owner acceptance. Current results belong in
CURRENT and the implementation checkpoint, not an unqualified acceptance claim here.
