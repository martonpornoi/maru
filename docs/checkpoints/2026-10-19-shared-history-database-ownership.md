# Shared-history database ownership review

Date: 2026-10-19. Requirements: NFR-001, NFR-002 and NFR-003.

## Finding and unchanged reproduction

[PR #218](https://github.com/martonpornoi/maru/pull/218) received an exact-head
Copilot finding on `77525db92cdf0c1ce58801a7d60133d33097e069`: the shared-history
session fixture inferred initialization from a `test_` database-name prefix.
If the configured database already had that prefix and the selection requested
no ordinary database aliases, the fixture skipped creating its test database.
Historical baseline migration and flush could then operate on that configured
database. A name is not ownership evidence.

A database-free probe invoked the unchanged fixture with recorded setup and
teardown calls. With the pinned plugin reporting no aliases, `maru` requested
fresh setup and teardown; `test_demo` yielded with neither. The source hashes
matched before and after. No database was opened, migrated, flushed or dropped;
this proves the faulty decision, not an executed destructive event.

## Repair contract

After the ordinary `django_db_setup` dependency completes, the fixture consults
the pinned pytest-django plugin's same collected-item alias discovery. It creates
the default test database only when that alias was not initialized. Existing
mixed-session ownership is retained. Unit contracts cover prefixed input names,
ordinary fixture/marker discovery, another alias, failed setup, failed history
and visible teardown failures. Native verification must exercise real standalone
and mixed sessions while preserving a synthetic configured-database sentinel.

The four original shared-history modules, every original body and assertion,
rollback guard, full restoration, committed isolation, plan selection, timing
map, one-history capacity, worker/resource limits and protected gates remain.
No product schema, permission, dependency or UI changes. Maintained fictional
demo coverage is unaffected. ADRs 0090 and 0098 continue to govern acceptance.

## Evidence and delivery boundary

The earlier exact candidate passed ordinary Auto exhaustive certification in
21,485.445 seconds: 14,304 units, 5,270 native cases, 386 groups including 111
histories, 111 batches, max eight workers, 91.247876% coverage and timing headroom.
All 111 owned containers were independently absent. The complete 5,761-file local
archive and 13 run metadata files remain hash-preserved.

Hosted run `39203985444` was deliberately cancelled after the review finding.
All jobs reached terminal status: 14 succeeded, 106 were cancelled, three
alternative lanes skipped, and the two aggregate gates failed closed. Six native
batches completed; partial results do not certify the candidate. All 16 available
artifacts and the complete available 316-entry log archive were preserved in a
4,133-file hash manifest. CodeQL analysis succeeded for the older exact head; it
does not establish acceptance of the repair. Review evidence and the unchanged
probe are under the local `ci-cost-review-ownership-20261019` evidence directory.

Focused repaired-source verification, a normal coherent commit, fresh ordinary
Auto exhaustive certification, exact-head hosted acceptance/review and protected
delivery remain pending. No previous receipt certifies changed source. All nine
earlier local exhaustive failures remain failed and preserved. No partial,
failed or diagnostic measurement recalibrates costs.

## Completed focused verification

Both serial native regressions completed against unchanged repaired source.
The standalone selection passed all six original Scope-v2 cases in 712.51
seconds (719.375-second wrapper); the mixed selection passed all 30 cases in
798.58 seconds (805.843-second wrapper). The latter includes all 18 Guidance
foundation cases, six native isolation cases and the six Scope-v2 cases.
All 36 executions, 30 distinct cases and 108 setup/call/teardown phases passed
without failures, errors or skips.

Fresh owned PostgreSQL started with a deliberately prefixed `test_configured`
database and a synthetic sentinel. Read-only observations recorded no ordinary
aliases in the standalone selection and `default` in the mixed selection.
The shared fixture created `test_test_configured` in the former and retained
the already-initialized database in the latter. Configured database OID/owner,
sentinel, non-system relation inventory and server database inventory were
identical before and after; the temporary test database did not remain.

Each run retained the original 1 GiB tmpfs, 2 GiB memory and 3,600-second focused
limit. Every 3,240-entry before/pre-pytest/after/live source inventory matched,
including the diagnostic runner and observer. All 62 artifact hashes, original
selected/collected/JUnit identities and phase order were independently verified.
The common 3,238 tracked/unignored source entries matched between runs. All 49
original shared-history bodies and two original conftest bodies remained exact;
the rollback helper was unchanged. Both exact owned containers were independently
absent, with nine unrelated containers preserved.

The first diagnostic preflight stopped before pytest because its read-only
catalog query needed an explicit PostgreSQL type cast. Its 21 artifact hashes
and unchanged source were verified, and its exact container was confirmed gone.
That failed preflight remains preserved; the corrected diagnostic copies changed
only the catalog cast and run identities, not the candidate implementation.

Ten new ownership contracts and 29 existing migration-helper contracts passed
together: 39 unit tests in 0.76 seconds. Scoped Ruff/format, documentation
validation (764 Markdown files) and whitespace checks passed before this result
update. Combined verification released source at 06:39:40 UTC on October 19,
before status edits and the normal commit. Evidence is retained under
`ci-cost-review-ownership-20261019` and the two `ownership-a2/b2` run directories.

These focused passes do not replace ordinary Auto exhaustive certification,
hosted acceptance, measured pool headroom or protected review. No timing cost was
recalibrated and no new speed claim is made.
