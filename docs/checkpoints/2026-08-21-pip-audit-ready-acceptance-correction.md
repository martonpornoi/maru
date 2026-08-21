# Pip audit ready-acceptance correction

Date: 2026-08-21
Status: Repository candidate verified locally; corrected hosted acceptance pending
Requirements: NFR-001, NFR-003, NFR-011
Decision: No new ADR; this applies ADR 0064's locked dependency-security policy

## Outcome

Pull request 9's first ready-state workflow run `32501661144` selected complete
hosted acceptance for head `1c140f81c02e4762b9b03401e586f4c6a8ee67f1`.
The workflow exposed one stale transitive development-tool lock entry before
starting the unit and PostgreSQL fan-out. The dependency and lock correction
updates only `pip` from `26.1.2` to patched `26.2.1`; it changes no Maru runtime
dependency, application behavior, workflow logic, or npm package.

## Hosted failure evidence

- `Full dependency security`, job `96832670925`, ran `uv run pip-audit` and
  rejected `pip 26.1.2` under `PYSEC-2026-3721`. The hosted advisory output
  identified `26.2` as the first fixed version.
- `pip` enters the locked development environment only through
  `pip-audit -> pip-api -> pip`. It is not a direct Maru dependency or a
  packaged application requirement.
- The shell stopped after `pip-audit`, so the hosted npm audit did not run.
  Unit coverage, every PostgreSQL shard, and combined coverage were also
  skipped because dependency security is their prerequisite.
- `Full CI gate`, job `96835535246`, and `PR gate`, job `96835561498`, then
  failed deliberately. They are fail-closed consequences of the dependency
  result, not two additional defects.

## Correction

The lock was refreshed with a package-targeted resolver operation. The resulting
`uv.lock` diff changes only the `pip` version, source archive, wheel, hashes,
sizes, and publication timestamps for `26.1.2 -> 26.2.1`. No direct `pip` floor
is added to `pyproject.toml`: promoting an implementation dependency of the
audit tool to a Maru development requirement would add unnecessary coupling.
Locked installs and the mandatory vulnerability audit already enforce the
intended boundary.

`pip 26.2.1` remains a development-only transitive tool and is not included in
the Maru Python distribution or application runtime dependencies. Its installed
wheel metadata declares the MIT license, so the one-package refresh adds no new
package or license category to GH-003's reviewed lockfile boundary.

## Local verification

- `uv lock --check` passes.
- The locked inverse dependency tree resolves `pip 26.2.1` through
  `pip-api -> pip-audit -> maru[dev]`.
- `pip-audit` reports no known vulnerabilities; it separately notes that the
  local editable `maru 0.1.0a0` package is not published on PyPI.
- `pnpm --dir frontends/staff-console audit --audit-level high` reports no
  known vulnerabilities.
- The complete unit suite passes all 1,937 tests in 6.66 seconds, and 47
  classifier/workflow contracts pass.
- Documentation validation passes over 287 Markdown files and 203 requirement
  identifiers. A fresh serial Sphinx/AutoAPI build completes with warnings
  fatal, and whitespace checks pass for the corrected repository candidate.

## Remaining acceptance

Local evidence does not replace GitHub's merge-candidate result. After explicit
publication approval, commit and push the lock plus its CURRENT and checkpoint
documentation. The new ready-state run must complete full acceptance, including
preflight, static analysis, documentation, generated contracts, dependency
security, unit coverage, all eight PostgreSQL shards, combined coverage, and
the final `PR gate`, at the corrected commit before pull request 9 can be
merged.
