# PR #222: align native setup feedback with the accepted task label

Date: 2026-10-25

## Exact failure

Ordinary Auto certification of clean
`6ac89b41db0bed2ac87714832202968e2ce4ede9` failed in shard 48 at
`test_guided_setup_page_explains_the_boundary_and_redirects_to_accountability`.
The test expected **Set up Workforce** while the page correctly rendered
**Set up a volunteer team**, as accepted by UX-031 and the management-shell
page contract in this PR. The one failed case stopped the pool normally.

The attempt passed all 14,433 units and the non-database repository gates.
Forty-eight native shards passed, one failed, seven active shards were
cancelled and 55 were unstarted. No complete native receipt or combined coverage
exists. Wrapper source/head/tree checks and original-resource checks passed;
every task-owned container was removed. All 4,885 original local-CI files and
5,774 original documentation-build files were moved into separate ignored
preservation directories and independently checked with matching SHA-256 hashes.
The failed attempt remains failed.

## Repair and scope

Change only the obsolete expected title string in the existing integration case.
Its fresh-database setup, successful page response, module-boundary explanations,
closed-input refusal, absence of partial edition creation, explicit foundation
creation, accountable-access redirect and remaining independent authority checks
are preserved. The case remains in the ordinary native inventory and full plan.
A targeted search found no other integration assertions for the retired title.

This is test expectation maintenance for an already accepted presentation change,
not a new product decision or a weaker assertion. No application code, role,
permission, migration, history inventory, coverage threshold, timing budget,
worker count or manual-test record changes. Existing ADR 0055 and the UX-031
task-label contract remain authoritative. Maintained demo data is unaffected;
the existing from-empty walkthrough remains the representative journey.

## Verification and continuation

Exercise the complete existing case against one fresh, task-owned PostgreSQL
database, preserving all of its assertions and cleaning up only that resource.
That focused native case passed in 201.58 seconds. Independent readback confirms
the original resources are unchanged and the owned container is absent. An AST
comparison proves the expected title literal is the only executable test change;
all other statements match the failed candidate. Focused Ruff formatting/lint,
documentation policy and whitespace checks pass.

Focused evidence is not certification. Commit the documented repair, then run
the unchanged complete ordinary Auto certification on the new clean exact head.
Preserve draft PR #222, existing human/browser/operational gates and both earlier
failed attempts. Keep source pinned during the run and record its actual result
in the PR and ignored evidence.
