# Current PostgreSQL coverage follow-up

Date: 2026-09-07
Scope: CI issue #83, ADR 0090, NFR-001; no product activation or delivery claim.

The first diagnostic is preserved in the
[original benchmark checkpoint](2026-09-07-postgresql-current-path-benchmark.md).
After starting coverage before Django initialization and enabling two-decimal
reporting at the existing 90% threshold, the diagnostic at
`8fa540cf649937a56855d4098f7ec7647744e439` passed 2,983 unit and 3,002 current
PostgreSQL tests, with no failures, errors or skips. Startup coverage warnings
were resolved. The aggregate correctly failed at 89.56%; no successful
certification receipt was issued. This supersedes any interpretation of the
earlier rounded 90% result as precise acceptance.

The follow-up adds fast current-behavior tests for Programme call constraints,
typed applicant answers, canonical import round-trips, malformed conditions,
deliberate Workforce adoption, interval/time input, typed scope derivation,
invalid signed access tokens, and missing or accidentally activated Programme
catalog declarations. These do not delete, weaken, relabel or replace historical
migration assertions. Authorization grants and database isolation still require
their real PostgreSQL tests; the new scope tests only cover input rejection and
typed scope hints. No production data or product behavior changed.

All 3,224 unit tests pass, including the additional CI policy regressions.
Combined development coverage from those tests and the prior current-schema
PostgreSQL data is 90.02% (58,136 covered statements and 11,684 covered branches
out of 62,659 statements and 14,898 branches). This is an estimate assembled
from separate runs, not exact-head certification. Two existing Django URL-field
deprecation warnings are visible; they are not suppressed or treated as product
changes in this CI task.

Review also corrected two acceptance-support defects:

- A shared mypy cache retained Scheduling model references after changing
  branches. A fresh cache passed all 436 source files and the complete
  non-database quality command on `8fa540c`. Certification now keeps a fresh
  cache inside its per-run artifact directory; unrelated caches are preserved.
- A scheduled selector-only successful workflow could otherwise hide an
  earlier failed exhaustive run. Deduplication now reads bounded latest-attempt
  job metadata and requires exactly one successful Full CI gate bound to the
  expected revision and run. Malformed/incomplete metadata fails closed;
  skipped acceptance is not evidence.

Ruff and whitespace checks pass. Fresh current-only measurement, final complete
local certification, hosted acceptance, protected merge and issue reconciliation
remain pending for this candidate. Issue #81 / PR #82 and its separate branch
remain preserved; its historical migration evidence cannot be bypassed.
The temporary app reminder remains deleted; no scheduler was recreated.
