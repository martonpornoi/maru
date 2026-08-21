# ADR 0071: Fail-fast pull-request dependency review

- Status: Accepted
- Date: 2026-08-21
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011
- Implements: GH-006
- Refines: ADR 0064 decisions 1 and 2 and ADR 0066 decisions 1 and 3

## Context

Maru already installs locked Python and Staff Console dependencies, runs
`pip-audit` and `pnpm audit`, limits Dependabot to grouped security updates,
and validates every external Action against an exact immutable allowlist. Those
controls evaluate the complete candidate tree, but they do not provide an
early, pull-request-specific account of dependencies introduced or changed by
the submitted diff.

The distinction is useful but cannot replace current-tree auditing. Pull
request 9's first ready-state run found `PYSEC-2026-3721` in the already-locked
development dependency `pip 26.1.2`. The pull request had not introduced that
version, so a diff-only review would not have selected it. The retained
`pip-audit` check corrected the lock to `pip 26.2.1` and demonstrates why Maru
must keep both forms of evidence.

An authenticated 2026-08-21 dependency-graph read found 293 packages in Maru's
live graph: 108 PyPI packages, 173 npm packages, 11 GitHub Actions, and the root
repository document. Read-only comparisons also recognized changes from
`uv.lock`, `pyproject.toml`, the Staff Console `pnpm-lock.yaml`, and GitHub
Actions workflows. GitHub dependency review therefore covers material Maru
inputs rather than only a theoretical ecosystem.

The graph still has boundaries. It can omit an unsupported or unparseable
manifest, and it does not represent the container base selected by
`Dockerfile`. Dependency-license compatibility also needs a reviewed Maru
policy and legal context; a generic allowlist would create false confidence and
routine contribution friction.

## Decision

1. Add GitHub's dependency review as one conditional step inside the existing
   `changes` job. It runs only when the pull request is not a draft and the
   fail-closed classifier's dedicated `dependency_review` output is `true`.
   That output covers graph-visible manifests, locks, and workflow manifests,
   but not `Dockerfile`. Drafts keep their classification and
   locked-input/Action-policy boundary unchanged.
2. Fail when a graph-visible dependency introduced by the pull request has a
   vulnerability of moderate severity or higher in the `runtime`,
   `development`, or `unknown` scope. Include patched-version guidance in the
   result. Keep vulnerability checking enabled.
3. Disable Action-based license enforcement until Maru accepts a bounded
   dependency-license policy. Native dependency review and source review may
   still inform a maintainer, but neither is treated as an automated legal
   conclusion. Disable OpenSSF Scorecard output and pull-request comments to
   avoid low-signal duties and write permission.
4. Keep the workflow token at `contents: read`. Do not add a workflow, job,
   runner, required status, PostgreSQL service, or write permission. A failed
   Action step fails `changes`; the existing always-running `PR gate` already
   rejects a non-successful `changes` result before selected work can fan out.
5. Pin `actions/dependency-review-action` v5.0.0 to verified commit
   `a1d282b36b6f3519aa1f3fc636f609c47dddb294` and add that exact reference to
   the checked-in Actions allowlist. The live selected-Actions policy requires
   a separately authorized pre-read, exact twelfth-pattern update, and
   post-change readback before the ready-state workflow can execute it.
6. Retain locked installation, `pip-audit`, `pnpm audit`, Dependabot,
   immutable-Action validation, human manifest review, and release SBOM and
   provenance evidence. Dependency review supplements those controls; it does
   not certify unsupported manifests, container images, license compatibility,
   or the absence of vulnerabilities in unchanged dependencies.

## Consequences

- A ready dependency or automation change receives introduced-dependency
  evidence before full or targeted acceptance starts. An API or Action failure
  fails closed through the established required gate.
- Newly introduced moderate frontend, development, and unknown-scope
  vulnerabilities are blocked even though the retained npm audit threshold is
  high. Current-tree Python auditing remains stricter and catches unchanged
  dependencies when advisory knowledge changes.
- An irrelevant pull request downloads no dependency-review Action. A relevant
  pull request reuses the existing classification runner, so GH-006 adds no
  standalone status, runner startup, or database service.
- `Dockerfile` remains part of the broader `security` classification, but does
  not select the graph-review step. Container-base vulnerability analysis
  remains a separate current-tree and release boundary.
- Local certification cannot reproduce GitHub's revision-comparison API. It
  continues to prove locked current-tree audits, while the hosted ready-state
  run supplies the independent diff evidence.
- The repository candidate is not operationally complete until the live
  selected-Actions policy is reconciled and an authoritative ready-state run
  proves the pinned Action. The workflow executes on the synthetic pull-request
  merge candidate, while GitHub dependency review compares the pull request's
  base and head revisions.

## Alternatives considered

### Rely only on current-tree audits

Rejected because they do not give reviewers a focused introduced-dependency
summary and must install the candidate environment before reporting a problem.
They remain mandatory because diff-only evidence cannot find every current-tree
vulnerability.

### Add a separate workflow, job, or required status

Rejected because it would add runner startup and conditional-status semantics.
Keeping the step in `changes` makes failure precede fan-out and lets the one
stable `PR gate` remain the only required status.

### Run dependency review for drafts

Rejected because **Ready for review** is Maru's authoritative acceptance
transition. Drafts retain only the cheap policy checks needed to prepare a
candidate.

### Automatically allow or deny dependency licenses

Deferred because Maru has no accepted comprehensive compatibility policy, the
upstream deny-list option is deprecated, and a broad allowlist would turn
missing or ambiguous metadata into recurring contributor work without legal
certainty.

### Enable OpenSSF Scorecard summaries and pull-request comments

Rejected because the score is advisory rather than a Maru acceptance
requirement, and comments would require write permission and create persistent
triage noise. The read-only job summary is sufficient.

## Requirements affected

- NFR-001 gains fail-fast introduced-dependency evidence while retaining the
  complete current-tree audits.
- NFR-002 requires the distinct graph, audit, license, and container boundaries
  to remain explicit in contributor and operations documentation.
- NFR-003 requires the live allowlist reconciliation and first hosted proof to
  remain visible until GH-006 is complete.
- NFR-011 gains an immutable, read-only dependency-diff control aggregated
  through the existing protected status without broadening workflow authority.
