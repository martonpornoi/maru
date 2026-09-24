# Programme exit bundle: certification preflight repairs

Date: 2026-09-21. Local delivery preparation for #189/#190/#97/#198 and related
#48 prerequisites; not exact-head certification, a protected merge or activation.

The first full attempt targeted `2a41f96490c7e3885adf22137ad111602af492cf` against
protected `b056aa253a39df2648752daf35ac5a158a9950d7`. Its planner selected all 106
historical groups within 370 groups and 70 shards, at most eight databases.
The repository formatting gate failed on three earlier test files. The runner
starts native checks alongside repository gates, so the supported cancellation
marker stopped the already-failed pool after about 227 seconds. All eight started
containers report removed. The unit subprocess passed 13,139 cases in 169.24s,
but this does not make the attempt certified or reusable as exact-head acceptance.
Later formatting-only edits mean no partial native result is attributed to a
fresh candidate.

Failed artifacts are preserved under
`.tools/certification-evidence/programme-exit-2a41f96-static-failed`. The previous
protected PR #195 certification receipt and plan were hash-checked against their
preserved copies before its original `.local-ci` directory was reused.

Preflight now corrects those three formats, three overlong test strings, explicit
NumPy parameter descriptions and private helper error/return contracts. Public
exceptions propagated from helpers remain documented, with narrowly explained
existing-style DOC502 annotations instead of deleting truthful error contracts.
No native migration, guard, permission or behavior changes in these repairs.

Full Ruff/format, NumPy documentation, semantic documentation (814 source files),
strict typing (793 source files) and a warning-fatal fresh Sphinx build pass.
Staff Console typecheck, all 103 frontend tests and the generated build pass;
generated API contracts remain unchanged. Model consistency reports no changes.
Unconfigured local invitation encryption and existing schema enum warnings remain
explicit; this is not production startup evidence. One manual API-generation
invocation omitted `CI=true` and stopped at pnpm's noninteractive prompt; the
correctly configured pinned-pnpm retry passes, with no generated drift.

A separate checkout prepares real existing foreign/sibling scope denials for
#109/P12 without altering the source under certification. Its first native attempt
failed before setup because the fresh checkout lacked its local temporary parent.
The next two exposed an incorrect rehearsal expectation, not a product-policy
defect: an original Maru operator genuinely holds Organization-scoped Events
transition and role-control authority, so a sibling edition's stop preview is
allowed. The corrected expectation verifies the sibling's exact rendered scope;
archive admission remains separately purpose- and edition-scoped. The failed
attempts remain failures. No P12 acceptance is inferred from 20 protocol units;
record the corrected native result separately.

Fresh clean exact-head full local and hosted acceptance remains required after
repairs. The protected gate, original coverage floor, timing headroom and all
historical selection rules remain unchanged.
