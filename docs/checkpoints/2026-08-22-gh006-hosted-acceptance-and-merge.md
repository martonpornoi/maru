# GH-006 hosted acceptance and merge

Date: 2026-08-22
Status: Complete
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0071
Follows: `2026-08-22-gh006-selected-actions-reconciliation.md`

## Outcome

Pull request 11 completed the authoritative ready-state acceptance required by
GH-006 and squash-merged to `main`. The accepted dependency-review step used
read-only repository authority, the exact reviewed Action revision, and the
existing classification runner and stable `PR gate`. It added no job, status,
runner startup, PostgreSQL service, comment, license decision, or OpenSSF
Scorecard output.

This checkpoint closes GH-006. It records closure evidence only; it does not
change runtime behavior, schema, migrations, deployment, or release state.

## Exact candidate identity

The final pull-request candidate had:

- base `cf0235f103e6d9fcd01bfb29c1032aba7e524938`;
- head `1d7f17a93b689a62260d7a08ed33ade6bc9593e2`; and
- synthetic merge candidate
  `105c9acccf4819f30dd3dc77541b6a1669a963e5`.

The ready-for-review event occurred at `2026-08-21T22:10:33Z`. GitHub labeled
the run with the pull-request head, while the runner checkout log confirms that
it fetched and checked out `refs/pull/11/merge` at the synthetic merge candidate.
Dependency Review separately compared the pull request's base and head through
GitHub's API.

## Dependency-review proof

Ready-state run `32531845794` started at `2026-08-21T22:10:35Z`. Its successful
**Classify changes** job reported `dependency_review=true` and ran:

`actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294`

The Action retained `contents: read`, evaluated runtime, development, and
unknown scopes, and found no introduced vulnerable packages at the configured
moderate-or-higher threshold. License checks remained disabled. This result is
a base-to-head dependency-diff finding, not proof that the whole repository is
vulnerability-free, that unchanged dependencies are safe, or that licenses and
container base images are approved.

## Complete hosted acceptance

Run `32531845794` completed successfully at `2026-08-21T23:08:56Z`. Static
analysis, documentation, contracts, frontend and security checks, unit tests,
all eight PostgreSQL shards, combined coverage, **Full CI gate**, and `PR gate`
passed. Three narrow-route jobs skipped because the classifier selected the
full route; those skips were intentional. No acceptance category was omitted.

Pre-merge managed CodeQL run `32531757710` also passed its Actions, Python, and
JavaScript/TypeScript analyses on the final pull-request head.

## Merge and default-branch readback

Pull request 11 squash-merged at `2026-08-22T05:17:05Z` as GitHub-signed commit
`0d8af128ca29bbfa4daeca41e392694bb39da057`. The final pull-request head,
synthetic merge candidate, and squash merge all have tree
`3e84dde66be774e7b293471c699978f8ed7ba8bc`, connecting the accepted content to
the protected default-branch result without claiming that full acceptance ran
again on the squash commit.

An authenticated post-merge dependency-graph SBOM read returned 294 entries:
108 PyPI packages, 173 npm packages, 12 GitHub Actions, and the root repository
document. This confirms that the merged Action is graph-visible; it does not
expand the bounded dependency-diff result.

Post-merge managed CodeQL run `32553943756` passed Actions, Python, and
JavaScript/TypeScript analysis on `0d8af128ca29bbfa4daeca41e392694bb39da057`.

## Repository verification

- Documentation validation passes for 292 Markdown files and 203 unique
  requirement identifiers.
- A warning-fatal Sphinx/AutoAPI build from a fresh environment succeeds.
- `git diff --check` reports no whitespace error.

## Remaining boundaries

GH-006 does not establish Docker-base, license, release, deployment, recovery,
accessibility, or production approval. GH-002's first `rc.1` rehearsal remains
separate. GH-007's warning-fatal Sphinx publication through GitHub Pages is the
next repository-hardening step.
