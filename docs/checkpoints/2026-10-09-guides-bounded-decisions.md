# Bounded Guides decisions and preserved availability

Date: 2026-10-09\
Status: Implemented in the Guides and Help desk development checkouts;
database-free feedback complete; native and browser acceptance pending

## Human outcome and boundary

People can continue through their own Guides access decisions and history after
more than 100 retained requests. Pages inspect at most 100 participant-owned
candidates plus one locator lookahead, newest first, with signed actor/mode-bound
creation-time and identity cursors. Each disclosed request rechecks its current
original sources. An empty admitted page keeps an explicit next link when
unexamined candidates remain. Bounded menu discovery distinguishes proven
**Guides decisions** from **Check Guides requests**, without invented action counts
or labels from unavailable requests.

The separate setup owner's explicit capacity result produces a generic notice
without blocking independently admitted access decisions. Other owner failures
remain unavailable. Compatible integrity exceptions subclass `PermissionDenied`
but are distinguished from ordinary row denial, including final rechecks. People
with no Guides candidates do not depend on unused Guides readiness for unrelated
personal work.

This implements KNO-013, UX-031 and NFR-013 within ADR 0119. Existing profiles,
roles, authority, native contracts and pin maps are unchanged. The original
unpaged access API and 256-assignment workspace limit remain. No Reading-only
surface, profile, capability or dependency was introduced.

## Recorded database-free evidence

| Checkout | Focused regression suite | Whole unit suite | Git-listed files unchanged during whole feedback |
| --- | --- | --- | --- |
| Guides | 151 passed in 3.35 seconds | 14,090 passed in 122.19 seconds | 3,167 |
| Help desk | 155 passed in 3.38 seconds | 14,314 passed in 131.24 seconds | 3,319 |

Both whole suites had no failures, errors or skips and retained three existing
Django URL-field deprecation warnings. They ran serially with fresh task-local
TEMP/TMP and pytest directories and an unreachable database URL. Whole Ruff,
formatting, mypy, pydoclint, semantic docstrings and documentation validation
passed. Mypy checked 880 Guides and 966 Help desk source files; semantic
validation checked 901 and 987 source files respectively. Formatting checked
1,792 and 1,907 files. Original documentation checks covered 724/730 Markdown
files and 223/228 unique requirement IDs.

Each checkout retains `.tools/guides-decisions-backport/`: `before.json`, original
changed-file backups and `after-source-contracts.json` bind the bounded repair.
All 326 Guides and 340 Help desk captured native/authority files remain
byte-identical; readiness AST comparison preserves every predicate and pin map
apart from the compatible exception declaration, raise and documentation.
Focused evidence is `focused-02.log/xml` in Guides and `focused-01.log/xml` in
Help desk. `whole-feedback-20261009-01/` retains every command, log, JUnit result,
return code and before/after source hash. No tracked file changed during either
whole run; these source bindings precede this documentation follow-up.

The original whole-tree `git diff --check` failed only on CURRENT.md's CRLF line
endings: 201 lines in Guides and 233 in Help desk. That failed evidence is retained.
This follow-up normalizes only CURRENT.md to LF, updates the concise verification
handoff and adds this checkpoint. Separate final documentation and diff-check
results are retained under `final-doc-feedback-20261009-01/`; no whole-run result
or source binding is rewritten.

## Acceptance still outstanding

No database, container, browser or native certification resource was used for
this repair or its feedback. The new authenticated paging, stale-source,
readiness, keyboard and no-script cases in the
[Guides walkthrough](../operations/guidance-maintainer-walkthrough.md) are explicitly
unrun. Help desk's maintained walkthrough also records independent-purpose
coexistence cases. Guides' native ACL recheck, genuine restricted-role workflow
and browser journey remain pending. Help desk's empty native observation pins,
known custody/continuity proof gaps and native/role/browser acceptance remain open.
No production, specialist, independent-person or protected-delivery acceptance is
implied by these checks.
