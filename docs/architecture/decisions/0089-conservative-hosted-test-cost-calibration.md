# ADR 0089: Conservative hosted test-cost calibration

- Status: Partially superseded by ADR 0091 for acceptance selection and grouping
- Date: 2026-09-07
- Requirements: NFR-001, NFR-002, NFR-003
- Partially supersedes: ADR 0060's requirement that every scheduling weight is
  a raw file duration from one accepted run

## Context

Programme migrations change the cost of historical migration tests even when
their file inventory is unchanged. PR #82's first hosted run completed six
PostgreSQL shards but cancelled two at the existing 120-minute limit. The same
head passed complete local certification. Refreshing only local durations
balanced native execution, but one proposed shard already contained almost
7,000 seconds of observed hosted work before its unobserved files were counted.
Native and hosted execution costs are not interchangeable.

## Decision

1. Keep the deterministic whole-file partition algorithm, eight isolated
   PostgreSQL shards, serial execution within each shard, all test selection,
   existing timeouts, and combined 90% branch-aware coverage unchanged.
2. Permit an explicitly requested calibration mode in
   `scripts/update_ci_timings.py`. Its baseline must contain every current
   integration file from successful full local certification. A maintainer
   independently verifies the local receipt, hosted run's exact head and base,
   and successful observed hosted jobs. Both supplied head identifiers must
   be identical full lower-case commit identifiers. Arguments and unsigned
   artifacts are cost evidence, never proof of acceptance or authenticity.
3. Accept observations from completed successful hosted jobs even if another
   job in that same run timed out. Reject failed, errored, skipped, incomplete,
   duplicate, split-file, unnamed, or invalid-duration evidence. Each observed
   file must have the exact same complete testcase identities as its baseline.
4. For each hosted job, divide its matched complete files' summed hosted time
   by those same files' summed baseline time. The conservative fallback factor
   is the largest such ratio, bounded below by one. An observed file receives
   the greater of its baseline and hosted durations. An unobserved file
   receives its complete baseline duration multiplied by that factor. Store
   deterministic millisecond-rounded positive weights and require exact current
   inventory coverage before writing the calibrated map.
5. Unstable collection IDs may make a hosted observation unusable. Require a
   deliberate repeatable `--exclude-hosted-file` with an exact path present in
   both evidence sets; no automatic identity normalization or fuzzy matching.
   Validate the entire report before excluding that measurement. The file and
   every baseline testcase remain in execution and receive the conservative
   fallback cost. At least one matched hosted file must remain. Record the
   exact exclusions and reason with the timing refresh.
6. The checked-in map is therefore a scheduling-cost estimate, not a claim that
   all values were literally measured in one environment. Existing direct
   aggregation remains available for complete accepted-run evidence. Hosted
   acceptance still independently tests the new exact head under ADR 0063.

## Consequences

- Calibration preserves every test and can route a targeted selection to full
  acceptance sooner; it does not loosen the targeted runtime budget.
- A balanced cost estimate cannot guarantee runtime on a variable hosted
  runner. Inspect actual results, not projected seconds, before merging.
- A timeout is not permission for blanket retries, extra runners, a larger
  timeout, reduced coverage, skipped tests, or accepting incomplete reports.
- New or changed test inventories require new complete baseline evidence.
  Checkpoints retain exact provenance and measured versus estimated results.

## Alternatives considered

Raw local durations alone were rejected for this repair because observed
hosted work already contradicted their proposed balance. Combining partial
hosted timings without a complete baseline could omit files. Fuzzy matching
randomized testcase IDs could conceal changed cases. Changing test behavior or
the acceptance topology is a separate outcome, not a timing-map repair.
