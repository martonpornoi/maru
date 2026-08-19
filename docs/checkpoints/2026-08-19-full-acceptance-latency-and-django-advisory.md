# Full-acceptance latency and Django advisory correction

Date: 2026-08-19
Status: Local acceptance complete; replacement pull-request acceptance pending
Requirements: NFR-001, NFR-002, NFR-003
Decision: ADR 0061

## Outcome

Pull-request run
[`32254293214`](https://github.com/martonpornoi/maru/actions/runs/32254293214)
restored GitHub execution after the earlier billing block. Its mixed full-quality
job completed static analysis, generated contributor documentation, Django and
OpenAPI contracts, 20 frontend tests, typechecking, and the production bundle.
The final Python audit then rejected Django 5.2.16 for `PYSEC-2026-3717`; the
advisory identifies Django 5.2.17 as the fixed LTS release.

The project floor and lock now select Django 5.2.17. Live `pip-audit` and the
complete Staff Console audit report no known vulnerabilities.

ADR 0061 replaces only ADR 0060's full-certification scheduling shape:

- Python static analysis, warning-fatal documentation, Django/contracts plus
  frontend, and dependency security are four concurrent jobs;
- the security boundary can fail soon after installation rather than at the end
  of a serial mixed job, and PostgreSQL jobs start only after it passes;
- Sphinx uses automatic parallel workers while retaining a fresh environment,
  warning-fatal behavior, and the complete generated site; and
- all 157 integration files use eight measured, deterministic, whole-file
  PostgreSQL shards rather than six.

The recorded weights total 21,213.536 seconds. The eight loads are 2,659.7,
2,650.4, 2,650.7, 2,650.5, 2,650.5, 2,650.6, 2,650.6, and 2,650.5 seconds. This
reduces the estimated integration critical path from approximately 59 to 44
minutes, while full certification starts nine PostgreSQL services instead of
returning to the former thirteen-service design. Change-aware ordinary pull
requests continue to start zero to two services.

The first four six-shard jobs to complete in run `32254293214` took between
56 minutes 45 seconds and 59 minutes 7 seconds. That live result corroborates
the timing map and makes the eight-shard estimate a scheduling projection based
on observed work rather than source-size guesswork.

No acceptance category, integration file, coverage threshold, or
branch-protection result was removed. `Full CI gate` now requires the four
non-database jobs, security-gated unit suite, complete integration matrix, and
combined coverage; the pull-request workflow still exposes one stable
`PR gate`.

## Verification

- Django resolved and synchronized from 5.2.16 to 5.2.17 under the locked
  Python 3.12 environment.
- `pip-audit --cache-dir .pip-audit-cache`: no known vulnerabilities.
- `pnpm --dir frontends/staff-console audit --audit-level high`: no known
  vulnerabilities.
- actionlint 1.7.7: every workflow passes.
- CI workflow and shard contracts: 16 tests pass.
- Eight-shard inventory: all 157 files are assigned once with the measured
  loads listed above.
- Ruff formatting and complete-rule lint: 642 files pass.
- strict mypy: 356 source files pass.
- PyDocLint and semantic docstring validation: 363 production/tooling files
  pass.
- documentation validator: 263 Markdown files and 202 unique requirement
  identifiers pass.
- fresh warning-fatal parallel Sphinx/AutoAPI HTML build: passes.
- complete unit suite: 1,870 tests pass in 59.80 seconds.

## Remaining evidence

The running six-shard workflow predates this correction and cannot certify the
new schedule or dependency lock. Pushing this checkpoint and implementation
will supersede that run. The successor GitHub run remains authoritative for all
eight PostgreSQL shards, combined 90-percent branch coverage, generated
artifacts, and the stable `PR gate`.
