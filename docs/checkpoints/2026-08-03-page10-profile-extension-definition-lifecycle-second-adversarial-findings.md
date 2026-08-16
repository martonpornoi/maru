# Page 10 profile-definition lifecycle second adversarial findings

Date: 2026-08-03

## Status

Independent review rejected the first corrective candidate after its fresh
36-case focused matrix passed. A direct writer could create a second open
successor from the same active definition by using the next unused version.
The canonical review and activation commands could then activate that
unevidenced branch and strand the first draft. Green command-only tests did not
prove the corresponding model, database, or activation invariant.

This checkpoint is append-only evidence of that rejection. It does not replace
the earlier findings or claim independent acceptance of the repair below.

## Second corrective candidate

- The model rejects a second non-retired successor for one predecessor.
- Migration `0034` adds a partial unique PostgreSQL constraint for that same
  invariant, so raw and concurrent writers fail closed and a populated
  multi-open graph blocks forward migration instead of being guessed into a
  canonical branch.
- Activation independently rejects another open same-key branch and requires
  the exact immutable successor-start receipt, target, audit, event, outbox,
  request digest, actor, predecessor, and setup-version graph.
- Retired profile-definition versions are terminal in the model and database;
  an abandoned retired version remains available as history while the next
  unused version can become the sole new draft.

## Verification so far

- Direct fresh regressions for abandoned-successor replacement, model/raw
  second-open insertion, missing successor-origin evidence, and retired-row
  mutation: **3 passed in 32.17 seconds**.
- A separate populated-forward migration rehearsal proves that `0034` rejects
  an existing two-open graph and succeeds only after explicit retirement
  repair: **1 passed in 24.11 seconds**.
- Focused Ruff formatting/lint and Django migration-drift checks pass. The
  expected development-only invitation encryption warning remains fail-closed.
- A separate reviewer is rerunning the direct adversarial probes and complete
  fresh focused matrix. The configuration-owned adjacent fixture failure is
  tracked at migration `0035` and is not waived as release evidence.

## Remaining gate

Only a new explicit independent verdict can accept this lifecycle. Lifecycle
HTML/API adapters, profile-value commands, stopped-writer activation, browser
and accessibility acceptance, and deployment recovery remain separate work.
