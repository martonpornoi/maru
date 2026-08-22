# GH-007 GitHub Pages live reconciliation

Date: 2026-08-22
Status: Live prerequisites reconciled; ready-state hosted proof pending
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0072
Follows: `2026-08-22-gh007-github-pages-candidate.md`

## Outcome

The owner separately authorized the exact live activation described by the
GH-007 candidate. The repository now permits the four audited Pages Action
references in addition to the prior 12, exposes a workflow-source public HTTPS
Pages site, and has one no-bypass `github-pages` environment that accepts only
branch `main`. This activation does not publish repository content by itself:
the workflow remains confined to pull request 13 until accepted and merged.

The earlier candidate checkpoint remains the immutable pre-change record. This
checkpoint records only the sanitized post-change conclusions and stable
environment and branch-policy identifiers.

## Exact authorized mutation

On 2026-08-22, the authenticated administrator session performed only these
approved operations:

1. replaced the complete selected-Actions payload with the reviewed checked-in
   16-reference payload while preserving both broad trust flags as `false`;
2. created the Pages site with `build_type: workflow`;
3. configured the `github-pages` environment with custom branch policies and
   administrator bypass disabled; and
4. created its sole deployment branch policy for exact branch `main`.

No repository homepage, Wiki, custom domain, secret, variable, reviewer, wait
timer, branch publishing source, `gh-pages` branch, preview deployment, or
personal access token was added.

## Sanitized readback

Immediate authenticated API readback proved:

- the repository remains public, unarchived, and based on default branch
  `main`;
- Actions remain enabled in selected-only mode with mandatory SHA pinning;
- the selected policy contains exactly the 16 checked-in immutable references,
  order-insensitively, with `github_owned_allowed: false` and
  `verified_allowed: false`;
- Pages reports `build_type: workflow`, `public: true`, HTTPS enforcement,
  no custom domain, and authoritative URL
  `https://martonpornoi.github.io/maru/`;
- environment `github-pages` has stable ID `20378219386`, administrator bypass
  disabled, custom branch policies enabled, and protected-branch matching
  disabled;
- its sole deployment policy has stable ID `57973137`, name `main`, and type
  `branch`;
- the environment has no reviewer or wait-timer rule and contains zero secrets
  and zero variables; and
- Wiki remains disabled and the repository homepage remains empty.

Pages has no built deployment yet because the publication workflow is not on
`main`. A pre-deployment null status is therefore expected and is not accepted
as publication proof.

## Draft hosted proof

Draft pull request 13 at repository commit `6252a6d` exercised the bounded draft
path:

- change classification passed;
- managed CodeQL passed for Actions, JavaScript/TypeScript, and Python;
- relevant quality, repository safety, unit, PostgreSQL, and high-risk full
  acceptance jobs skipped as designed; and
- `PR gate` failed explicitly because a draft is not merge-acceptable.

This red draft gate is intentional evidence, not a workflow defect. It prevents
the expensive acceptance fan-out until the maintainer marks the pull request
ready after live prerequisites match.

## Repository verification

- Documentation validation accepts 296 Markdown files and 203 unique
  requirement identifiers.
- A fresh warning-fatal Sphinx and AutoAPI build succeeds using the authoritative
  Pages base URL and includes this checkpoint in the generated site.
- Whitespace validation passes.

## Remaining acceptance

1. Commit and push this sanitized reconciliation record, then mark pull request
   13 ready for review.
2. Require every applicable hosted acceptance and provider-managed protection
   to pass for the exact accepted tree before merge.
3. Merge the accepted tree and require the main-triggered Pages workflow and
   deployment to reference the exact merge SHA.
4. Complete the API, deployment, HTTP, content, canonical-link, asset, Mermaid
   SVG, browser-console, and exact-script-request checks in the publication
   runbook.
5. Only after those checks pass, separately authorize setting the repository
   homepage to the returned Pages URL and add the final append-only closure
   checkpoint and README link.

This reconciliation does not deploy Django, publish a release, approve
production use, create a support obligation, or permit production personal
data.
