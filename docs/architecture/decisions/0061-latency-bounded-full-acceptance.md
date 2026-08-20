# ADR 0061: Latency-bounded full acceptance

- Status: Accepted
- Date: 2026-08-19
- Requirements: NFR-001, NFR-002, NFR-003
- Supersedes: ADR 0060 decision 4 only where it fixes full acceptance at six
  integration shards or places every non-database gate in one serial job

## Context

ADR 0060 reduced routine pull-request database use and replaced twelve
source-size shards with six measured-duration shards. That protects the Actions
budget on ordinary changes, but a high-risk change still has approximately
21,214 weighted integration seconds. Six balanced workers therefore place the
critical path near 3,536 seconds before setup and combined coverage.

The full workflow also ran static analysis, contributor documentation, Django
and generated contracts, frontend acceptance, and dependency audits in one
serial job. A newly published Django advisory demonstrated the cost of that
shape: every earlier check completed before the audit reported that Django
5.2.16 required 5.2.17. The mixed job name and one late red result obscured
which acceptance boundary failed.

## Decision

1. Keep change-aware pull-request classification and the stable `PR gate` from
   ADR 0060. No test category is removed or weakened.
2. Split non-database full acceptance into four concurrent jobs: Python static
   analysis, warning-fatal contributor documentation, Django/generated
   contracts plus frontend acceptance, and dependency security. The stable
   `Full CI gate` requires all four results.
3. Run the fresh Sphinx build with its supported automatic parallelism while
   preserving warning-fatal, keep-going, and fresh-environment behavior.
4. Partition all 157 integration files across eight isolated PostgreSQL jobs
   using the same checked-in measurements and deterministic whole-file
   scheduler. Each job remains serial and matrix fail-fast remains disabled.
5. Require the inexpensive dependency-security job to pass before starting the
   PostgreSQL unit and integration jobs. A vulnerable lock therefore consumes
   no database-service minutes. Retain one post-matrix combined-coverage job.
   Successful full certification starts nine PostgreSQL services, not the
   thirteen used by the former twelve-integration-shard design.
6. Keep high-risk classification for dependency, workflow, model, migration,
   security, settings, and test-harness changes. Speed must come from safe
   concurrency and measured scheduling rather than skipped evidence.

## Consequences

- The timing inventory balances eight shards at approximately 2,650 weighted
  seconds each; the one indivisible longest file is approximately 2,660
  seconds. The estimated integration critical path falls from about 59 minutes
  to about 44 minutes, a 25-percent reduction before setup and coverage.
- A dependency advisory can fail the dedicated security job shortly after
  dependency installation instead of waiting behind documentation, contracts,
  and frontend work. Database jobs remain skipped after that failure.
- Full runs use two more PostgreSQL service instances than ADR 0060's
  six-shard design. Ordinary pull requests still use zero to two, so the added
  concurrency is paid only for high-risk changes, manual certification, and
  releases.
- Parallel jobs repeat some dependency-environment setup and may consume a few
  more runner-minutes even though wall-clock feedback is shorter. A successful
  run also waits for the short security preflight before starting PostgreSQL.
  Shared immutable caches limit that overhead without sharing mutable
  environments.
- Job-specific names make failures and timing visible while branch protection
  continues to depend on only the stable aggregate gate.

## Alternatives considered

### Restore twelve integration shards

Rejected because it would again start thirteen PostgreSQL services for full
certification and previously produced poor cost and latency behavior. Eight
measured shards provide a bounded compromise between feedback time and service
fan-out.

### Keep six shards and split only the non-database job

Rejected because the measured integration matrix, not the 12-minute mixed
quality job, remains the full workflow's critical path.

### Skip slow integration files on pull requests

Rejected for high-risk changes because migration, authorization, transaction,
and PostgreSQL behavior are precisely the evidence that full certification is
designed to preserve. The existing classifier already avoids the full matrix
for lower-risk changes.

### Parallelize tests inside one shared database

Rejected because many integration files intentionally exercise migrations,
database roles, global constraints, and concurrent state. Whole-file isolated
database jobs preserve the established correctness boundary.
