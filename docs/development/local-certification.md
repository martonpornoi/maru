# Local exact-commit certification

Status: Required contributor evidence; GitHub independently verifies pull requests
Last updated: 2026-09-07

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

The test phase uses one database-free unit process and eight deterministic
integration processes backed by eight isolated PostgreSQL containers. Current
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
generated contributor site in `docs/_build/html`. Version-2 receipts record the
exact head, resolved base, historical scope, elapsed time and gates actually run.
Per-shard selection JSON records actual collected case identities. `.local-ci/` is ignored and
must not be committed or presented as a cryptographic attestation. The command
deletes only that verified, repository-contained artifact directory and its own
`maru-cert-*` containers.

`scripts/check.ps1` remains useful for a sequential local check. It runs the
same non-database gates and audits, followed by the complete Python suite unless
`-SkipPythonTests` is supplied. It does not replace the isolated certification
receipt.

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
exhaustive path uses sixteen smaller groups with at most eight running at once;
routine paths use eight. Local certification always uses eight isolated services.
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
