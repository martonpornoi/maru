# Repository dependency and CodeQL hardening

Date: 2026-08-20
Status: Repository candidate complete; hosted full acceptance and merge pending

Requirements: NFR-001, NFR-002, NFR-003, NFR-011

## Outcome

ADR 0064, **Repository supply-chain and code-scanning policy**, accepts GH-000
and GH-001 from the GitHub repository hardening plan. The repository candidate
makes Dependabot security-only for the native `uv`, npm, and GitHub Actions
ecosystems. Each ecosystem retains one grouped security-update rule while
`open-pull-requests-limit: 0` suppresses routine version-update pull requests.
Ordinary upgrades move to one maintainer-owned, locally certified branch at
least quarterly and before a release when material dependency changes warrant
it.

Reusable full acceptance now starts with a small locked-input and automation-
policy preflight. It runs `uv lock --check` and verifies exact two-way parity
between immutable workflow Action references and
`.github/actions-allowlist.json` before static, documentation, contract,
security, unit, or PostgreSQL integration work fans out. The stable `Full CI
gate` includes this preflight result.

The reviewed `main` ruleset snapshot adds GitHub's native `code_scanning` rule
for CodeQL with `alerts_threshold: errors` and
`security_alerts_threshold: medium_or_higher`. `PR gate` remains the sole
strict required status. Pull-request-only squash history, resolved
conversations, deletion and non-fast-forward protection, the empty bypass list,
and `current_user_can_bypass: never` remain unchanged.

No product runtime, model, migration, tenancy, authority, audit, API, or release
behavior changes in this milestone.

Adjacent public-facing policy pages now link the active private vulnerability
intake and Discussions, describe the current sole-maintainer governance model,
and replace the superseded initial-CodeQL and environment setup language with
the verified public state. The wider repository-description, metadata,
succession, history, and public-material audit remains tracked under GH-003,
GH-004, and GH-008.

## Repository and external-state boundary

The CodeQL ruleset mutation was a separately authorized live GitHub operation
performed before this repository branch is merged. On 2026-08-20, live ruleset
`21093924` was read back with the exact error and medium-or-higher security
thresholds above. The readback also confirmed that `PR gate` remains the sole
strict status and that all prior pull-request and no-bypass protections remain
intact. This branch records the normalized desired-state payload and its
contract test; it does not repeat the remote mutation.

By contrast, the security-only Dependabot configuration and the default-branch
full-acceptance preflight are repository changes. They do not become the
automation policy on `main` until this branch is merged. A pull request can
exercise the candidate preflight before merge, but the checkpoint does not
claim that the candidate files are already active on the default branch.

## Verification

- Twenty-four focused classifier and workflow-contract tests pass, including
  thirteen workflow, ruleset, Dependabot, and Action-allowlist contracts.
- Ruff formatting and lint pass across all 643 checked Python files, and strict
  mypy passes across all 356 source files.
- `uv lock --check` confirms that `uv.lock` matches the Python project inputs.
- Direct Action-policy validation finds all eleven external workflow references
  immutable and exactly represented by the checked-in allowlist.
- The live selected-Actions policy contains the same eleven references and
  keeps broad GitHub-owned and verified-publisher trust disabled.
- PyDocLint, the warning-fatal Sphinx and AutoAPI build, validation of 272
  Markdown files and 203 unique requirement identifiers, and
  `git diff --check` pass.
- The live ruleset readback confirms CodeQL `errors` and
  `medium_or_higher` thresholds with the previous protections preserved.

The exact candidate head has not yet passed GitHub-hosted complete full
acceptance. That hosted run, including the preflight and stable aggregate gate,
remains authoritative before merge.

## Known limits

- Dependabot can propose security updates, but a maintainer must still keep each
  ecosystem's manifest and lockfile coherent and run the complete review path.
- The preflight detects stale Python resolution and Action allowlist drift; it
  does not replace dependency audits, immutable installation, tests, CodeQL, or
  human review.
- The live CodeQL rule blocks configured alert thresholds, but repository
  administrators must continue to read back external settings after ownership,
  visibility, or GitHub behavior changes.
- GH-002 through GH-009 remain outside this milestone. No release, tag,
  package, deployment, or additional GitHub setting is authorized by this
  checkpoint.

## Smallest next actions

1. Push the exact candidate head and require its complete GitHub-hosted full
   acceptance and stable aggregate gate before merge.
2. Merge only after the hosted result is green, then confirm the default branch
   contains the security-only Dependabot policy and early full-CI preflight.
3. Continue GH-002 by deciding release immutability and deployment-environment
   verification under a separate external-setting authorization boundary.
