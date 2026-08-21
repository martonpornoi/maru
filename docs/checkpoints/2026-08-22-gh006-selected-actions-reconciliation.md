# GH-006 selected-Actions reconciliation

Date: 2026-08-22
Status: Live reconciliation complete; hosted proof pending
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0071
Follows: `2026-08-21-gh006-dependency-review.md`

## Outcome

The owner separately authorized one exact live GitHub mutation: add
`actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294`
to Maru's selected-Actions policy, preserve every prior pattern and both broad
trust flags, and independently read back the complete result. No ruleset,
required-status, dependency-graph, Dependabot, or other GitHub setting mutation
was authorized or performed.

The update completed successfully. The live policy now exactly matches the
12-entry `.github/actions-allowlist.json` in pull request 11. This establishes
permission to execute the pinned Action; it is not evidence that the Action has
run successfully on the pull request.

## Fail-closed pre-read

Immediately before the update, authenticated reads established that:

- `martonpornoi/maru` was public, unarchived, and used `main` as its default
  branch;
- Actions were enabled with `allowed_actions: selected` and mandatory SHA
  pinning;
- `github_owned_allowed` and `verified_allowed` were both `false`;
- the live selected policy contained exactly the prior 11 unique immutable
  references; and
- the checked-in candidate contained those same references plus only the
  reviewed dependency-review v5.0.0 commit.

The operation was required to abort on any mismatch. Every desired entry was
validated as an owner/repository reference followed by a 40-character lowercase
hexadecimal commit SHA.

## Authorized update and readback

The selected-Actions endpoint received a whole-list payload containing both
broad trust flags as `false` and the reviewed 12-entry set. No server response
field was replayed into the payload.

Immediate authenticated GETs then established that:

- the parent Actions policy remained enabled, selected-only, and SHA-pinned;
- both broad trust flags remained `false`;
- the live policy contained exactly 12 ordinal-unique immutable references;
- the new dependency-review reference appeared exactly once;
- all prior 11 references remained; and
- the live set matched the checked-in candidate exactly, using an order-
  insensitive and case-sensitive comparison.

A separate read-only verification repeated the repository, parent-policy,
selected-policy, uniqueness, immutability, and exact-set assertions and found no
drift. Pull request 11 remained a draft at implementation commit `23c25a3`.

## Repository verification

- Documentation validation passes for 291 Markdown files and 203 unique
  requirement identifiers.
- A warning-fatal Sphinx/AutoAPI build from a fresh environment succeeds.
- `git diff --check` reports no whitespace error.

## Remaining acceptance

1. Transition pull request 11 to **Ready for review**.
2. Require its authoritative hosted workflow to execute on the synthetic merge
   candidate and verify that dependency review compares the pull request's base
   and head revisions successfully before selected acceptance fans out.
3. Merge only after the stable `PR gate` and every applicable provider-managed
   protection pass.
