---
name: maru-pr-delivery
description: "Prepare, push, describe, monitor, repair, merge, or synchronize a Maru pull request through the protected GitHub flow. Use for delivery and hosted-check work; do not use for ordinary local implementation or merge anything unless the user explicitly requests that action."
---

# Maru Pull-Request Delivery

Carry one exact branch outcome through Maru's protected collaboration boundary
without weakening acceptance or obscuring what is being merged.

## Respect the requested authority

Distinguish among preparing locally, committing, pushing, creating a pull
request, marking it ready, fixing checks, merging, and synchronizing `main`.
Perform only the stages the user requested or that are ordinary prerequisites
of that requested stage. Never merge merely because checks are green. Do not
mutate repository settings, release, or deploy without separate authorization.

Read [repository governance](../../../docs/development/repository-governance.md),
[local certification](../../../docs/development/local-certification.md), and
the [pull-request template](../../../.github/pull_request_template.md). Use
[the protected-flow reference](references/protected-flow.md) for exact checks
and stop conditions.

## Prepare the candidate

- Confirm the branch began from current `main`, the worktree contains only the
  intended outcome, and unrelated user changes are preserved.
- Review requirements, ADRs, migrations/recovery, generated artifacts,
  documentation, `CURRENT.md`, and checkpoint need.
- Run focused feedback while iterating and the appropriate complete local
  pre-review evidence. Do not describe an unsigned local receipt as GitHub
  acceptance.
- Commit a coherent diff and verify the exact local and remote head after push.

## Complete the pull-request description

Replace every template placeholder. Lead with the human or operator outcome,
then document contract and scope, safety boundaries, migration/recovery,
verification actually performed, remaining gaps, and a truthful release note.
Use purpose names and link directly to maintained requirements, ADRs, page or
module contracts, and checkpoints where useful.

Keep the description current when hosted checks expose and repair another
contract. A description is review evidence, not a diary: summarize failed
acceptance stages and their resolution without pasting logs.

## Treat hosted acceptance as authoritative

Monitor the exact branch commit. On failure, inspect the precise job and log,
reproduce the smallest relevant contract locally, fix the cause, rerun affected
checks, update documentation when behavior or evidence changed, and push a new
exact head. Never lower coverage, delete a test, widen an exemption, or bypass
the stable `PR gate` merely to obtain green status.

Stop when evidence requires new product authority, external coordination, a
destructive-review decision, or a user choice that materially changes scope.

## Merge and synchronize only when requested

Before merge, verify the current exact head, up-to-date mergeability, required
green checks, resolved conversations, and intended squash boundary. After the
user or authorized workflow merges, verify the returned merge commit, switch a
clean worktree to `main`, fetch current `origin/main`, fast-forward only, and
confirm local `main`, `origin/main`, and the protected result match exactly.
