# ADR 0098: Budgeted PostgreSQL shard planning

- Status: Accepted
- Date: 2026-09-12
- Requirements: NFR-001, NFR-002, NFR-003, NFR-008
- Partially supersedes ADR 0090 only for fixed shard counts, local execution
  topology and runtime-cost evidence; selection and protected acceptance remain.

## Context

PR #101 passed complete eight-shard local certification, but hosted group 15
exceeded the unchanged two-hour limit. The fixed sixteen-way plan estimated
every group at approximately 103 minutes and enforced no runtime budget.
Local case durations regrouped into that hosted shard totalled about 95 minutes;
completed hosted groups exhibited up to approximately 36 percent slowdown.
Older group costs also overestimated some recent current-schema tests while
underestimating several historical migration tests. An unchanged retry does not
repair this capacity problem.

## Decision

Keep every ADR 0090 current/affected/exhaustive selection, complete collection,
coverage, isolation and protected-merge requirement. Determine shard count from
the selected groups and a conservative duration budget rather than a fixed
sixteen. Preserve at most eight concurrent isolated databases and serial tests
inside each database. Never split a reviewed shared baseline or parameter group.

Use validated measured group costs with a conservative slowdown multiplier and
explicit per-job startup/cleanup reserve. Target at most sixty predicted minutes
per job under the unchanged 120-minute hosted kill limit. An indivisible group
that exceeds the budget, invalid evidence or an infeasible bounded partition
fails planning before expensive fan-out; it does not omit tests or raise limits.

Local certification and GitHub independently compute and verify the same frozen
scope/group manifest and fingerprint from the exact candidate and base. Local
execution queues the planned shards through eight workers, each shard receiving
its own fresh disposable database. A manifest cannot choose a lesser acceptance
scope or replace current source-derived collection. Final coverage requires all
planned shards, with no missing, failed or skipped execution. The execution
runner resolves its required group objects directly from the validated manifest;
it must not repartition after validation. The printed assignment and actual
collection evidence must match that same shard, including every density limit.

Retain exact selection and setup/call/teardown timing records incrementally, so
an interrupted process still leaves diagnostic lower bounds. Only complete
successful reports can establish measured costs; partial or timed-out evidence
never establishes acceptance. Cost refreshes preserve receipt/head/base and
source provenance, reject mismatched/duplicate/missing cases and keep current
and historical ownership distinct. Timing estimates are not trusted receipts.

Certification also evaluates measured per-shard elapsed time with a conservative
hosted slowdown and overhead allowance. A timing-headroom failure prevents a
success receipt and push readiness even when assertions pass. Replan or optimize
before retrying. A successful local receipt still does not replace GitHub's
independent exact-head gate or guarantee a particular hosted runner speed.

## Historical work density refinement (2026-10-09)

Keep at most two complete historical work groups in a budgeted shard, in addition
to the existing cost limit. Raise the minimum partition size only as required by
that capacity. A reviewed shared baseline or parameterized function remains one
indivisible group. The deterministic frozen manifest includes this limit, so local
and hosted planning independently agree on the same assignments and policy.
The 128-shard ceiling, eight workers, estimates, timeout and measured headroom
remain unchanged. Too many groups fail planning instead of dropping work.

The Announcements candidate passed 63 full-run shards before shard 64 reached
its 3,200-second measured limit during final restoration. All three historical
test bodies had passed. The unchanged isolated diagnostic then completed in
2,279.203 seconds. That result supports reducing serial migration density; it
does not establish the sole cause or certify the concurrent plan. The refinement
requires a fresh full run. Partial evidence does not refresh the timing map.

## Consequences

Suite growth changes the number of bounded jobs rather than silently consuming
the remaining timeout margin. Smaller shards reduce the cost and likelihood of
timeout retries; they do not reduce total work and add some startup overhead.
Actual total-time improvements require separately measured optimization of
historical migration work while retaining its real recovery and negative proofs.
No broader concurrent resources, self-hosted execution, production deployment,
automatic retry loop, waived historical case or new merge bypass is authorized.

The repair itself requires complete local and hosted acceptance. Do not push it
on estimates alone: first execute its exact assignments locally and demonstrate
substantial measured headroom, as explicitly required by the maintainer.
