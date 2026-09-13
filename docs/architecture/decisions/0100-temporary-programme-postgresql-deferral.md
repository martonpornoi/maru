# ADR 0100: Temporary Programme PostgreSQL acceptance deferral

- Status: Accepted by the maintainer
- Date: 2026-09-13
- Requirements: NFR-001, NFR-002, NFR-003, NFR-013
- Temporarily supersedes ADRs 0090 and 0098 only for development-time database
  execution and database-dependent combined coverage. Their restored full
  acceptance selection, isolation, timing budgets and 90-percent threshold remain.

## Context

The dormant Programme workflow still needs several substantial features. The
maintainer explicitly requested that PostgreSQL checks stop running during this
development phase, while their tests continue to evolve with implementation.
The #100 feature candidate already completed exhaustive local acceptance in
3h36m16s. Preserving that evidence does not make it acceptance of later commits.

## Decision

The tracked `scripts/ci_postgresql_policy.json` owns a closed `required` or
`deferred` mode, version and restoration owner #48. It is changed through the
ordinary protected PR flow, never a label, environment variable or local skip
list. Missing, malformed and unknown policy fails closed.

During deferral, PR classification still records the original required database
path and historical depth, but selects an explicitly named `deferred` execution
path. Every deferred code PR requires locked dependencies, packaging, static
analysis, unit tests, NumPy documentation, warning-fatal Sphinx, static Django
and generated contracts, frontend tests/type/build and dependency audits. The
ordinary destructive-review boundary, dependency review, CodeQL and protected
PR gate remain. PostgreSQL jobs do not start. Database-dependent combined
coverage and timing headroom are unavailable, not zero or passed. The 90-percent
full-acceptance threshold is retained, not lowered to fit unit-only evidence.

Default local certification and the ordinary check command honor the same
policy without requiring Docker. Local exact-commit development evidence uses
`result: postgresql_deferred`, zero database instances and null combined coverage
and headroom. It cannot be represented as a full certification receipt. A
deferred receipt binds its exact head, base and policy hash and lists only the
checks actually run. Scheduled/manual full-workflow selection records deferral
without starting PostgreSQL. The reusable full workflow fails before database
planning while deferred, including when called by Release. Local explicit full
or database diagnostic certification is similarly fenced until restoration.

All integration tests, migrations, historical ownership inventories, negative
constraint/race cases, timing tools and recovery fixtures remain tracked and
must be maintained for every feature. No database execution is required during
this explicitly authorized phase; unexecuted new/changed cases are recorded as
verification debt. SQLite, mocks and unit tests do not establish PostgreSQL
correctness. No fresh timing weights are invented from unexecuted tests.

## Restoration and limits

#48 must restore `mode: required` before Programme activation, integrated
acceptance, director pilot, deployment or release. A unit guard rejects adding
the Programme Operations profile while deferred. Restoring the policy re-enables
the original code/history classification, nightly/full execution and exact
combined coverage gates. Certify the entire final clean candidate with exhaustive
history and measured headroom, then obtain independent hosted full acceptance;
repair every discovered failure before activation. Do not reuse an old receipt
or close #48 to imply that this has happened. #92 and #97 remain separate gates.

This is a consciously reduced development acceptance boundary, not a test-speed
optimization or equivalent assurance. Database, migration, concurrency and
recovery regressions can accumulate and may require significant repair during
restoration. The maintainer accepts that tradeoff to keep dormant feature
development moving. Removing this temporary policy needs no test deletion or
architecture reversal: switch the tracked mode and prove full acceptance.
