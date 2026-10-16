# Current project state

Last updated: 2026-10-17
Phase: API inventory delivered; bounded Catalog edition API source review completed locally, awaiting exact delivery checks. Workforce browser acceptance remains blocked.

Maru is a Django/PostgreSQL modular monolith under synthetic evaluation, not a
production-ready service. Follow [ROADMAP](ROADMAP.md) and the owning requirements.
Keep one active delivery and preserve unrelated worktrees, stashes and evidence.

## Last completed outcome

[PR #215](https://github.com/martonpornoi/maru/pull/215) delivered the source-pinned
[240-operation API inventory](../development/api-contract-inventory.md). Protected
squash `c95bb69fe7b7cc308e030563fbd4856ea5201fd6` has exact certified tree
`a81bf12fdefd70db4d61e34725f1228d62633ab3`; designated clean main was synchronized
with a fast-forward only. All ten ordinary Auto gates passed the corrected exact
head in 5,267.127 seconds: 14,285 units, 5,094 native cases in 38 batches, at most
eight workers, 91.13% coverage and measured timing headroom. All 38 owned containers
were independently absent; complete 5,082-file evidence was hash-preserved.

Exact-head hosted PR gate from the required app and CodeQL analyses/acceptance
passed. One valid Copilot wording finding was corrected and its conversation
resolved; the follow-up review reported no open issues. Current base, no-bypass
ruleset and mergeability were verified before exact-head squash. The completed
inventory monitor was deleted. See the
[delivery and review checkpoint](../checkpoints/2026-10-17-catalog-api-contract-review.md).
This inventory does not close issue #36 or establish runtime safety from schema
metadata. No endpoint, schema, permission, test or gate changed.

PRs #210–214 remain delivered. Broad home issue #35 stays open. The earlier home
archive audit-guard rejection remains unexplained and unreproduced, not fixed;
complete failure evidence, diagnostics and final local/hosted acceptance remain
preserved. Investigate recurrence precisely without blind retry. Old paused
monitors stay paused. Fictional demos grow incrementally, with no
all-workflows-prefilled claim.

## Current bounded outcome

The [Catalog edition API review](../development/catalog-edition-api-contract-review.md)
completes exactly two source-evidence rows for issue #36: edition catalog GET and
POST. It records self versus staff/platform authority, exact adopted profile,
input normalization, projection, retry identity, mutation evidence, failure/cache/
correlation behavior, consumers and test limits at the delivered main revision.
Requirements INT-001, NFR-002/003/009/013, AUD-001 and the Catalog product requirements
apply; accepted ADRs 0001/0003/0050/0056 remain unchanged. No new behavior or
architecture policy is accepted by this review.

The source review identifies explicit follow-up decisions: GET completeness and
authority timing, its audit obligation, string/currency coercion, reason-excluding
retry identity and safe declared failures. Five database-free serializer probes
and exact schema/profile/source checks were recorded. The four existing focused
unit files passed 115 cases in 1.64 seconds; all 14,285 units passed in 77.51
seconds. Documentation policy (760 Markdown files) and whitespace passed.
This is not native HTTP, concurrency,
recovery or human acceptance. No runtime, schema, dependency, permission, original
test or gate changed; demos are unaffected. Exact candidate certification and
hosted acceptance remain pending.

## Preserved Workforce blocker

Issue #42's tutorial, route checks, read-only inspector and dedicated empty browser
launcher remain uncommitted in the separate `codex/workforce-rehearsal` worktree.
Eight owner native cases, four inspector native cases, 70 focused units, startup
smoke and standard warning-fatal Sphinx passed there. Its browser run exercised
platform sign-in, three ordinary invitation deliveries and Workforce-only setup;
all 223 unadopted model counts remained zero at that intermediate point.

The browser tool required human entry/submission of new recipient passwords. The
handoff was not completed before the four-hour lease ended at 18:40:20 UTC. Exact
owned container/listener absence and all 3,239 unchanged source files were verified;
the expired tab was closed. Partial public evidence and private fixture files stay
preserved. Guide labels and a partial checkpoint were updated in that branch.
Its obsolete monitor was deleted. No account activation, controller grant,
Workforce lifecycle, final absence report or independent-human acceptance is claimed.

Do not restart or seed accounts to evade that handoff. Resume only when recipients
can perform credential and governed-role handoffs in a new bounded fixture, then
complete the real-clock journey and all remaining acceptance. Issue #42 stays open.
No files from that unfinished branch are folded into this documentation delivery.

## Smallest next actions and limits

1. Finish documentation checks and review, commit this coherent two-operation
   source review, and run ordinary exact-head certification against current main.
   Preserve all previous receipts and evidence before the fresh run.
2. After exact local success, push normally, open and attach a full-template PR,
   resolve valid review findings and obtain exact-head hosted PR gate/CodeQL
   acceptance. Recheck current base, all conversations and mergeability before
   authorized protected squash and ff-only synchronization of designated clean main.
3. Keep issues #36 and #42 open. The next proposed API scope is the two-operation
   conformance plan, with explicit unresolved behavior and acceptance criteria;
   do not silently convert this source review into endpoint changes.

Preserve unrelated checkouts, stashes, stopped fixtures, private credentials and
all failed/passing evidence. No deployment, external mail, account/authority
workaround, security relaxation or additional agent is authorized by this slice.
