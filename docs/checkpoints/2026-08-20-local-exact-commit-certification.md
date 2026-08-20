# Local exact-commit certification foundation

Date: 2026-08-20
Status: Repository contract locally verified; first exact-commit `PR gate`
pending publication of the candidate

## Outcome

ADR 0062 replaces Maru's billed pull-request matrix with one GitHub-recorded
job on the repository-scoped `maru-local-certifier`. GitHub reports that runner
online and idle with the exact `self-hosted`, `Windows`, `X64`, and
`maru-certifier` labels.

`scripts/certify.ps1` binds acceptance to a clean Git commit. It runs the
complete static, NumPy documentation, Sphinx, Django, generated-contract,
frontend, advisory, Python-test, and combined-coverage boundary. Unit tests and
eight measured integration shards use nine separate local PostgreSQL
containers so migrations, server-global roles, triggers, historical schemas,
and concurrency tests retain their established isolation.

Pull-request and reusable full workflows now expose only `PR gate` and
`Full CI gate` on that local runner. They upload JUnit, logs, combined coverage,
the JSON exact-commit receipt, and contributor HTML for seven days. No GitHub-
hosted pull-request job repeats Ruff or starts PostgreSQL.

The tracked pre-push hook is active in the current clone. It blocks direct
`main` pushes, remote branch deletion, and non-fast-forward branch updates.
Mass or protected-path deletion still fails before certification without the
`destructive-change-reviewed` label.

## Verification

- actionlint 1.7.7 accepts every workflow with the checked-in custom-runner
  label configuration.
- The workflow/change-classifier contract batch passes 19 of 19 tests.
- Ruff formatting and all-rule lint pass over 642 files; strict mypy passes 356
  source files.
- Documentation validation passes 265 Markdown files and 202 unique
  requirement identifiers. Strict PyDocLint and semantic validation pass 363
  production/tooling files. A fresh warning-fatal Sphinx/AutoAPI build succeeds.
- Python and frontend audits report no known vulnerabilities. Django migration
  drift is zero, both production-settings modes pass, OpenAPI generation has
  zero errors and the 18 existing enum-name warnings, and generated OpenAPI and
  TypeScript files remain unchanged.
- The first combined Staff Console run exposed a pre-existing async assertion:
  the report heading rendered before its country rows. The test now awaits its
  country, attendee, and role data. The focused rerun passes all 20 tests.
- The digest-pinned PostgreSQL 17.11 image starts healthy through the
  certifier's random loopback-port command and the exact smoke container was
  removed afterward.
- Simulated pre-push input rejects `main` with exit 1 and permits a new feature
  branch with exit 0. Git reports `.githooks` as the active local hook path.
- GitHub's runner API reports `maru-local-certifier` online, not busy, and
  carrying all four required labels.
- `git diff --check` passes.

The full unit/integration/combined-coverage command is deliberately not called
an exact-commit result while these changes are uncommitted. The first published
pull-request run is the acceptance authority for the complete orchestration.

## External enforcement blocker

Both the live rulesets API and classic branch-protection API return HTTP 403:
the private repository requires GitHub Pro or public visibility. Therefore the
reviewed no-bypass payload remains prepared but is not server-enforced. The
local hook reduces accidental damage and the project workflow requires the
green gate, but neither can honestly guarantee that a repository owner cannot
bypass policy on the current plan.

The repository must not be made public merely to remove this blocker. Before a
separately reviewed public transition, the personal persistent runner must be
unregistered and untrusted fork pull requests moved to standard hosted runners
or an approved disposable isolation design.

## Smallest next actions

1. Commit and push this candidate on the feature branch, then inspect the first
   locally executed `PR gate`, container cleanup, coverage result, receipt, and
   documentation artifacts.
2. Apply and verify the checked-in main/tag rulesets after GitHub Pro is enabled
   or during the public transition.
3. Keep the runner offline outside reviewed same-repository certification and
   release windows; restart its hidden process after a workstation reboot only
   when a queued check is expected.
