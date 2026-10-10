# Checkpoint: Announcements retained migration source pin

- Date: 2026-10-10
- Scope: ANN-007, ADR 0117 and the existing Events setup readiness contract
- Status: Bounded source-pin repair verified locally; fresh full acceptance pending

## Observed failure

PR #210's full local certification at
`c5f053661bd989e5c719c09e5983e513fdc3595d` failed after 721.109 seconds.
All 13,825 database-free unit cases passed in 239.09 seconds and the other
non-database gates passed. Native shard 3 recorded one passing case and 25
Announcements fixture errors because dedicated setup reported unavailable
integrity. The pool stopped the other workers and removed all eight owned
containers. This run produced no successful certification receipt or aggregate
coverage. Its `.local-ci/` artifacts and
`.tools/announcements-development/certification-review-c5f05366/` launcher evidence
remain retained and must be preserved before another run replaces the output.

The review repair truthfully corrected the module and Migration-class docstrings
in Events 0019. Its retained whole-source SHA256 still described the old text,
so `_retained_migration_sources_current()` and the composed source contract were
false while the SQL-derived base contract remained true. The integrity refusal
was correct; the reviewed deployment expectation was stale.

## Reviewed repair and audit

Only the Events 0019 entry in `announcements_setup_readiness.py` changes:

- Previous normalized SHA256:
  `e66794f16f6f142774021d35149ec2182f61f693d9cc41cfa4fe1d74951ef6b2`.
- Reviewed current normalized SHA256:
  `a805f78d4ba073dd9dc43dcb062be374cd58862d9d65ce8928267c7d4473096e`.

Independent AST comparison with previously certified `dccd7dcd` removes only the
two module/class docstrings and finds identical remaining syntax, including every
migration operation and dependency. That operational AST has SHA256
`b0bc9896d146d0fdeade6d8104ca2d899aa88843ce98f89c92803716f49c9e0a`.
No migration operation, native SQL fingerprint, catalog/schema expectation,
runtime grant, adoption manifest or recovery policy changes.

The audit checked old/current whole-source fingerprints for all seven production
Python files changed by the review repair against checked-in source, scripts and
tests. Only this retained Events 0019 pin matched. The repaired readiness module
is not itself retained by another whole-source pin. No bulk hash refresh was
performed. Exact audit details are saved in the original checkout under
`.tools/pr210-source-pin-repair-20261010/`.

## Focused verification

Three new database-free regression cases inspect the actual checked-in retained
migrations and the composed setup source contract without mocking their source,
pins or contract builder. Before repair, the Events 0019 digest and overall
readiness checks failed while the unchanged downgrade migration passed: two
failures, one pass. After repair, the complete focused Announcements unit set and
adjacent retained-source schema checks passed 312 cases in 2.57 seconds.

Focused strict mypy, Ruff lint, formatting, semantic Python documentation and
documentation-reference checks passed. These checks do not establish native
database readiness, native atomicity or complete-repository acceptance. No native
test, full suite, hosted run, push or merge was performed during this repair.

## Next action and retained limits

Freeze and independently review the coherent four-file follow-up. Preserve the
failed exact-head artifacts, then create a new clean commit and run the ordinary
full local certification and independent hosted checks before protected merge.
The earlier successful `dccd7dcd` result does not certify this source. Separate
human, accessibility, operational and production acceptance limits remain open.
