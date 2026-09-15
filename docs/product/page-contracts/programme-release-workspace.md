# Programme release workspace

Status: dormant implementation under #108/#48; exact protected delivery pending.
No current profile, production route or production acceptance is added.

## Purpose and scope

Programme planners, independent reviewers and publishers turn an exact private
candidate into an explicitly approved and published timetable. Planning conflict
review is not release review. Authority remains Scheduling-owned under SCH-004,
SCH-007, SCH-012, AUD-001 and UX-005–008/019/020/027/029, and ADRs
[0094](../../architecture/decisions/0094-complete-programme-release-eligibility.md),
[0095](../../architecture/decisions/0095-trusted-programme-release-sources.md)
and [0096](../../architecture/decisions/0096-atomic-programme-release-and-invalidation.md).

Reserved canonical placement is the edition Programme workspace's **Release
timetable** task, beside Timetable planning; the isolated route is
`/admin/platform/organizations/<organization>/series/<series>/editions/<edition>/programme/release/`.
The adapter verifies the server-resolved organization/series/edition relationship.
It is not included in production URLs. Links are conveniences, never admission.

## Owner reads and disclosure

- Labelled current candidate discovery requires `scheduling.view_planning` /
  `candidates`, is complete and bounded by Scheduling's candidate limit, and
  cannot expose placements, people, public copy or reasons.
- Complete ten-category preflight uses `load_release_preflight`, its exact pinned
  adapter and all independently checked owner fields. No browser-supplied source
  facts, eligibility flag, acknowledgement or planner evaluation substitutes for it.
- Retained release warning and approval evidence requires
  `scheduling.view_history` / `planning_history`. Labels refer to the immutable
  candidate revision, not current labels. Reasons and accountable actor references
  are restricted history, not a person directory. Warning evidence is tied to the
  exact revision and complete source digest; an old acknowledgement is not reusable.
- Pointer observation requires `scheduling.view_planning` / `release_manifest`.
  It reports only the exact active identity and monotonic version, never serving
  eligibility. This source-independent selection keeps deliberate withdrawal
  possible when current content, owner sources or artifact validation fail.
- Publication/withdrawal history has independent `scheduling.view_history` /
  `planning_history` and `release_manifest` admission. Bounded older pages are
  explicit history, not a complete delivery inventory or a last-good fallback.
- All reads are tenant/edition scoped, audited, bounded and reauthorized before
  disclosure. Overflow, missing joins and inconsistent retained evidence are
  unavailable, not an empty successful result. No artifact bytes, private owner
  content, foreign calendar or unrequested identity labels are returned.

## Deliberate commands and recovery

Select an exact labelled draft, inspect every category and finding, deliberately
acknowledge permissible warnings with a reason, then independently approve the
exact candidate/source and explicit retained acknowledgements. Candidate and
selected-placement authors, including copy/restore ancestry and former authors,
cannot approve. An independently admitted publisher distinct from the approver
publishes one exact retained approval against the observed pointer. The publisher
may be a planner. The existing canonical commands authenticate every fact and
prepare/verify all required artifacts atomically before switching the pointer.

Whole-release withdrawal requires its own authority, exact active identity/version,
explicit confirmation and reason. It does not delete retained evidence, silently
activate a predecessor, or reset the monotonic pointer. No action implicitly
invites hosts, confirms volunteers or sends change notices.

POST intent retains original identifiers, versions, digest, rationale and retry
key. Dispatch reaches the existing command's reauthorized receipt recovery before
refreshing source discovery. Stale input is never rebased automatically. A confirmed
receipt is still success if an optional continuation later loses access; unknown
completion says to retry the exact intent, not create another key. Private input
stays out of URLs, sessions, browser storage and logs; use CSRF, no-store responses
and escaped bounded text. High-impact actions have explicit native confirmation.

## States and interaction

Use one shared shell, H1 and main landmark, visible Access explanation and
independently admitted tasks. Empty candidate/approval/history states explain the
preceding task without implying approval. Read-only, denied, stale, invalid,
unavailable and successful/replayed states remain distinct. Never show partial
preflight or old content after a final disclosure check fails.

Native labelled forms and buttons work without pointer gestures or JavaScript.
Narrow lists become wrapping labelled cards, with text severity and visible focus.
Pending rationale/selection is visibly identified and guarded against accidental
navigation. Keyboard, actual zoom, assistive technology and reduced-motion
acceptance remain part of #92; implementation evidence must state its limits.

## Bounded implementation evidence

Database-free owner-query, form, real-template and HTTP tests cover complete
selection, exact field admission, post-render failure, closed original command
dispatch, stale/replay recovery and source-independent withdrawal. Frontend tests
cover pending input, two-action discard confirmation and unchanged retry/version
fields. Synthetic browser rehearsal uses the actual views/templates/assets with
substituted owner sources and writers and a database access prohibition. It covers
planner acknowledgement, independent reviewer approval, distinct publisher
publication, stale withdrawal/retry and retained history at a 1,280-pixel viewport.
It is not native transactional proof or two-human acceptance. Genuine zoom,
screen-reader, full responsive and integrated owner-source acceptance remain #92,
#102 and #109; do not infer them from this bounded fixture.

## Acceptance and operations

Test field/role/adoption and cross-scope denial, exact owner selection, complete
inventories, retained immutable labels, pagination, required audit failure,
post-render revocation, original-intent replay, stale source/pointer, independence,
hard blockers and deliberate withdrawal without source recovery. Maintain native
scenarios in existing files, but do not collect/run PostgreSQL while ADR 0100
deferral applies. #102/#97/#109/#92 remain final gates, not waived by unit or browser
evidence. No schema change is intended; existing
[atomic release recovery](../../operations/programme-atomic-release-migration-and-recovery.md)
continues to govern fix-forward and stop-use.
