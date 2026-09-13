# Local exact-commit certification

Status: Required contributor evidence; GitHub independently verifies pull requests
Last updated: 2026-09-12

## What the gate proves

`scripts/certify.ps1` checks one clean local commit and covers:

- locked Python and Staff Console dependencies plus vulnerability audits;
- Ruff formatting and lint, strict mypy, NumPy docstrings, semantic docstring
  quality, and a fresh warning-fatal Sphinx build;
- Django system and migration drift, production settings, OpenAPI and generated
  TypeScript contracts, and the Staff Console test/type/build boundary;
- every unit and current-schema PostgreSQL test, plus risk-selected history; and
- combined branch-aware coverage at or above 90 percent.

Coverage starts before the PostgreSQL runner initializes Django, using
`coverage run -m scripts.run_postgres_acceptance`. Unit tests retain pytest-cov.
The shared configuration uses two-decimal reporting at the same 90-percent
threshold, so a whole-number rounded shortfall cannot certify a candidate.
The local type-analysis cache lives inside the fresh `.local-ci/` artifact
directory, preventing stale Django model relationships from another branch
from entering exact-commit certification.

The test phase uses one database-free unit process and a bounded local worker
pool executing the same budgeted shard manifest as GitHub. At most eight
PostgreSQL containers run concurrently; each shard receives a fresh database.
The compatibility parameter `-IntegrationShards` now limits worker concurrency,
not the number of planned shards. Current
cases in a file stay together; independently restorable historical functions
may form separate groups, while shared historical baselines stay indivisible.
Each database executes serially. The containers are
local Docker resources, not eight GitHub-hosted runners. An unreachable unit
database URL makes accidental database use fail instead of silently changing
the unit boundary.

## Run it directly

Start Docker Desktop, make the working tree clean, and run:

```powershell
./scripts/certify.ps1
```

Default `Auto` compares the clean head to the resolved `origin/main` commit;
fetch first and pass `-Base EXACT_BASE` for another reviewed comparison.
The local and hosted paths use the same ADR 0090 classification and migration
dependency closure. Global safety/harness changes require exhaustive history;
ordinary code changes no longer require an exhaustive local run. Running on
the base itself fails conservatively to exhaustive mode. Use `-Mode Full` for
explicit complete certification. Pre-review runs require eight isolated databases.

`-Mode CurrentDiagnostic` benchmarks only unit/current-schema PostgreSQL tests
and their unchanged 90-percent combined branch coverage. It skips non-database
quality gates and emits `diagnostic_success`, never certification success. It
cannot replace the required scope for a high-risk diff. Only that diagnostic
mode accepts fewer than eight databases; results from different worker counts
are not comparable whole-suite speedup evidence.

Successful local evidence is written below `.local-ci/` and includes
`certification.json`, JUnit reports, process logs, XML/HTML coverage, and the
generated contributor site in `docs/_build/html`. Receipts record the
exact head, resolved base, historical scope, elapsed time and gates actually run.
Version-3 receipts also record the exact plan fingerprint, total shards,
maximum concurrent databases and measured timing-headroom result. The local
pool retains one resource/result record per shard, incremental timing JSONL,
and `pool-result.json`. Each measured job, including cleanup, must fit a
90-minute conservative projection after a 50% slowdown and ten-minute overhead
allowance; otherwise no success receipt is written. This is substantial margin,
not a guarantee about every GitHub runner. Per-shard selection JSON records
actual collected case identities. `.local-ci/` is ignored and
must not be committed or presented as a cryptographic attestation. The command
deletes only that verified, repository-contained artifact directory and its own
`maru-cert-*` containers.

`scripts/check.ps1` remains useful for a sequential local check. It runs the
same non-database gates and audits, followed by the complete Python suite unless
`-SkipPythonTests` is supplied. It does not replace the isolated certification
receipt.

## Diagnostic whole-file cost calibration

For a cheap current budget/assignment preview without starting PostgreSQL:

```powershell
.venv/Scripts/python.exe -m scripts.run_postgres_acceptance --history all --base EXACT_BASE_COMMIT --plan-only --write-plan .tools/postgresql-plan.json
```

`predicted_seconds` includes the slowdown multiplier and overhead reserve;
`estimated_seconds` in the CLI summary is the raw group-weight sum. The frozen
manifest retains the conservative estimates, every assignment and a normalized
source fingerprint. This command creates no certification receipt and does not
measure runtime. Do not reuse its manifest after changing source or policy.

For the active group-cost refresher (not the old whole-file diagnostics):

```powershell
.venv/Scripts/python.exe -m scripts.update_ci_group_timings --local-evidence PRESERVED_FULL_EVIDENCE --commit EXACT_MEASURED_COMMIT --base EXACT_BASE_COMMIT --destination scripts/ci_test_group_timings.json
```

Optional `--hosted-evidence DIRECTORY` consumes complete passing hosted reports
whose provenance must first be independently verified. Explicit repeated
`--exclude-hosted-file tests/integration/EXACT_FILE.py` omits only an unusable
hosted cost comparison; the full local cost and every test remain required.
Review the generated provenance sidecar and certify the resulting candidate.

