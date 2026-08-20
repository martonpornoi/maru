# Repository governance and collaboration

## Branch workflow

Create work from current `main`, push a focused branch, and open a pull request.
The protected status is `PR gate`; isolated GitHub-hosted runners evaluate the
exact submitted commit through the repository's fail-closed change plan.
Squash merge is the only permitted merge method, and merged branches are
deleted automatically.

The current sole-maintainer rules require a pull request, successful status,
linear history, and resolved conversations but zero approving reviews. When a
second trusted maintainer is available, change the ruleset to require one
approval and CODEOWNER review. Never add a routine bypass actor.

Deleting 25 or more paths or deleting source, workflows, ADRs, locks, license,
or security policy requires the `destructive-change-reviewed` label. The label
is evidence that the deletion's exact scope was reviewed; it is not permission
to bypass tests.

Every clone must activate `.githooks/pre-push` through
`scripts/install_git_hooks.ps1`. The hook blocks direct `main` pushes, branch
deletion, and non-fast-forward updates in ordinary Git use. It remains
bypassable by design; the no-bypass GitHub ruleset is the authoritative
boundary. The active public-repository ruleset reports that the current owner
can never bypass it through an ordinary Git operation.

## Applying repository rules

Reviewed desired-state payloads live in `.github/rulesets/`. They were applied
when Maru became public on 2026-08-20. On a new repository, apply them with an
owner token:

```powershell
gh api --method POST repos/martonpornoi/maru/rulesets --input .github/rulesets/main.json
gh api --method POST repos/martonpornoi/maru/rulesets --input .github/rulesets/release-tags.json
```

Do not repeat the POST commands against this repository because that would
create duplicate rulesets. Compare the active rule first and update its exact
identifier when the checked-in desired state changes.

The active `main` rule requires an up-to-date `PR gate`, a pull request, linear
squash history, and resolved conversations; it rejects deletion and non-fast-
forward updates with no bypass actors. The active `v*` tag rule rejects update,
deletion, and non-fast-forward mutation. Verify the live rules after every
visibility, ownership, or plan change rather than trusting this prose.

## Public hosted acceptance

Public pull requests run only on GitHub-hosted standard Linux runners. The
persistent `maru-local-certifier` registration was removed before Actions were
re-enabled, and repository-level self-hosted runner inventory must remain empty.
Fork pull requests receive only read permissions; do not add `pull_request_target`
execution or expose environments, package publication, or repository secrets.

The hosted `PR gate` retains ADR 0060's change-aware boundary: documentation-
only changes avoid PostgreSQL, ordinary Python work runs unit and bounded
affected integration tests, and high-risk paths invoke the complete eight-
shard reusable matrix. `scripts/certify.ps1` remains the required local pre-
review command, but its unsigned receipt is contributor evidence rather than a
server trust boundary. Details are in
[local exact-commit certification](local-certification.md) and ADR 0063.

## Maintainer settings

Use squash merge, automatically delete merged branches, require immutable
Action SHAs, keep workflow tokens read-only by default, and grant write
permissions only to the release job. Repository Actions run in `selected` mode;
`.github/actions-allowlist.json` must exactly match every external immutable
workflow reference. Dependabot groups weekly Python, frontend, and Actions
updates. The checked-in CODEOWNERS file is ownership discovery even before its
review rule is enabled.

All contributors follow `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
and `GOVERNANCE.md`. Architecture and requirements remain the durable decision
system; GitHub conversation does not silently supersede either.
