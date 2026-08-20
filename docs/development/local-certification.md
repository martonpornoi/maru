# Local exact-commit certification

Status: Required contributor evidence; GitHub independently verifies pull requests
Last updated: 2026-08-20

## What the gate proves

`scripts/certify.ps1` checks one clean local commit and covers:

- locked Python and Staff Console dependencies plus vulnerability audits;
- Ruff formatting and lint, strict mypy, NumPy docstrings, semantic docstring
  quality, and a fresh warning-fatal Sphinx build;
- Django system and migration drift, production settings, OpenAPI and generated
  TypeScript contracts, and the Staff Console test/type/build boundary;
- every unit and PostgreSQL integration test; and
- combined branch-aware coverage at or above 90 percent.

The test phase uses one unit container and eight deterministic integration
containers. Every integration file stays whole and serial within its shard.
The containers are local Docker resources, not nine GitHub-hosted runners.

## Run it directly

Start Docker Desktop, make the working tree clean, and run:

```powershell
./scripts/certify.ps1
```

The default of eight integration shards fits the current 24-logical-core,
64-GB certifier. A maintainer may lower `-IntegrationShards` for diagnostic
work, but only the default eight-shard command is repository acceptance.

Successful local evidence is written below `.local-ci/` and includes
`certification.json`, JUnit reports, process logs, XML/HTML coverage, and the
generated contributor site in `docs/_build/html`. `.local-ci/` is ignored and
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
GitHub then evaluates the exact head commit through the hosted `PR gate`. Git
hooks can be bypassed and therefore supplement rather than replace GitHub's
active ruleset.

## Public repository trust boundary

The local receipt is useful review evidence, but contributors control their
own machines and can fabricate or omit it. GitHub therefore runs a separate,
fail-closed acceptance path on standard ephemeral hosted Linux runners. The
stable required result is `PR gate`, not a file uploaded from the contributor's
computer.

Documentation-only changes avoid PostgreSQL, ordinary source changes run unit
and bounded affected integration tests, and changes to workflows, dependencies,
models, migrations, settings, security boundaries, or the test harness invoke
the complete eight-shard matrix. This selection is repository policy, not a
contributor assertion.

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
remain read-only except for the manually invoked release boundary.
