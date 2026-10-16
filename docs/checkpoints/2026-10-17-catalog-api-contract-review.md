# API inventory delivery and Catalog edition source review

Date: 2026-10-17 (delivery at 2026-10-16 23:25 UTC)
Scope: protected inventory delivery followed by exactly two Catalog API evidence rows

## Delivered inventory

[PR #215](https://github.com/martonpornoi/maru/pull/215) was protected-squashed at
23:25:17 UTC as `c95bb69fe7b7cc308e030563fbd4856ea5201fd6`. Its parent is
`979de2a0e97bd43a33198e0e46c1237376033b7e`, and tree
`a81bf12fdefd70db4d61e34725f1228d62633ab3` matches certified candidate
`1dfc45e10e418381ba174f88b268f308bb6fbcc3`. The designated clean main checkout was
synchronized by fast-forward only and matched local/remote main and the merge tree.

Ordinary exact Auto certification passed all ten gates in 5,267.127 seconds:
14,285 units, 5,094 native cases, 38 batches, maximum eight workers, 91.13% combined
coverage and measured timing headroom. Native failures/errors/skips were zero.
All 38 owned containers were independently absent. Complete 5,082-file evidence
and hashes were preserved beside the authoritative receipt. The prior candidate's
full evidence remains intact.

Hosted PR run `38978600716` passed the policy-selected documentation lanes;
its unit/native/risk lanes were policy-skipped, not separately run. Exact-head
PR gate check `117237891875` succeeded from app `15368`. CodeQL run `38978598288`
passed its analyses; acceptance check `117234027765` succeeded from app `57789`.
The valid readiness-503 wording finding was corrected, replied to and resolved.
Copilot's 22:59:45 UTC follow-up reported no open issues; it was a commented review,
not independent human approval. Live ruleset `21093924`, no bypass, strict current
base, mergeability and resolved conversations were checked before an exact-head
squash. The inventory heartbeat was deleted after verified delivery.

## Subsequent bounded review

The clean worktree was reused on `codex/catalog-api-contract-review` from the
protected merge, preserving ignored evidence and all other branches/worktrees.
The [two-operation report](../development/catalog-edition-api-contract-review.md)
records only `catalog_retrieve_edition_catalog` and
`catalog_create_edition_catalog`. Its evidence distinguishes source behavior,
schema declaration, focused mocked tests and unproven native HTTP behavior.

Notable observations include profile/self versus platform authority, no explicit
GET collection budget, separately read projection/version/stock, CharField numeric
coercion, a creation digest excluding reason, pre-transaction authorization and
undeclared problem/cache/correlation outcomes. These are review inputs, not new
approved semantics or claims that every possible race or outage was reproduced.
No runtime, schema, tests, permissions, migrations or gates changed.

Five synthetic database-free serializer probes, schema fragments, exact profile
capability membership and source hashes were recorded under ignored
`.tools/catalog-contract-review`. Four existing focused unit files passed
115 cases in 1.64 seconds; all 14,285 units passed in 77.51 seconds using owned
temporary files. Documentation policy (760 Markdown files) and whitespace passed.
No domain service/database or real credential was used by the probes. Final exact
certification remains pending; older receipts do not certify this new candidate.

Requirements INT-001, NFR-002/003/009/013, AUD-001, FUR-005/006 and FIN-007 frame this
review; ADRs 0001, 0003, 0050 and 0056 remain unchanged. The report's next scope is
a two-operation conformance plan with explicit normalization, retry, completeness,
audit, concurrency and failure decisions. Implementation requires its own reviewed
scope and compatibility assessment. Issue #36 stays open.

## Preserved limits

Issue #42's uncommitted Workforce preparation remains in its separate worktree.
The human new-password handoff was not completed before its fixture lease ended;
exact source and cleanup were verified, the expired tab closed and the obsolete
monitor deleted. No restart, seed, alternate credential path or authority workaround
is introduced. No full browser, independent-human or production acceptance is
claimed. Existing demos are unaffected by this documentation review.
