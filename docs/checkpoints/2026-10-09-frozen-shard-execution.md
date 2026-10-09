# Execute the validated PostgreSQL shard assignments

- Date: 2026-10-09
- Status: Source repair verified; fresh full certification pending
- Basis: NFR-001, NFR-002 and ADR 0098

## Observed failure

Announcements candidate `7cb0a071c53787dbcbd580828e0e487185a4e2c8` generated a
77-shard plan with at most two historical groups per shard. The acceptance runner
validated that complete plan, then independently repartitioned the same required
groups without the density constraint. Its collection evidence therefore did not
match the assignments whose fingerprint and estimates it reported. Neither the
planner-only regressions nor the earlier manifest-validation tests exercised
this divergent execution path.

A read-only comparison found **58 mismatches among 73 started shards**. The run
was cancelled through its supported pool cancellation file. Sixty-five shards had
passed their actually selected cases; eight were interrupted and four never
started. Every owned container was removed. These passing subsets do not certify
the planned assignments, timing headroom, complete coverage or the candidate.

All 4,711 files in the failed evidence tree, totalling 412,455,264 bytes, were
copied and SHA-256 verified before source repair. The console, exact source tar
and per-shard planned/selected comparison are retained alongside them under the
ignored `7cb0a07-plan-selection-mismatch` evidence archive. The plan fingerprint
is `17eb58b5a7f6b67d23999a769dcc3e1ea03824ccf40d229087e4ab27f84ecc98`; its
separate source fingerprint is
`2b8bc2b26cd346ea249467b8aef71e803fd5977c9704cb5305353638171d34fe`.
Earlier failed runs and the isolated timing diagnostic remain preserved.

## Repair and evidence boundary

The runner resolves the already-validated manifest keys to the required group
objects, preserving those exact assignments and order. It no longer partitions
a second time. Summary estimates, the selected collection boundary and recorded
groups consequently describe the same planned shard. Risk selection, complete
collection, indivisible groups, weights/provenance, eight-worker concurrency,
coverage, timing limits and protected acceptance remain unchanged.

The new database-free regression enters the actual main execution path for every
shard of a real budgeted synthetic inventory where constrained and unconstrained
assignments differ. It exercises the real collection hook and compares printed
summary, written selection evidence, retained cases and exact-once total coverage
to the manifest. The original runner fails this regression. This source evidence
does not replace a fresh full certification of the repaired clean commit.

## Completed source verification

The regression and surrounding policy tests pass 122 cases in 19.04 seconds.
The whole database-free suite passes 13,817 cases in 76.20 seconds, retaining
three existing Django URL-field warnings. Full Ruff and formatting checks pass;
canonical `mypy src` passes 827 files, as do Python documentation and reference
checks. An initial ad hoc mypy command incorrectly included the executable script
as a second module root and failed on duplicate module names; that log is retained.
The repository's canonical command passed without a source change.

A separate real CLI check generates all 77 shards and resolves shards 1, 66, 67
and 77 from the saved manifest. All printed selections match, and all 374 group
assignments remain identical to the reviewed density-limited plan. These checks
perform no database execution. Exact implementation hashes remained unchanged
through combined feedback and the CLI check.

## Next gate

Freeze the repair and run complete exact-commit local acceptance. Compare actual collection evidence with the saved plan
early in that run. Only a successful receipt permits the next independent hosted
acceptance and protected delivery steps. Programme #48 remains deferred.
