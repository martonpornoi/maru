# Programme release initial certification and repair

Date: 2026-09-11
Issue: [#96](https://github.com/martonpornoi/maru/issues/96), under #48
Status: Focused repairs verified; new exact-commit certification and delivery pending

This supplements the [implementation milestone](2026-09-11-programme-atomic-release-kernel.md).
It is not a successful certification receipt, protected merge, activation or
production acceptance. ADR 0096's dormant contract and all #92/#97 gates remain.

## Failed exact candidate

The first clean candidate was
`341f77e8730a88f272d93aaa68d828b99052276e`, tree
`a0cf265bd4b3af61a1dea58de06a5729cc5fb938`, based on protected main
`413997c938de86daa88dc626f70389c5b84af36a`.
`scripts/certify.ps1 -Mode Full` ran with that explicit base and `CI=true`.

All 4,669 unit tests passed. Eight PostgreSQL reports contain 4,136 cases:
4,102 passed and 34 failed, with no errors or skips. Worker durations ranged
from 117m26s to 150m51s. Seven database workers failed; one passed all 531 cases.
The warning-fatal Sphinx build also failed because an unqualified
`ProgrammeCommandResult` return reference resolved to two modules. Later Django,
OpenAPI/frontend gates and combined coverage did not run. No success receipt
was emitted, and no PR or merge was attempted.

The complete ignored `.local-ci` directory, including all selections, reports,
logs, coverage parts and temporary artifacts, was moved intact to
`.tools/certification-evidence/issue96-341f77e-failed-20260911/`. The certification
transcript was copied alongside it. The original checkout stayed clean while
repairs were developed in an isolated task-owned worktree. The certification
script removed its own containers after completion; unrelated resources were
untouched.

## Verified causes and corrections

- Sixteen failures came from one incorrect Scheduling relation fingerprint:
  fourteen baseline drift checks, genuine-runtime readiness and the empty
  Scheduling reverse/reapply check. The pin had been captured from a reused
  development database containing two retired physical column slots.
- A rollback-only probe of the verified empty synthetic dependency-key table
  reproduced the exact old hash after two real drop/re-add cycles. The clean
  hash was restored by transaction rollback. The corrected pin is the clean
  ordinary-migration shape, not a normalization or arbitrary live rebaseline.
  Negative cases reject both one- and two-retired-slot variants.
- Fifteen recovery cases still expected predecessor fences or partial removal
  of empty successors. Ordinary native owner activity now makes the release
  extension used even without a release, conversion, staffing requirement or
  binding. Tests directly exercise each original populated preflight and also
  require the real current migration executor to preserve every recorder and
  guard at the newer top-level fence. Real empty reverse/reapply coverage retains
  host, placement, staffing and Workforce binding table/function removal.
- One audit rollback test patched the old Programme append function rather than
  the successful native Audit mutation boundary. It now fails the real primary
  append and a distinct secondary failure-audit path, preserves the primary
  exception, and verifies domain, witness, audit and event/outbox rollback.
- One PUBLIC-execution fixture supplied the old V3 contract. Both obsolete V3
  and current V4 PUBLIC-only variants now fail safely; every V4 required helper
  has an explicit missing-EXECUTE negative case.
- One raw-write fixture populated only the fifteen original planning tables.
  A closed two-part matrix now checks all twenty-five current Scheduling tables.
  Release rows come from real tracking, native source change, warning,
  independent approval, publication and withdrawal commands. Every table must
  contain a row, reject raw UPDATE and DELETE with SQLSTATE 23514, and retain
  the complete unchanged row. Unknown model additions fail the inventory check.
- The public-copy return type is fully qualified in annotations and its NumPy
  documentation. No warning was suppressed.

Historical membership names and participating owners were updated together.
Existing timing values were not reduced or recalibrated from failed evidence.
No migration SQL, native source guard, runtime grant, authorization rule,
coverage threshold or hosted protection was relaxed.

## Focused repair evidence

The initial clean-database readiness diagnostic reproduced fifteen failures
and six passes in 226.07 seconds. Its native catalog checks passed; exactly
one of twenty-five Scheduling relation hashes differed. After correction:

- 23 readiness cases passed in 32.96 seconds, including genuine-runtime
  `/health/ready`, existing drift cases and both retired-slot negatives.
- 62 recovery/audit/function-privilege cases passed in 1,081.15 seconds.
- Both populated raw-write matrices and the repeated physical restore passed:
  three cases in 46.98 seconds.
- Three final Workforce/expanded empty-roundtrip cases passed in 155.50 seconds.
- 89 contract/runner/timing units and 52 classifier units passed in separate
  database-free runs. The isolated qualified-return Sphinx build passed with
  warnings fatal. Final candidate quality gates remain part of certification.

The final Workforce group repeats one expanded empty-roundtrip case from the
62-case group; these executions must not be added into a unique suite total.
Ignored repair logs and XML use the `.tools/issue96-repair-` prefix. The isolated
database used only synthetic data, a pinned PostgreSQL 17.11 image and tmpfs.

The repeated physical rehearsal used a real `pg_basebackup` with included WAL
and native tar extraction into an exact task-labelled same-image disposable
clone. With the corrected clean-schema pin, it passed readiness, identical
manifest/artifact, new native copy withdrawal, exact retry, one governing
journal entry and unchanged original source. The clone was removed by verified
identity and labels. This does not resolve #97's logical-restore mismatch or
prove provider, production backup/PITR or human acceptance.

## Remaining delivery boundary

Prepare one clean repaired commit, run complete exact-commit local certification,
then obtain that head's independent protected PR gate and CodeQL before the
authorized squash merge. Verify tree equality, reconcile #96/#48 and synchronize
main before the next Programme child. No profile, route, writer or output has
been activated, and deferred human acceptance is not waived.

## Consolidated pre-commit follow-up

The final fast unit sweep initially passed 4,667 cases and failed two outdated
CI owner assertions. They still expected only Scheduling and Venues, although
the repaired historical boundary explicitly involves nine native owners. The
test now checks all nine actual migration graphs and retains both original
owner cases. The complete database-free rerun passed 4,676 tests in 25.68 seconds,
with two pre-existing Django form warnings. Both run logs are retained; this is
not a new full certification or a sum with the earlier focused unit groups.

Repository Ruff lint and formatting passed all 1,026 Python files. Documentation
validation passed 444 Markdown files, four repository skills and 215 stable
requirement identifiers; changed-source NumPy docstring checks passed. The exact
ID/label-verified tmpfs repair container was stopped and automatically removed
after its final database tests. No certification, repair or restore database
remains from this attempt, and no unrelated resource was removed.
