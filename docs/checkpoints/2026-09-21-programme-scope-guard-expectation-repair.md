# Programme scope integrity after terminal-guard composition

Date: 2026-09-21. Test-only repair within #48; not certification, protected
delivery or profile activation.

Full certification of `e3635ab95574ec56ab5d9744f50755698e079458` against
`b056aa253a39df2648752daf35ac5a158a9950d7` stopped after approximately 2h21m.
Fifty-four native shards passed, containing 3,446 cases without failures, errors
or skips. Shard 55 passed 120 cases and failed two error-message expectations in
`test_raw_item_scope_tampering_is_atomic`; its complete job took 1,924.281s.
The new Programme 0022 stop guard correctly rejected a mismatched organization
and edition before the older item guard could report its original scope error.
Neither failed case admitted a write. This was not a timeout or weakened guard.

The pool cancelled its other seven active workers and removed all 62 databases
it had started. Every result retained timing headroom; the longest passing shard
took 2,505.453s (41m45s). All 13,222 certification units and the non-database gates
passed, but there is no successful full receipt or combined-coverage claim.
Preserved evidence is
`.tools/certification-evidence/programme-exit-e3635ab-scope-expectation-failed`;
the outer transcript is `.tools/programme-certification-e3635ab.log`.

The correction retains exact rejection assertions for each mismatched column
and adds a coordinated move of both identifiers into another genuinely existing
scope with its own Programme control and item. That case passes the new exact-
parent lookup but must still fail the original immutable-item guard. All three
cases require PostgreSQL constraint SQLSTATE `23514`, compare the complete before
and after item rows, and retain the original scope/version rollback assertions.
No guard is disabled or replaced; no application source or migration changes.

The entire native Programme database-integrity file passes **20 cases in 180.66s**,
with no failures, errors or skips. Report: `.tools/programme-scope-repair-native-1.xml`.
Its exact task-labelled loopback-only database was inspected, stopped and verified
removed; the report remains. Ruff and formatting pass for the changed test file.
Complete fast unit run41 passes **13,222 cases in 92.10s**, with the three existing
Django URL-field warnings. Maintained documentation validation passes for 693
Markdown files, four repository skills and 215 unique requirement identifiers.

Before another complete certification, the uncompleted groups are receiving
focused diagnostic feedback using a fresh source-bound plan and the unchanged
bounded worker implementation. At most eight databases run; per-shard deadlines,
complete selection validation and cleanup stay intact. These reports are not a
certification receipt, are not combined with older partial runs to claim success,
and do not replace fresh clean exact-head local and hosted acceptance.

Keep #48/#108/#109/#92 open and preserve the prior failure records. The earlier
populated native rehearsal remains evidence of its recorded, unchanged application
and rehearsal source only, not certification of this later test/documentation edit.
