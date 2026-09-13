# Budgeted PostgreSQL acceptance candidate

Date: 2026-09-12
Status: Locally implemented; complete measured certification and delivery pending
Requirements: NFR-001, NFR-002, NFR-003, NFR-008
Decision: ADR 0098

## Trigger and bounded scope

The original PR #101 head `35bc135fc2c9d7e7c448b4619dd681b60ac74e15`
passed full local certification: 9,044 Python tests, 64 frontend tests and
90.66% coverage in 2h42m35s. Hosted run `34694008861`, first attempt,
passed fifteen PostgreSQL shards but job `103554400306` exceeded the unchanged
two-hour limit. It is failed acceptance, not a successful delivery.

The maintainer authorized this repair in the same PR, with no push until actual
execution demonstrates substantial headroom. No #99 product scope, historical
test selection, coverage floor, protected gate or runtime limit is relaxed.

## Candidate

- Deterministic complete-group planning selects between eight and sixty-four
  jobs as needed, within a sixty-minute prediction including a 50% slowdown and
  ten minutes of overhead. At most eight databases execute concurrently.
- Local and hosted execution use the same source-bound group assignments. Each
  local shard gets a fresh loopback-only disposable PostgreSQL instance and
  separate temporary directory, logs and coverage. Cleanup targets recorded IDs.
- Incremental setup/call/teardown diagnostics survive interruption without
  claiming success. Missing, failed or skipped execution remains unacceptable.
- A local elapsed duration must still fit a ninety-minute projection after
  the same slowdown/overhead allowance; otherwise no success receipt is issued.
- Validated complete JUnit/selection evidence refreshes all 334 group costs;
  312 also have completed hosted observations. Two explicit hosted-only timing
  comparisons have incompatible parameter IDs: account invitation API and admin
  edition context. Their complete local costs and all tests remain required.
  The provenance sidecar records source commit, base and input hashes.

Initial estimates choose 39 exhaustive jobs at just under sixty conservative
minutes each. These are not measured replacement-run durations or a promise
about hosted runner latency. Smaller jobs reduce timeout exposure, not total
migration work; further total-runtime optimization is a separate measured task.

## Evidence and remaining boundary

All 4,836 unit tests passed in 33.55 seconds. Repository lint/format, semantic
documentation and strict script docstrings passed. Failure-path tests cover
startup, cleanup, deadlines, manifest tampering, complete assignments and bounded
concurrency. No database or product migration is introduced by this repair.

Full clean-commit certification with the new assignments remains required.
Retain its per-shard observed times before deciding whether a push is safe.
Independent protected exact-head GitHub acceptance remains required after that.
Original evidence is preserved outside the disposable certification directory.

Issue #100 follows #99 protected delivery. Human acceptance #92 and logical
restore blocker #97 remain open; this change does not activate Programme.
