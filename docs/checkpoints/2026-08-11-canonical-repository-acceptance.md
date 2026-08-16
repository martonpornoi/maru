# Canonical repository acceptance

Date: 2026-08-11
Status: Repository gate and scoped authenticated read-only Logistics browser
acceptance complete; deployment and production approval not performed

## Outcome

The production-consolidation working tree has one canonical repository verdict.
All 4,067 collected tests passed in the serialized PostgreSQL-backed run, and
the total branch-aware coverage gate passed at 90.78 percent. This supersedes
earlier focused-suite counts as the current whole-tree result without erasing
their milestone history.

An authenticated read-only Logistics journey also passed at 1,920- and
390-pixel viewport widths. That is a deliberately scoped browser acceptance,
not evidence for every module, mutation role, validation/denied/stale state,
keyboard path, or automated accessibility rule.

## Coverage repair and genuine fixes

Registration and Identity received coherent behavior, authorization, lifecycle,
failure, and security matrices to close their branch-coverage gaps. The repair
did not lower the threshold, change coverage configuration, exclude production
code, or add pragma omissions.

The new cases exposed two real product defects:

- Registration setup-definition adapters now handle dependency/database
  failures before the broader setup command-error superclass. An unavailable
  dependency therefore retains the documented `503` response instead of being
  flattened to an ordinary `409` conflict.
- Canonical UUID form validation now accepts the documented lower-case,
  hyphenated, version-agnostic UUID shape while continuing to reject compact,
  braced, upper-case, whitespace-padded, and otherwise aliased input.

## Readiness, API, and migration boundary

- Installed module readiness, exact function/relation ACLs, non-delegable
  runtime-role profiles, tenant/object/field denial, and tamper/fail-closed
  matrices passed within the canonical suite.
- OpenAPI and generated-client/frontend artifacts regenerated deterministically.
  No schema or generated-artifact drift remains.
- Migration generation reports no model drift. The accepted graph keeps
  `venues 0001 -> logistics 0001 -> authorization 0016 -> logistics 0002`,
  places Workforce `0008` after the exact Registration, Applications,
  Charities, Venues, and Logistics Department-FK creators, and makes historical
  Registration targets select the compatible Workforce leaf. Identity delivery
  integrity follows its required reconciliation-audit fence.
- Invitation delivery, expiry, and retention scheduler evidence uses one
  materialized PostgreSQL clock observation, avoiding host/database clock skew.
  Invitation transitions, scheduler success, retention receipts, and terminal
  delivery/disposition evidence are append-only or one-way under both model and
  database guards. Runtime ACLs grant no delete path for that evidence.

The invitation-retention corrective candidate remains disabled pending its
independent verdict, lawful policy/digest, supervised scheduler and alerting,
stopped-writer cutover, load evidence, and backup-expiry/restore/PITR rehearsal.
Canonical repository coverage does not activate that boundary.

## Dependency and concurrency hardening

A live registry-enabled audit found `cryptography` 46.0.7 affected by
`PYSEC-2026-3552`, `PYSEC-2026-3553`, `PYSEC-2026-3554`, and
`GHSA-537c-gmf6-5ccf`. `pyproject.toml` and `uv.lock` now select
`cryptography` 50.0.0, the environment was synchronized, and a repeated live
audit exits zero with "No known vulnerabilities found." The local `maru`
package is skipped only because it is not published on PyPI.

Post-upgrade verification passed the fresh invitation/cryptography matrix at
639 of 639 tests in 219.69 seconds and the full unit suite at 1,815 of 1,815 in
68.62 seconds. Ruff/format remained clean over 624 files, strict mypy remained
clean over 355 source files, Django check emitted only the expected fail-closed
`identity.W001`, and migration generation reported no changes.

Two direct-database concurrency harnesses now insert with one-row `bulk_create`
to bypass model `full_clean` and genuinely race their unique constraints. The
fresh direct pair passes 2 of 2 cases, and the combined repeated stress run
passes 24 of 24 cases across the two probes.

## Verification

- Ruff formatting and lint preflight: 624 files passed.
- Strict mypy preflight: 355 source files passed.
- Test collection: exactly 4,067 tests.
- Canonical serialized suite: 4,067 of 4,067 passed in 15,558.23 seconds
  (4:19:18).
- Total branch-aware coverage: 90.78 percent.
- Migration drift: none.
- Frontend/OpenAPI generation and drift checks: deterministic.
- Live registry-enabled dependency audit after the lock/environment upgrade:
  exit zero, no known vulnerabilities found; only unpublished local `maru`
  skipped.
- Post-upgrade invitation/cryptography matrix: 639 of 639 passed in 219.69
  seconds; full unit suite: 1,815 of 1,815 passed in 68.62 seconds.
- Genuine database-constraint concurrency: 2 of 2 direct cases and both
  probes' combined 24-of-24 repeated stress run passed.
- Authenticated scoped read-only Logistics browser: passed at 1,920 and 390
  pixels.
- Documentation validator: 236 Markdown files and 202 unique requirement
  identifiers valid; the four-file `git diff --check` is clean.

## Remaining release gates

The following remain open and must not be inferred from repository acceptance:

1. Page 10 compatibility-writer retirement, stopped-writer activation, and
   controlled cutover/recovery rehearsal.
2. Broader authenticated browser coverage across mutation roles and complete
   validation, stale, denied, protected, limit, and dependency states.
3. Reliable keyboard traversal and automated accessibility analysis.
4. Representative whole-database restore/PITR, fix-forward, load, and production
   authority/runtime-login activation evidence.
5. Provider/infrastructure certification and named owner, privacy/legal,
   finance, safeguarding, support, and operating-governance approvals.

No production data was used, no deployment or production migration was run,
and no production-readiness claim is made by this checkpoint.
