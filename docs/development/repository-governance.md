# Repository governance and collaboration

## Branch workflow

Create work from current `main`, push a focused branch, and open a pull request.
The protected status is `PR gate`; internal jobs may change without weakening
that stable contract. Squash merge is the only permitted merge method, and
merged branches are deleted automatically.

The current sole-maintainer rules require a pull request, successful status,
linear history, and resolved conversations but zero approving reviews. When a
second trusted maintainer is available, change the ruleset to require one
approval and CODEOWNER review. Never add a routine bypass actor.

Deleting 25 or more paths or deleting source, workflows, ADRs, locks, license,
or security policy requires the `destructive-change-reviewed` label. The label
is evidence that the deletion's exact scope was reviewed; it is not permission
to bypass tests.

## Applying repository rules

Reviewed rule payloads live in `.github/rulesets/`. Apply them with an owner
token after GitHub enables repository rules for the current plan and visibility:

```powershell
gh api --method POST repos/martonpornoi/maru/rulesets --input .github/rulesets/main.json
gh api --method POST repos/martonpornoi/maru/rulesets --input .github/rulesets/release-tags.json
```

Verify the rules in GitHub settings and through a harmless pull request before
relying on them. The current private-plan API returns HTTP 403 and requires
GitHub Pro or public visibility; this is an external enforcement blocker, not a
reason to make the repository public prematurely.

## Maintainer settings

Use squash merge, automatically delete merged branches, require immutable action
SHAs, keep Actions permissions read-only by default, and grant write permissions
only to the release job. Dependabot groups weekly Python, frontend, and Actions
updates. The checked-in CODEOWNERS file is ownership discovery even before its
review rule is enabled.

All contributors follow `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
and `GOVERNANCE.md`. Architecture and requirements remain the durable decision
system; GitHub conversation does not silently supersede either.
