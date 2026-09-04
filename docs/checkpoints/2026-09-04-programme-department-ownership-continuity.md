# Checkpoint: Programme Department ownership continuity

- Date: 2026-09-04
- Phase: Progressive Programme Operations adoption, runtime inactive.
- Scope: Issue #64 under umbrella #48; PRG-011 and ADR 0084.

## Outcome

Programme call/import ownership and Workforce Department retirement now share
one edition mutex and database enforcement. Both Applications probes execute
independently; a known blocker wins over unavailability. Public errors reveal
no Programme category, count, identifier, payload, or source metadata.

Dedicated commands reassign Draft calls and pristine staged import batches.
Import batch versions advance monotonically and invalidate old previews;
source bindings remain permanent. Imported call ownership follows a contiguous
receipt chain. Exact-ID historical Draft reassignment and Active retirement
require dormant break-glass recovery authority. Existing proposal relationships
and history survive retirement. Expired and orphaned staging remains explicitly
disposable under the separate Edition capability.

Authorization `0023`, Applications `0010` through `0012`, and Workforce `0018`
install the contract and refuse incompatible populated downgrades. Runtime
Programme relations remain SELECT-only. No profile, route, host, review,
Scheduling, publication, or unrelated relationship is activated.

## Evidence and limits

The interrupted implementation was reviewed and resumed from remote main
`25b7a119f25184367a49f5cc00580db2ca5d8988`. Strict mypy passes for 419 source
files. All 2,759 unit tests pass. The initial focused PostgreSQL run passes
261 tests; an additional 12 barrier/recovery cases pass. Final review also
added an exact previous-owner check for import transition receipts and its
forged-source regression, plus imported-call ownership-chain coverage. The
final import/race run passes 29 cases; the corrected failure-envelope assertion
then passes its focused regression, covering all 30 selected cases. Ruff,
semantic docstrings, and documentation validation also pass.
Final focused integration results, complete certification, and hosted PR
acceptance are recorded in the PR delivery evidence for its exact commit.
Those gates must pass before merge; this checkpoint does not claim production
readiness or a supported Programme Operations workflow.

Added verification targets the six raw-write mutex barriers, shared normal
writer locking, independent SQL retirement protection, historical migration
recovery/disposal, scope and disclosure, stale/replay behavior, receipt chains,
rollback, readiness, runtime ACLs, and safe downgrade fences.

## Handoff

Finish this issue through protected squash merge and exact-main synchronization,
then stop as requested. The next separately scoped Programme child is staged
review and accountable decisions. Accepted-item conversion and hosts follow;
Scheduling, staffing, release, continuity, and profile activation remain later.

## Certification follow-up

The first full certification exposed obsolete historical-test assumptions:
Registration rollback targets also selected new Applications migrations that
depended on later Registration state; the Applications ACL restoration test
stopped before the current endpoint; and an older proposal-history test tried
to retire a Department while its call was still Active. The helper now chooses
compatible leaves, with a regression against the real migration graph. ACL
restoration reaches the current endpoint, and the history test explicitly
retires the call before its Department. That history regression passes.

Retained Department resolution and row locking now use a documented, exact-scope,
label-free Workforce query rather than an Applications import of its model.
Both current and retired reference contracts are unit-tested. The combined
repair focus passes all 12 migration, concurrency, and recovery cases. The
obsolete certification run was stopped, its logs retained locally, and its
disposable test databases removed; a fresh clean-commit certification remains
mandatory before protected acceptance.

The next run also exposed a wall-clock-dependent invitation acceptance test at
a 15-minute rate-limit boundary. A controlled boundary crossing reproduces its
unexpected ninth HTTP 400, while a same-window run correctly returns HTTP 429.
The test now fixes its abuse-control clock within one window. No production
rate-limit behavior or assertion was relaxed.
