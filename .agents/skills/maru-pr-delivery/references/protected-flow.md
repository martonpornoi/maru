# Protected delivery flow

Use these checks as patterns, substituting the exact pull-request number,
branch, and commit. Inspect output before moving to the next mutating stage.

## Candidate snapshot

```powershell
git status --porcelain=v1 --branch
git diff --check
git rev-parse HEAD
git ls-remote --heads origin BRANCH_NAME
```

The tree must be clean at the commit used for complete local certification.
The remote head must equal the locally tested commit before hosted results are
attributed to it.

## Pull-request snapshot

```powershell
gh pr view PR_NUMBER --json url,state,isDraft,headRefName,headRefOid,baseRefName,mergeStateStatus
gh pr checks PR_NUMBER
```

Use `gh pr checks PR_NUMBER --watch --interval 30` for a bounded active watch.
Long PostgreSQL shards may run for more than an hour; inspect job-level status
before treating a summary label such as `pending` as a stalled run.

If a check fails, inspect only the failed job first:

```powershell
gh run view RUN_ID --job JOB_ID --log-failed
```

Pin all conclusions to `headRefOid`. A later push invalidates the earlier
candidate result.

## Pull-request description

Use the repository template's six contracts:

1. human outcome;
2. requirement/ADR scope and explicit non-goals;
3. authorization, privacy, audit, migration, recovery, and destructive review;
4. automated and manual evidence;
5. updated maintained documentation and current handoff; and
6. externally meaningful release note or **Not user-visible**.

Do not leave HTML comments or blank bullets in the opening description.

## Post-merge synchronization

First verify GitHub reports the pull request as merged and record its exact
merge commit. With a clean worktree:

```powershell
git switch main
git fetch origin main
git merge --ff-only origin/main
git status --porcelain=v1 --branch
git rev-parse HEAD origin/main
```

Stop on a dirty tree, merge conflict, non-fast-forward requirement, unexpected
remote, mismatched commit, failed required check, or unmerged pull request. Do
not reset, force, delete, or silently discard work to make synchronization
succeed.
