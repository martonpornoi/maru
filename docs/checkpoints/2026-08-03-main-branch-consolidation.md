# Main branch consolidation

Date: 2026-08-03

## Outcome

`codex/full-platform-consolidation` became the canonical `main` branch locally
and on `origin`.

The following redundant local branches were deleted only after Git ancestry
checks proved that each tip was completely contained in the consolidation
branch:

- `main` at `17b68a2`;
- `codex/production-consolidation` at `17b68a2`;
- `codex/page-04-create-convention-series` at `327a7d6`;
- `codex/page-03-organization-record` at `cc1ae91`;
- `codex/page-02-create-organization` at `02d8d15`;
- `codex/page-01-platform-home` at `c96ea01`;
- `codex/page-by-page-rebuild` at `db5af58`; and
- `codex/pre-reset-20260731` at `548f15a`.

The consolidation tip was `c7287ef`, 19 commits ahead of the previous
`origin/main` tip `ca37acb`. The remote update was a fast-forward, not a forced
rewrite.

## Preserved history

The remote archive branches were retained:

- `origin/legacy/local-final-2026-07-29` has three commits not contained in
  `main`;
- `origin/legacy/github-main-462e7ba` has two commits not contained in `main`.

They are historical reference inputs, not active development branches.

## Working-tree safety

The existing uncommitted Page 10 corrective work and the local synthetic
dataset were preserved. No files were reset, stashed, discarded, or rewritten
as part of branch consolidation.

## Verification

- refreshed all remote refs with `git fetch --all --prune`;
- compared every local and remote branch with `git rev-list --left-right`;
- proved each deleted local ref was an ancestor of the consolidation branch;
- fast-forwarded `origin/main` from `ca37acb` to `c7287ef`;
- retained both non-contained remote archive branches.

## Next action

Stabilize and independently accept the uncommitted Page 10 corrective work
before creating the next ordinary `main` commit.
