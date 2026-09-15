# PR #139 documentation navigation and quality-budget repair

Date: 2026-09-15. Bounded repair of #113's observed blocker in the active #108
domain-reference PR; no unrelated cleanup, Programme activation or CI-policy change.

## Observed failure

Head `383ca2dab488232e97897f853c0f6a3031386e5e` passed all eight retained local
gates in 1130.706s (18m51s), including 8,160 units in 52.38s. Its schema-4 deferred
receipt and four companion artifacts are archived with verified hashes. Receipt
SHA-256: `d40601fe4703bfe7e25b7fbdadbacf54d1251cbf59fbaf83b1fceec59c64cfd6`.

Hosted run [34992485886](https://github.com/martonpornoi/maru/actions/runs/34992485886)
failed the protected gate. Quality ran 16:03:16–16:33:36 UTC (30m20s including
cancellation cleanup), exhausting its unchanged 30-minute cap. Documentation
passed in 28m01s, 16:04:32–16:32:33; Staff Console acceptance was cancelled at
16:33:31, after build output. That step and PR are not accepted. Hosted units
passed 8,160 cases in 62.68s (1m39s job), and CodeQL passed. No merge, timeout
increase, blind rerun or split-run acceptance exception was used.

The finding is recorded under
[#113](https://github.com/martonpornoi/maru/issues/113#issuecomment-5684131238) and
[#108](https://github.com/martonpornoi/maru/issues/108#issuecomment-5684131569).

## Cause and bounded repair

Installed Furo asks Sphinx for the complete uncollapsed tree with unlimited depth
and hidden entries, then transforms that HTML for each page. The generated
domain-reference API page contained 1,194 sidebar links: 210,890 of 264,678 bytes.
An isolated existing-environment navigation probe measured three actual pages:

| Page | Full tree | Current-section tree | Remaining links |
| --- | --- | --- | --- |
| Domain-reference API | 0.2938s | 0.0128s | 132 |
| Domain-reference page contract | 0.2583s | 0.0062s | 56 |
| Domain-reference checkpoint | 0.2693s | 0.0241s | 270 |

These single samples include Sphinx fragment generation and Furo transformation,
with the Furo cache cleared for each. They are not a full-build benchmark or
guaranteed hosted speedup. No acceptance receipt came from the diagnostic.

ADRs 0058/0074, UX-006/007 and NFR-001/002/003/012 retain complete searchable
documentation behind six curated hubs. The repair applies `collapse=True` through
a page-local Sphinx hook at priority 400, before Furo's priority-500 renderer.
It preserves every other toctree option, current-branch siblings, other hub links,
complete catalog contents, page URLs, search and source-code reference. It does
not monkeypatch dependencies or render an expensive full tree only to hide it.
Other sections open through ordinary catalog links without requiring JavaScript.

## Verification and remaining acceptance

Nine targeted cases and existing documentation-policy regressions passed during
iteration (28 tests). They cover actual Furo override behavior, unchanged options,
page-local scope, failure propagation and a real warning-fatal fresh miniature
Sphinx build. Its sibling/current links, cross-section catalog, every source page
and search entries remain present. Lint feedback is repaired without waivers.

Complete database-free feedback then passed **8,169 tests in 55.27s**, with three
existing URLField warnings. Whole-tree Ruff and 1,280-file formatting passed;
documentation validation passed 558 Markdown files, four skills and 215 requirement
identifiers. Exact-commit local certification, the real site's browser navigation
check and independent hosted acceptance remain required. No
published full-build speedup or restored margin is claimed yet. The failed head's
receipt cannot certify the repair. PostgreSQL remains deferred; no schema exception
or full/native coverage claim is introduced. #108/#48 remain incomplete.

Recovery is an ordinary source/configuration fix-forward; no data, page, history,
schema or artifact retention is deleted. Do not respond to another timeout by
weakening warnings or extending the cap. Keep all future measured timing evidence
bound to its exact head.
