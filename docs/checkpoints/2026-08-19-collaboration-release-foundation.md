# Collaboration and release foundation

Date: 2026-08-19

## Outcome

ADR 0060 establishes protected GitHub flow, a stable change-aware `PR gate`,
six measured full integration shards, release CalVer, and an evidence-bearing
GHCR/GitHub Release path. Community health files, ownership, issue and pull-
request templates, dependency update policy, ruleset payloads, container build,
CodeQL default-setup readiness, release and public-transition runbooks are
checked in.

The timing map was generated from the accepted 12-shard JUnit run
`31964200663`. Every current integration file has a measured duration and the
six-way greedy schedule is approximately balanced. The map remains historical
evidence and should be refreshed from a later accepted full run when suite
shape or duration materially changes.

## Boundaries

No repository visibility, GitHub Release, tag, or container package was created
by this milestone. The release workflow requires a future dedicated release PR
to update `pyproject.toml` to its derived PEP 440 version. GitHub currently
refuses rulesets/branch protection for this private repository on the active
plan; the payloads and application runbook are ready without making the source
public.

Candidate or gold workflow success is not production approval. External
infrastructure, provider, legal/privacy, security, accessibility, load,
restore/PITR, owner, and go/no-go evidence remains mandatory.

## Verification

- Actionlint 1.7.7, Ruff formatting/ALL-rule lint over 642 files, strict mypy
  over 356 source files, strict PyDocLint, semantic docstring validation over
  363 files, and the 261-Markdown/202-requirement validator pass.
- A fresh warning-fatal Sphinx/AutoAPI build, all 1,870 unit tests, all 20 Staff
  Console tests, TypeScript typechecking, and the production frontend build
  pass. Generated contracts and static assets are unchanged.
- Live Python and complete frontend dependency audits report no known
  vulnerabilities. Patched transitive frontend floors are locked through the
  pnpm workspace policy.
- The production container builds, collects 192 static files, runs as UID
  10001 under Gunicorn 23.0.0, and contains the local API-documentation assets.
- The measured timing inventory covers all 157 integration files and balances
  six shards near 3,536 weighted seconds each. Remote full acceptance remains
  the pull request's authority after push.