ADR 0091 retains the following ADR 0089 tooling for whole-file diagnostics.
It does not update the active group map or choose acceptance scope. Use the
[group timing procedure](../quality/testing-strategy.md#runtime-and-cost-boundaries)
for current risk-selected acceptance, including new Scheduling history.

Preserve complete reports and the exact-head local receipt outside `.local-ci/`
before another certification deletes that artifact directory. Raw JUnit
aggregation remains available with `scripts/update_ci_timings.py`. For a
demonstrated native/hosted imbalance, ADR 0089 also permits conservative
calibration from complete successful local evidence and successful hosted jobs
at the same verified head and base. Independently inspect their provenance;
supplying matching command-line strings does not authenticate an artifact.

```powershell
.venv/Scripts/python.exe scripts/update_ci_timings.py LOCAL_REPORTS TIMING_MAP --hosted-artifact-directory HOSTED_REPORTS --local-commit EXACT_HEAD --hosted-commit EXACT_HEAD
```

Use full lower-case commit identifiers. The calibrated baseline must cover
every current integration file. Reports must be complete and passing without
skips, files cannot be split or duplicated, and observed testcase identities
must match exactly. Successful jobs from a partially timed-out hosted run are
cost observations, not acceptance of that run. Missing observations receive
the largest matched job-group hosted/local ratio, bounded below by one;
observed weights never decrease below either measured duration.

If collection IDs are unstable, explicitly exclude only the unusable hosted
measurement with repeatable `--exclude-hosted-file tests/integration/EXACT_FILE.py`.
Document the exact path and reason. The complete baseline file and every test
remain selected, with conservative fallback cost. Whole reports are validated
before exclusions, and unknown paths or excluding all observations fail.
Neither a projection nor an unsigned receipt authorizes a merge: certify the
new clean head and obtain its independent hosted `PR gate` and CodeQL results.

## Repository-managed push guard

Activate the tracked hook once per clone:

```powershell
./scripts/install_git_hooks.ps1
```

The hook rejects direct pushes to `main`, branch deletion, and non-fast-forward
updates. Work on a feature branch, push it normally, and open a pull request;
GitHub then evaluates the current pull-request merge candidate, derived from
that head and up-to-date `main`, through the hosted `PR gate`. Git hooks can be
bypassed and therefore supplement rather than replace GitHub's active ruleset.

## Public repository trust boundary

The local receipt is useful review evidence, but contributors control their
own machines and can fabricate or omit it. GitHub therefore runs a separate,
fail-closed acceptance path on standard ephemeral hosted Linux runners. The
stable required result is `PR gate`, not a file uploaded from the contributor's
computer.

Documentation-only hosted changes avoid PostgreSQL. Every code PR runs current
PostgreSQL behavior plus the history required by ADR 0090: domain schema changes
add affected owners/dependents and whole-graph recovery; global safety, runtime,
dependency and test-harness changes retain exhaustive history. The hosted
exhaustive and routine paths choose a bounded count from measured group costs
under ADR 0098, with at most eight running at once. Local certification executes
those same independently verified assignments through eight database workers.
This selection is repository policy, not a contributor assertion. See the
[testing strategy](../quality/testing-strategy.md#github-acceptance-topology)
for inventory review, parameterized/shared-fixture grouping and nightly behavior.

Draft pull requests perform only the classifier and locked-input/Actions-policy
preflight and retain an explicitly non-green `PR gate`. **Ready for review**
starts authoritative hosted acceptance. The pull-request workflow does not
repeat that evidence after the protected identical-tree squash reaches `main`;
managed CodeQL still performs its default-branch scan.

Ready pull requests with a graph-visible dependency manifest, lock, or workflow
input additionally run GitHub's revision-diff dependency review inside the
existing classification job. It blocks graph-visible moderate-or-higher
vulnerabilities introduced in runtime, development, or unknown scope before
selected work starts. `Dockerfile` retains broader security routing without
selecting this graph comparison. This adds no job, required status, runner, or
PostgreSQL service; a failure reaches the existing `PR gate` through the
unsuccessful `changes` job.

The local commands cannot reproduce GitHub's dependency-graph comparison API.
Their locked current-tree `pip-audit` and `pnpm audit` checks remain mandatory
and intentionally broader in time: they can catch an unchanged dependency after
new advisory knowledge appears. Dependency review does not cover unsupported
manifests, the `Dockerfile` base image, or deferred license compatibility. A
successful local receipt therefore does not claim that the hosted diff step ran,
and a successful hosted diff does not replace local current-tree evidence.

A pull request can propose changes to its own candidate workflow and classifier.
The current sole-maintainer boundary therefore includes human review of
automation changes; before another person receives write and merge authority,
enable stale-dismissing approval plus CODEOWNER review or add a separately
designed trusted-base policy check.

The persistent `maru-local-certifier` was unregistered before public Actions
were enabled. Do not register a personal or trusted-network machine for public
pull-request execution. A future self-hosted design must be disposable and
separately reviewed.

## GitHub enforcement boundary

The active public-repository ruleset requires a pull request, an up-to-date
successful `PR gate`, resolved conversations, and squash-only linear history;
it rejects deletion and non-fast-forward updates with no bypass actors. Release
tags are immutable under a second active ruleset. Actions are limited to the
exact pinned references in `.github/actions-allowlist.json`, and workflow tokens
remain read-only except for the manually invoked release boundary and the
issues-only, no-checkout stale-label cleanup workflow.
