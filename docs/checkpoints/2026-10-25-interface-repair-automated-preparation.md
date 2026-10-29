# Interface repair: automated preparation

Date: 2026-10-25

## Outcome and scope

The maintainer asked for continued work that does not need their manual
verification. Protected PR #221 had already delivered Workforce rota portability;
live PR state and preserved exact-tree delivery evidence confirmed that outcome.
Its pre-delivery source checkpoint was not treated as unfinished implementation.

The existing 24 October interface repair is prepared on an isolated branch from
protected `7bd59c0bf1130a7ebc8b202d0f47b2bc26c9182b`. Only the 44 intended
source/documentation files were copied; private runtime settings, credentials,
mail, database dumps, browser checklist storage and launchers were excluded.
The original manual-test sources, running services and all manual records remain
untouched. Source hashes and original feedback are preserved in ignored evidence.
The guide differs from the earlier closeout hash and is freshly checked rather
than inheriting that older documentation result.

The repair retains UX-007/016/024/029/031 and ADRs 0039/0049/0055. It adds no
domain command, authority, migration, runtime grant or profile expansion.
Rollback is a source rollback; no database downgrade or manual-data rewrite
is needed. The existing tenant denial for Alex's second organizer stays intact.

Automated review additionally corrects radio/checkbox group descriptions: a
fieldset refers to its own help/error IDs; help uses the field's stable auto ID
instead of the empty group label target. Django's existing error-list ID is
retained without duplicating it on the wrapper. A two-group invalid-form
regression covers unique IDs and accessible description references. Widget
docstrings now include their actual default arguments; their executable behavior
is unchanged. Changelog notes describe the visible repairs.

## Verification

Fresh final feedback passed all 14,433 database-free units in 86.92 seconds
(eleven existing warnings), all 124 frontend cases, strict Python/frontend
types, Ruff formatting/lint, NumPy/semantic docstrings and documentation policy.
Independent JUnit reconciliation verified unique identities and zero failures,
errors or skips in both suites. Regenerated OpenAPI, TypeScript and normal
frontend build output are byte-identical to all six supplied generated files.
A fresh warning-fatal Sphinx HTML build passed before this results-only append;
documentation policy and whitespace are checked again before commit. These are
development checks, not clean-head native certification or hosted acceptance.

Failed attempts remain separate: one verification command invoked a package without a module
entrypoint; the corrected command exposed two missing docstring defaults. A
new regression first exposed a duplicate error ID in the proposed accessibility
repair; the wrapper ID was removed and all 83 focused input/template cases passed.
Restricted execution also blocked local socket and atomic file-replacement
operations in seven existing units. The fresh unrestricted rerun passed every
case with the same assertions and unreachable unit database address.
No assertion, authority guard or acceptance threshold was weakened.

## Remaining gates

This is draft preparation, not full exact-head certification or protected
delivery. Fresh native acceptance and hosted checks remain required on the final
candidate after tomorrow's browser observations. Recipient-owned invitation
acceptance, Alex's Crew continuation, representative humans, specialist screen
reader, operational ownership and production/recovery evidence remain separate.
No account acceptance, grant, password, test-data or production action occurred.
