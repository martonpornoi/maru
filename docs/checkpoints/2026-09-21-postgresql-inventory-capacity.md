# PostgreSQL inventory growth without longer checks

The #48 exit bundle's new native negative tests caused the exhaustive-history
planner to outgrow its existing 64-shard ceiling. Complete fast run26 correctly
failed before database execution; no test or historical group was omitted.

`MAX_SHARDS` is now 128. The deterministic planner still selects the smallest
feasible partition, preserves every indivisible group, runs at most eight workers,
and enforces the same one-hour predicted budget, 1.5 slowdown factor and ten-minute
overhead. Local measured headroom and the hosted two-hour kill limit are unchanged.
This adds sequential capacity for a growing inventory, not concurrent containers,
a longer timeout or a promise that checks will run faster. Over-budget indivisible
groups and total capacity still fail closed.

Boundary tests prove 65 and 128 maximal-sized groups fit without changing worker
or time limits; 129 such groups still fail. The real exhaustive inventory plan
also passes. Focused planning/acceptance/migration-order checks: 143 passed in
16.97s. Full exact-commit PostgreSQL certification and protected delivery remain
pending for this bundle.
