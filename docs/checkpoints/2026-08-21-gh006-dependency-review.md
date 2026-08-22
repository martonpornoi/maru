# GH-006 pull-request dependency review

Date: 2026-08-21
Status: Repository candidate; live reconciliation and hosted proof pending
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0071

## Outcome

The repository candidate adds a fail-fast dependency-diff review to the
existing pull-request `changes` job. The pinned v5.0.0 Action runs only for a
ready pull request whose dedicated classifier output marks a graph-visible
manifest, lock, or workflow change. It rejects introduced moderate-or-higher
vulnerabilities across runtime, development, and unknown scopes before selected
acceptance can fan out. `Dockerfile` keeps its broader security routing without
selecting a graph comparison that cannot inspect its container base.

The step keeps `contents: read`, posts no pull-request comment, disables license
enforcement and OpenSSF Scorecard output, and includes patched-version guidance.
It creates no workflow, job, required status, runner startup, or PostgreSQL
service. Its result is already covered by the stable `PR gate` because a
failure makes the required `changes` job unsuccessful.

## Graph and complement evidence

An authenticated read-only dependency-graph export on 2026-08-21 contained 293
packages: 108 PyPI, 173 npm, 11 GitHub Actions, and the root repository
document. Read-only revision comparisons demonstrated that GitHub recognizes
Maru's `uv.lock`, `pyproject.toml`, Staff Console `pnpm-lock.yaml`, and workflow
dependencies.

This evidence does not make dependency review a replacement for current-tree
audits. Pull request 9's initial ready-state run found `PYSEC-2026-3721` in
already-present `pip 26.1.2`; a diff-only control could not flag a version the
pull request did not introduce. Locked installation, `pip-audit`, `pnpm audit`,
Dependabot, exact Action validation, source review, and release SBOM/provenance
therefore remain in force.

The GitHub dependency graph may omit unsupported or unparseable inputs and does
not cover the `Dockerfile` base image. Automated dependency-license enforcement
is deferred until Maru has an accepted compatibility policy; no Action result
is treated as legal approval.

## Immutable Action candidate

The selected Action is
`actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294`,
the verified v5.0.0 release commit. The repository candidate adds that exact
reference as the twelfth checked-in selected-Action pattern while retaining
`github_owned_allowed: false` and `verified_allowed: false`.

The live selected-Actions setting still contains the prior 11 exact patterns.
Adding the twelfth pattern is an external GitHub mutation and remains pending a
separate owner authorization, authenticated pre-read, exact update, and
complete post-change readback. Repository acceptance does not itself authorize
that mutation.

## Repository verification

- All 68 focused workflow and classifier contracts pass.
- The complete database-free unit suite passes all 1,958 tests.
- Ruff check and format verification pass for the changed Python contracts.
- The Actions-policy validator finds exactly 12 immutable references, and
  Actionlint reports no workflow diagnostic.
- `uv lock --check` preserves the 108-package resolution without changing the
  lock.
- Documentation validation passes for 290 Markdown files and 203 unique
  requirement identifiers. A fresh warning-fatal Sphinx/AutoAPI build succeeds.
- `git diff --check` reports no whitespace error in the candidate diff.

## Remaining acceptance

1. Obtain separate authorization for the live selected-Actions update.
2. Re-read the complete live policy, append only the exact v5.0.0 reference,
   retain both broad trust flags as `false`, and independently read back all 12
   patterns.
3. Run authoritative ready-state hosted acceptance, whose workflow executes on
   the synthetic pull-request merge candidate, and verify that dependency
   review successfully compares the pull request's base and head revisions
   before the selected path.
4. Merge only after the stable `PR gate` and all applicable provider-managed
   protections pass.
