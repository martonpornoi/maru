# Truthful administration-home entry

Date: 2026-10-16
Status: Implemented and focused feedback passed; exact certification and protected delivery pending

## Bounded outcome

Under UX-027, UX-029 and UX-031, the administration home now presents a bounded
set of already admitted navigation items. It preserves exact scoped URLs, labels,
descriptions and reauthorized pins; a profile alone grants no shortcut. Supported
events receive a neutral **Work on** heading. **Setup steps** stays secondary,
unknown profiles receive an unavailable explanation, and no-event users are
directed to **Change event** or an organizer who can check access. Platform
organization/account links appear only if the registry admits them. Users with
no workspace retain their invitation recovery path and advanced records retain
their existing gateway.

The home no longer reads Django admin log entries as a supposed recent-work
feed. No current-disclosure or completeness claim is made from those records.
This changes presentation, not ownership, permission admission, data schemas,
retention, audit events, adoption profiles or lifecycle rules. No migration or
data rollback is needed; a code rollback restores the prior presentation.
Existing ADR 0116 and the management-shell contract remain applicable. No new
architecture decision is needed for this projection-only change.

This addresses a finite part of issue #35. A true domain-backed operating home,
ordered work, governed recent outcomes and explicit dependency blockers remain
separate. It does not resume other unfinished module work or close issue #35.

## Focused evidence

- All 14,285 database-free units passed in 83.11 seconds. Home tests cover
  role/profile/no-event/unavailable states, exact admitted URLs and pinned
  destinations, permission loss/inactive accounts, secondary setup and omitted
  admin log history. The existing native branding assertion was updated; its
  execution remains part of the pending exact certification.
- Scoped Ruff formatting/lint, strict type analysis, NumPy docstrings,
  documentation validation and whitespace checks passed.
- One fresh ordinary `try_maru.py --scenario convention --port 8765 --minutes 20`
  preview was ready in 233.8 seconds. It used the existing disposable owner
  cleanup and genuine runtime role, with no preserved acceptance fixture reused.
- Normal visible Copy/sign-in flows covered ongoing Author and future Reviewer
  and Reader. Selecting an event offered only that account's authorized edition.
  Author/Reviewer homes offered Guides and Announcements; their links reached
  their proper work pages. Reader home offered Guides only and opened the
  approved library, without drafts, review, Announcements or setup cards.
- At CSS widths 320, 390, 768, 958, 1024, 1280 and 1920 there was no horizontal
  overflow; each view retained one main landmark and one H1. At 390 pixels,
  Enter expanded Technical setup details and Tab gave the Guides link visible
  focus. Desktop and narrow screenshots were retained as ignored evidence.
- Signed-out home access redirected to normal sign-in. No browser console
  warning/error was recorded. An initial credential-copy
  check used a redacted DOM value and failed sign-in; using the actual Copy
  buttons and waiting for their visible Copied state succeeded. This was a
  test-driver correction, not a product or permission change. No credentials
  were printed or retained outside the fixture.
- Browser observation found that the no-event instruction should name the
  header's Change event control. That final sentence was corrected afterwards
  and is covered by focused template rendering; the running server cached its
  earlier wording. The tested roles/routes/layout are otherwise unchanged.

## Remaining gates and limits

Preserve old certification evidence, verify owned preview cleanup, then certify
the clean exact commit against current main using the unchanged Auto policy.
Only passing authoritative hosted checks, CodeQL, resolved review conversations
and current mergeability permit the requested protected merge. Verify the merged
tree and fast-forward only the designated clean main afterwards.

These browser observations are assistant-operated, not independent-person or
full accessibility acceptance. Native print, 200 percent zoom, screen readers,
operational ownership and production acceptance remain open. The demo still
covers Announcements and Guides incrementally, not every Maru UI function.
