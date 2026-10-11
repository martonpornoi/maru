# Guides integration with delivered contributor workflow

- Date: 2026-10-11
- Requirements: KNO-010 through KNO-013, EVT-008, NFR-001, NFR-002, NFR-003
- Scope: resume the preserved Guides branch after protected workflow delivery.

PR #211 merged as `bc09e8b63e4142c712178a067a123c61b0924e2f` after all
required hosted checks and CodeQL passed. Its tree matched the certified source;
the clean main checkout was fast-forwarded. There were zero review threads and
no submitted reviews; this does not claim a Copilot review occurred.

Guides retained an earlier Announcements source commit, while protected main
received a squash. The ordinary merge produced overlapping historical conflicts
and was aborted from a clean checkout. A source-baseline merge using `633fab4`
reduced the actual conflicts to six files. The merge retains both parent histories,
all later main fixes, Guides combined admission and its unchanged successor pin.
Announcements documentation keeps the combined-profile contract; CURRENT and
ROADMAP reconcile delivered work. OpenAPI and the TypeScript client were regenerated.
No original fixture, volume, account, stash or other worktree was changed.

Verification: 14,239 database-free unit tests passed in 89.10 seconds; strict
application typing passed for 881 files. Full repository lint and formatting
passed; documentation validation passed for 737 Markdown files before this new
checkpoint. OpenAPI validation reported zero errors and 23 existing enum warnings.
The initial frontend generator refused non-interactive dependency preparation;
locked installation with CI=true and regeneration then passed. Complete native
certification of this new source remains pending. Earlier receipts certify only
their respective source, not this integration.

The retained genuine-runtime fixture stays stopped. Its earlier credential-entry
approval refusal remains binding; no browser workaround or authenticated browser
acceptance is claimed. Full browser, accessibility, print and operational evidence
remain distinct unfinished gates. Ongoing/future demo coverage is still incremental;
this integration does not change demo dates or seed contents. Review Guides sample
coverage with the next safely verified browser increment.
