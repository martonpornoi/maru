# Immutable release verification

Date: 2026-08-20
Status: Live setting reconciled, repository candidate implemented, and local acceptance complete; hosted acceptance and first candidate rehearsal pending

Requirements: NFR-001, NFR-002, NFR-003, NFR-011

## Outcome

ADR 0065, **Immutable release publication and verification**, accepts the
repository portion of GH-002. The repository owner enabled release immutability
through GitHub before this work resumed. No release, tag, image, package, or
deployment was created by this milestone.

The manual Release workflow now requires an immediately preceding maintainer
readback of the administrator-only immutable-release endpoint and records the
maintainer's confirmation in the workflow-dispatch inputs. The workflow keeps
its short-lived minimum release permissions and does not add an administrator
token, environment secret, or environment variable.

Publication now has an explicit irreversible boundary. The workflow builds and
attests the OCI image, assembles checksums and release evidence, creates a draft
with the complete asset set, then compares the GitHub draft with the intended
tag, exact target commit, prerelease state, uploaded non-empty assets, and local
SHA-256 digests. Only a verified draft is published; the remote tag is checked
against the exact commit after publication.

After publication, bounded retries require the release to report immutable and
non-draft, verify GitHub's release attestation and every local release asset,
confirm that the tag still targets the certified commit, confirm that the image
tag resolves to the certified digest, and verify OCI provenance issued by
Maru's exact Release workflow. Available draft, release, asset, and image
verification responses remain in the workflow artifact even if a later
verification fails.

## External-state evidence

The authenticated post-change read on 2026-08-20 returned:

- release immutability: `enabled: true`, `enforced_by_owner: false`;
- GitHub releases: zero;
- Git tags: zero;
- `candidate`: exact custom branch policy `main`, administrator bypass disabled,
  no required reviewer, zero secrets, zero variables, and no deployment;
- `gold`: exact custom branch policy `main`, administrator bypass disabled, no
  required reviewer, zero secrets, zero variables, and no deployment; and
- repository deployments: zero.

The candidate and gold settings were observed only. They were not mutated in
this milestone. Their no-reviewer state is intentional while Maru has one
maintainer; independent gold review remains triggered by a second trusted
maintainer.

## Verification

- Thirty-nine focused classifier, release-metadata, release-evidence, and
  workflow-contract tests pass, including twenty-eight release/evidence
  contracts.
- Ruff formatting and ALL-rule lint pass over 644 files; strict mypy passes over
  356 source files; and `uv lock --check` resolves the locked 108-package graph.
- PyDocLint and the semantic NumPy-docstring validator pass over 365 production
  and tooling files.
- Direct Actions-policy validation still finds all eleven external workflow
  references immutable and exactly allowlisted; no new Action was introduced.
- Workflow YAML parses, documentation validation passes 274 Markdown files and
  203 unique requirement identifiers, whitespace validation passes, and a
  fresh warning-fatal parallel Sphinx/AutoAPI build completes successfully.

Exact candidate-head hosted acceptance remains to be recorded after the
candidate is pushed. No publication behavior can be proven end to end without
intentionally creating the first real candidate release.

## Known limits

- GitHub restricts the immutable-release setting endpoint to repository
  administrators, while `GITHUB_TOKEN` does not expose repository-
  administration permission. The pre-dispatch maintainer readback is therefore
  accountable external evidence rather than an independent workflow query.
- A false maintainer confirmation followed by a disabled server setting would
  be detected only after publication reports mutable. Avoiding that narrow gap
  without adding a privileged persistent credential requires the manual
  administrator preflight to remain mandatory.
- A failure after image push or draft/tag creation consumes that candidate
  identity. A failure after publication leaves an immutable release and cannot
  be rolled back in place. Recovery uses a new candidate number or CalVer.
- The first `rc.1` is a real public prerelease and GHCR image. It remains a
  separate release-pull-request and publication decision.

## Smallest next actions

1. Require hosted full acceptance for the exact hardening branch head before
   merge.
2. Merge the repository-hardening candidate and confirm the default branch
   contains the release-verification workflow.
3. Prepare a dedicated release pull request with the derived project version,
   curated notes, migration/recovery statement, and release checkpoint.
4. Re-read release immutability, intentionally authorize `rc.1`, run Release
   from exact current `main`, and inspect the immutable release, GHCR image,
   attestations, environment record, and retained evidence.
