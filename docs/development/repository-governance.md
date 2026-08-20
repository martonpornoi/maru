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
forward updates with no bypass actors. It also requires CodeQL to report no
error-level alerts and no security alert at medium severity or higher. The
reviewed payload records those thresholds as `alerts_threshold: errors` and
`security_alerts_threshold: medium_or_higher`. Ruleset `21093924` was read back
after the 2026-08-20 update with those exact thresholds, the sole strict
required status still set to `PR gate`, and every prior pull-request and no-
bypass protection intact. The active `v*` tag rule rejects update, deletion,
and non-fast-forward mutation. Verify the complete live rules after every
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
shard reusable matrix. Before that matrix fans out, a lightweight preflight
requires a current `uv.lock` and exact parity between every workflow reference
and `.github/actions-allowlist.json`. `scripts/certify.ps1` remains the required
local pre-review command, but its unsigned receipt is contributor evidence
rather than a server trust boundary. Details are in
[local exact-commit certification](local-certification.md), ADR 0063, and ADR
0064.

## Dependency update policy

Dependabot is security-only for the uv, npm, and GitHub Actions ecosystems.
Each entry uses `open-pull-requests-limit: 0` to suppress routine version-
update pull requests while retaining one grouped security-update rule. Python
uses the native `uv` ecosystem so a security update must keep `pyproject.toml`
and `uv.lock` coherent.

At least quarterly, and before a candidate or gold release when dependencies
have changed materially, a maintainer creates one dependency-maintenance branch
from current `main`. Update Python manifests and `uv.lock` together, frontend
manifests and `pnpm-lock.yaml` together, and workflow SHAs and the exact Actions
allowlist together. Review major runtime and toolchain updates separately when
combining them would obscure compatibility risk. Run `scripts/certify.ps1`
before requesting review; never weaken locked installation or the allowlist to
make an update pass.

These Dependabot and full-acceptance preflight definitions are repository files.
They become the default-branch automation policy only when their reviewed pull
request is merged. A pull request can exercise its own candidate workflow, but
documentation of the candidate does not itself mutate GitHub settings or the
configuration currently present on `main`.

## Maintainer settings

Use squash merge, automatically delete merged branches, require immutable
Action SHAs, keep workflow tokens read-only by default, and grant write
permissions only to the release job. Repository Actions run in `selected` mode;
`.github/actions-allowlist.json` must exactly match every external immutable
workflow reference. The checked-in CODEOWNERS file is ownership discovery even
before its review rule is enabled.

All contributors follow `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
and `GOVERNANCE.md`. Architecture and requirements remain the durable decision
system; GitHub conversation does not silently supersede either.
