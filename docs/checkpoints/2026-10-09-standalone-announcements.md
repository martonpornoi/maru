# Standalone Announcements implementation

Date: 2026-10-09
Status: Local implementation and focused verification; protected delivery pending
Base: `e77fae5b94dbee3e7f2e9d64b2f768be95888738`
Requirements: ANN-001, ANN-003 through ANN-005, ANN-007 through ANN-009, UX-031
Decision: [ADR 0117](../architecture/decisions/0117-standalone-manual-announcements.md)

## Outcome and boundary

A convention can prepare reviewed announcements and keep truthful reports of posts
made through its existing channels. The exact `announcements_only@1` profile adopts
only Announcements and its foundations. Purpose-specific operators use genuine
invitations, self-acceptance, activation and retained authority provenance. Existing
profile versions and Workforce operators keep their original meaning.

The native journey covers readable record-keeping settings, writing exact channel
and language copies, independent review, copy/download, manual publication reports,
corrections and stopped use. A correction retains the last approved copy; unchanged
channels retain their reports. Retrospective reporting and corrections remain
available after stopping or cancelling without reopening writing or review.

The new Announcements owner retains immutable versions, decisions and reports with
atomic receipts, audit and internal domain events. Runtime access cannot delete or
truncate its records. Exact settings and announcement cursors protect stale forms;
current authorization precedes every retry, preview and download. Public copy and
private history have distinct field admission. No recipient notification or
external publishing route is adopted.

Human-facing routes, field labels, home continuation and scoped navigation are
native forms. Required decisions stay visible; technical identifiers and machine
exports are secondary. The short [operator guide](../operations/announcements.md)
uses synthetic practice text and preserves the difference between manual claims and
provider evidence.

## Verification at this milestone

- The complete combined database-free suite passed **13,806 cases in 75.81s**.
  Three existing Django URLField deprecation warnings remain.
- **108 frontend tests** passed; type checking and regenerated OpenAPI/TypeScript
  adoption choices passed. No Announcements REST authoring endpoint is claimed.
- **33 foundation/native cases** passed in 608.61s, including actual password-auth
  runtime setup, two operator acceptances, activation, settings, exact draft retry,
  self-review refusal, independent approval, publication report and private export.
  All 25 runtime-role predicates passed. Historical graph checks dominated that
  batch; the restricted-runtime workflow itself took 4.856s.
- **27 final Announcements domain/migration cases** passed on a fresh database in
  229.07s. They include real concurrency, stale/retry recovery, native drift,
  append-only history, receipt-to-state consistency, empty uninstall/reapply and
  refusal to reverse retained evidence.
- Full strict Mypy, Ruff/formatting, semantic Python documentation and documentation
  validation passed during feedback; focused source pydoclint also passed. Full
  exact-commit certification and independent hosted acceptance remain pending.

The independent review reproduced three native bypasses where omitted aggregate
writes or a wrongly shaped receipt could still commit. The unpublished integrity
migration now checks both directions of the receipt/aggregate graph while allowing
multiple valid commands in one transaction. Failed probes and final passing evidence
are retained; none of the rejected writes is presented as passing acceptance.

Browser feedback also repaired stale settings binding, exact correction retry,
removed-destination retry, older report correction, stopped-use reporting links and
the requested-changes continuation. Required markers now stay inside their labels.
Direct Announcements links narrow generic navigation without silently changing the
selected event. Sign-in language no longer refers to internal rehearsals. Nine
focused shared-shell cases passed after a browser finding exposed that `noscript`
alone does not cover a CSP-blocked script environment; navigation now remains
usable until enhancement successfully initializes.

## Synthetic browser evidence

The assistant used two distinct ordinary synthetic operator accounts in Codex's
in-app Chromium browser. First-use event selection, empty inventory, settings,
server-rendered add-channel/add-copy, draft creation, review request, independent
approval and approved text download were exercised. After the native integrity
repair, the original fixture was backed up and rebuilt through fresh migrations;
identical approved text was explicitly seeded through owning commands to resume
that journey, not presented as a second browser-created draft.

With fixture-only `Content-Security-Policy: script-src 'none'`, the final journey
recorded two reports, edited only the website copy, recovered a missing headline
without losing input, requested and independently approved the correction, and
observed only that channel needing an update. Recording the update and correcting
its older report preserved the newer current report. Stopping writing left copy,
history and retrospective reporting usable; an earlier noticeboard publication
was then recorded without reopening writing or review. No external post was made.

The error summary received focus; Tab reached its field link and Enter moved focus
to the invalid headline. Native event selection preserved the copy view. The final
copy page and earlier comparison view had no horizontal overflow at 320, 390, 768,
958, 1,024, 1,280 and 1,920 CSS pixels, with one H1 and one main landmark. The
comparison view had no duplicate IDs. Normal scripts were then restored: the
390-pixel menu opened as a labelled modal by Enter, focused Close, and Escape
returned focus to Open navigation. No warning/error console entries were observed
through the browser tool. The user's Windows animation and zoom preferences were
not changed.

The approved text download contained both exact channel messages and no private
review/rules text. The separate 11,606-byte JSON history download retained the
private correction review and its payload SHA-256 verified. A stale foreign-scope
URL returned only an unavailable message; the signed-out current deep link returned
Sign in without announcement content. Cross-tenant, field-limited and revoked
roles have automated coverage; they were not all independently browser-rehearsed.

Screenshots and downloaded synthetic artifacts remain in ignored local evidence.
The first browser download-event wait stalled in the automation; direct file-link
retrieval subsequently completed and the actual files were verified. CSP blocking
was tested, not a global browser JavaScript-off preference. Native print preview,
200-percent zoom, a specialist screen reader and independent people were not
exercised. This is a bounded synthetic journey, not complete UX-029 acceptance.

## Recovery and evidence custody

Owning migrations introduce eight Announcements relations, its integrity guards
and downgrade fence; additive foundation migrations own setup and authorization.
The v5 runtime closure preserves v4 and adds only the two Announcements-operator
assertion helpers. Provision exact relation/function ACLs with writers stopped.
Reverse only an unused installation through its explicit fences. Retained stores
repair forward or restore a complete consistent database; there is no destructive
self-service uninstall or automatic removal of external posts.

The isolated Programme test overlay follows the new foundation leaves while
retaining all three production-profile definitions and its separate test-only
candidate. Historical capability tests retain frozen catalogs instead of widening
old authority. This batch does not complete or activate Programme issue #48.

Development evidence lives in the ignored `.tools/announcements-development/`
folder. Synthetic credentials and fixture material are excluded from source and PR
text. Earlier failed unit, native and tool attempts remain preserved. Browser
fixtures use only invented `.invalid` accounts and convention data, genuine runtime
credentials and strict base-derived authorization; HTTP loopback is a local UX
boundary, not a production transport claim.

## Remaining gates

Certify one clean exact commit and deliver through the protected PR gate. The
synthetic correction/stopped-use and bounded responsive journey is complete.
Assistant-operated accounts do not establish independent-person comprehension,
specialist accessibility, real organizational policy, production recovery or an
operational go/no-go. Automatic sending, scheduling, emergency overrides, targeting,
images and recipient acknowledgements remain separate future increments.

Adding another optional workflow to an existing edition still needs an explicit
adoption-expansion contract. The next roadmap work must resolve that boundary
before presenting Guidance as an add-on to this same event.
