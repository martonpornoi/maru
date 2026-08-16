# Parallel GitHub CI acceptance

Date: 2026-08-16
Status: Initial remote matrix diagnosed; current-commit CI gate is the corrective acceptance authority

## Outcome

Maru's GitHub acceptance candidate is split into independently diagnosable
static, Django/generated-contract, frontend, unit, PostgreSQL integration,
combined-coverage, dependency-security, and stable final-gate jobs. Twelve
isolated PostgreSQL runners replace one serialized four-hour suite without
running schema-mutating tests concurrently inside a database.

This is an operational testing change. It adds no product behavior, authority,
tenant, disclosure, model, migration, API, recovery, or deployment boundary.

## Failure corrected

The first GitHub run reached formatting, Ruff, mypy, documentation, local
Django checks, and migration drift successfully, then stopped at production
settings validation. The workflow carried a second hand-written settings
fixture that no longer included the required invitation encryption key ID,
public key, digest key ID, or digest keyring.

The new Python verifier is the sole fixture for local and GitHub production-
settings checks. It:

- removes inherited `MARU_*` and `DJANGO_SETTINGS_MODULE` values;
- supplies deterministic synthetic public/digest invitation configuration;
- never passes the invitation worker private-key setting;
- runs exact-provenance `false` and `true` in separate subprocesses; and
- exercises both modes while returning the first failure.

The PowerShell wrapper and canonical local check delegate to that verifier.

## Parallel test boundary

The repository-owned shard selector discovers every direct
`tests/integration/test_*.py` file, assigns each whole file exactly once, and
rejects invalid or duplicate inventories. It uses source size as a
deterministic initial weight, distributes largest files to the lightest shard,
and preserves stable path/shard tie-breaking. Measured GitHub durations may
replace the weight proxy later.

Each integration matrix job receives its own pinned PostgreSQL 17.11 service.
Tests remain serialized within the shard; pytest-xdist is deliberately not
used for migration, trigger, concurrency, and historical-schema tests. Matrix
fail-fast is disabled so all failures remain visible.

Unit and integration jobs publish JUnit and hidden partial coverage data for
14 days. A dependent job combines every part and applies the existing branch-
aware 90-percent threshold once to the complete suite. The stable `CI gate`
fails unless static, contract, frontend, unit, every integration shard,
combined coverage, and dependency security all succeed.

The workflow also adds pull-request cancellation for superseded commits,
merge-queue/manual triggers, uv caching, immutable external-action SHAs, and a
digest-pinned PostgreSQL image.

## First remote matrix finding

The first twelve-shard remote matrix completed without accepting the candidate.
Ten PostgreSQL shards passed. Shards 2 and 10 each failed one rendered-copy
assertion that still expected pre-ADR-0055 wording; audit then found one adjacent
selector assertion that was passing only because a success message contained
the retired phrase. The current interface correctly renders **Change
workspace**, the active convention-management-authority explanation, and **My
governance invitations**. No product behavior changed; all three assertions now
pin the intended interface and pass locally.

The longest successful shard completed in 1 hour 22 minutes 51 seconds, and the
second longest in 1 hour 12 minutes 56 seconds. Both fit the new 90-minute
per-shard boundary and demonstrate why the retired 45-minute monolithic job
could not represent the repository's acceptance suite. The diagnostic run is
[GitHub Actions run 31959870679](https://github.com/martonpornoi/maru/actions/runs/31959870679).

## Verification

- The complete unit suite passes 1,841 of 1,841 tests in 56.68 seconds; the
  verifier, shard runner, and workflow contract pass their 18 focused tests.
- Ruff formatting/lint passes over 633 files and strict mypy passes over 356
  source files. The 78-package uv lock is current.
- Both real production-settings modes exit zero. They retain the 18 existing
  deterministic drf-spectacular enum-naming warnings and report no errors.
- YAML loading finds all eight required jobs and all four workflow events.
- The current inventory contains 157 unique integration files. The 12
  deterministic shards contain 12 to 14 files each with source-size weights
  between 257,394 and 258,780 bytes.
- `git diff --check` passes.
- Documentation validation passes over 242 Markdown files and 202 unique
  requirement identifiers.

The current commit's complete corrective GitHub matrix, combined branch-
coverage verdict, and successful stable `CI gate` are authoritative. `CI gate`
must not be promoted as the protected required check until that run is green.

## Remaining testing expansion

Next layers are a bounded Playwright/keyboard/automated-accessibility pull-
request smoke matrix, nightly Python-version/migration/concurrency/visual
matrices, CodeQL/dependency-review/secret-scanning policy, and a release
workflow for clean-build provenance, SBOM/attestation, synthetic restoration,
and production-shaped recovery evidence.

An ephemeral Actions PostgreSQL service does not replace representative
restore/PITR, runtime-login, accessibility, owner, or production-governance
acceptance.
