# ADR 0072: Protected-main Sphinx publication through GitHub Pages

- Status: Accepted
- Date: 2026-08-22
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011
- Implements: GH-007
- Refines: ADR 0057 decision 4, ADR 0064 decision 1, ADR 0066 decision 3,
  and ADR 0068 decision 7

## Context

Maru already builds its complete Sphinx, MyST, Napoleon, Mermaid, Furo, and
static AutoAPI contributor site with warnings treated as errors. Pull requests
validate the NumPy docstrings, maintained Markdown, generated reference, and
HTML artifact before merge. The accepted default-branch policy deliberately
stopped repeating full merge acceptance on every squash push, leaving a future
deployment workflow to own the smallest necessary `main`-only publication.

The public repository has no hosted documentation site. An authenticated
2026-08-22 pre-read reported `has_pages: false`, no Pages API resource, no
`github-pages` environment, an empty repository homepage, and Wiki disabled.
The live selected-Actions policy exactly matched the 12 checked-in immutable
references with both broad trust flags disabled.

Publishing introduces a narrower but real write boundary. GitHub Pages needs a
Pages artifact, an OIDC-backed deployment, and a deployment environment. A
manual workflow dispatch may select a non-default ref, an old workflow run may
be retried after `main` advances, and a checked-out contribution must not retain
Git credentials. The deployment must therefore prove its protected source and
keep build-time read authority separate from publication authority.

The official Pages uploader is a composite action. Its immutable v5.0.0 commit
invokes `actions/upload-artifact` v7.0.0 at another exact commit. GitHub's
selected-Actions boundary evaluates nested actions, while Maru's original
validator modeled only direct workflow references. Ignoring the nested pin
would either fail the first deployment or encourage broad GitHub-owned trust.

The existing local output can also contain stale caches because `--fresh-env`
refreshes the Sphinx environment but does not clean the destination directory.
At the audit boundary, the maintained HTML was below GitHub Pages' 1 GB site
limit, but an old `docs/_build/html/.doctrees` cache materially inflated the
local tree. A publication job must never upload that persistent path.

The extension also enhances diagrams in the browser. Its default generated
HTML loads exact-version Mermaid, optional ELK layout, and D3 packages from
jsDelivr and emits inline initialization. GitHub Pages does not provide a
repository-controlled strict response-header Content Security Policy. A public
static contributor site has no Maru authentication, secret, or personal-data
authority, but its diagram rendering still needs an explicit availability,
supply-chain, and browser-verification decision rather than inheriting defaults
silently.

## Decision

1. Add one dedicated workflow triggered by pushes to `main` and intentional
   manual dispatch. The build rejects every ref except protected
   `refs/heads/main` and checks that its commit is current remote `main`
   immediately before building. The deployment repeats that point-in-time check
   immediately before publication. Serialize the `pages` concurrency group and
   never cancel an in-progress production deployment. If `main` advances after
   the final check, allow that already accepted deployment to finish and require
   the queued newer run to converge the public site.
2. Separate build from deployment. The build job receives only `contents: read`
   and `pages: read`. It checks out without persistent credentials. The deploy
   job depends on the completed build, executes no repository code, and receives
   only `pages: write` plus `id-token: write`. Its sole environment is
   `github-pages`, and its environment URL comes from the deployment result.
3. Rebuild from Python 3.12 and locked dependencies. Install pinned
   `uv==0.11.29` and `PyYAML==6.0.3`, require a current lock and exact Action
   policy, synchronize all locked groups, run PyDocLint plus both semantic and
   Markdown validators, and build Sphinx/AutoAPI with `-W`, `--keep-going`,
   `--fresh-env`, and parallel workers.
4. Generate doctrees and HTML in separate fresh runner-temporary directories.
   Require the HTML root and generated Maru AutoAPI root, reject symlinks and
   embedded doctree caches, and reject a site at or above 1 GB. Upload only
   that generated HTML root for one day; never publish the repository,
   environment, source tree, or persistent local build directory.
5. Pin the latest stable official Pages releases observed on 2026-08-22:
   `configure-pages` v6.0.0, `upload-pages-artifact` v5.0.0, and `deploy-pages`
   v5.0.0. Keep configure-time enablement false. Explicitly record the
   uploader's audited nested `upload-artifact` v7.0.0 reference in the exact
   checked-in and live selected-Actions policy. Extend the validator so an
   audited nested reference is allowed only while its exact composite parent is
   directly used; all direct and nested references remain immutable and exact.
6. Read `[project].version` from `pyproject.toml` with the Python standard
   library. Use it for Sphinx `version`, `release`, the HTML title, and a visible
   active-development announcement. Obtain the canonical HTML base URL from
   `configure-pages` at publication time rather than hard-coding a project-site
   path or future domain.
7. Make the diagram browser boundary explicit. Pin Mermaid `11.16.1` and D3
   `7.9.0` in `docs/conf.py`, load them only below their exact-version jsDelivr
   package prefixes, and disable unused `@mermaid-js/layout-elk`. Accept the
   extension's inline bootstrap and the absence of a strict Pages response-
   header CSP only for public, unauthenticated contributor content. The first
   deployment and every runtime change must verify a maintained diagram becomes
   SVG, produces no console error, and makes no script request outside those
   exact prefixes and the same-origin site.
8. Treat Pages enablement as an external setting. Before merge, separately
   authorize and reconcile the 16-entry selected-Actions policy, create the
   Pages site with `build_type: workflow`, and create `github-pages` with an
   exact-`main` custom branch policy, no administrator bypass, no secret, no
   variable, and no self-review requirement while one maintainer exists.
9. Treat the first protected-main deployment as a second evidence phase. After
   merge, require the workflow run, deployment, Pages API, and HTTPS site to
   agree on the exact merge commit and returned URL. Verify the root, a nested
   guide with a Mermaid diagram, generated AutoAPI, static assets, canonical
   links, project version, and accepted external script boundary. Only then set
   and read back the repository homepage and add a small closure checkpoint.
   The implementation pull request cannot truthfully claim post-deployment
   evidence.
10. Keep Wiki disabled. Do not add a `gh-pages` branch, pull-request preview,
   custom domain, `CNAME`, or mandatory external link checker. The published
   site is static contributor documentation; it is not the Django application,
   a release, an API authority change, production approval, or permission to
   use production personal data.

## Consequences

- Every publication candidate is rebuilt from a protected `main` commit after
  merge acceptance and checked against current remote `main` immediately before
  build and deployment. A narrow post-check advancement can briefly publish an
  older accepted commit; serialized execution requires the queued newer run to
  converge the site. Pull requests retain read-only documentation validation
  and cannot deploy previews.
- Only the final deployment job can write Pages state or mint its OIDC token.
  Build tools and checked-out repository code cannot use that authority.
- A retry already obsolete at either current-main check, non-main manual
  dispatch, unprotected source, stale local output, oversized site, symlink,
  missing index, missing API root, mutable Action, or selected-policy mismatch
  fails before publication.
- The selected policy grows from 12 to 16 exact references: three direct Pages
  actions and the official uploader's one audited nested action. Both broad
  trust flags stay false.
- The public site automatically follows a future reviewed CalVer change in
  `pyproject.toml`; no second version constant can drift.
- Diagram enhancement retains an exact-version jsDelivr availability and
  supply-chain dependency. Unused ELK code is removed, no unversioned origin is
  accepted, and a browser proof is part of first-deployment closure. A custom
  domain, strict CSP, offline guarantee, authenticated content, or materially
  larger diagram corpus requires reconsidering vendoring or pre-rendering.
- GH-007 remains operationally incomplete until live settings, hosted merge
  acceptance, the first deployment, HTTP/API reconciliation, homepage update,
  and closure checkpoint are complete.

## Alternatives considered

### Mirror documentation into GitHub Wiki

Rejected because Wiki would create a second, unversioned source that can drift
from the reviewed Markdown and generated API reference.

### Publish a generated `gh-pages` branch

Rejected because it creates a mutable generated branch and Git credential write
path when artifact-based Pages deployment already provides an environment,
OIDC, deployment history, and exact source commit.

### Deploy from pull requests or publish previews

Rejected because untrusted candidate code must not receive deployment authority
and `deploy-pages` preview support remains experimental. Pull requests already
retain their HTML artifact for review.

### Reuse the pull-request documentation artifact

Rejected because Pages must publish the protected squash result from current
`main`, not an expiring artifact associated with a synthetic merge candidate.
The small main-only rebuild is publication evidence rather than duplicate full
acceptance.

### Allow all GitHub-owned actions

Rejected because it would turn one audited composite dependency into broad,
mutable repository authority. Explicitly modeling the nested immutable pin
preserves the exact policy.

### Let the workflow enable Pages itself

Rejected because `configure-pages` would need a stronger long-lived token or
administrator authority. A separately authorized settings mutation with pre-
read and post-change reconciliation keeps that authority outside repository
code.

### Require live external-link checking on every deployment

Rejected because third-party availability would make an otherwise correct
publication fail nondeterministically. Warning-fatal Sphinx validation and
focused internal-link evidence remain deterministic; external links receive
reviewed maintenance rather than becoming a production gate.

### Vendor or pre-render every Mermaid diagram now

Deferred because self-hosted Mermaid ESM requires its complete versioned chunk
graph and another browser-asset update boundary, while CLI pre-rendering adds a
Node and headless-browser toolchain. For four public diagrams, exact-version
runtime paths plus browser verification are the smaller accepted boundary. The
decision must be revisited if the site gains a custom domain, strict CSP,
offline requirement, authenticated material, or substantially more diagrams.

## Requirements affected

- NFR-001 gains executable workflow, metadata, artifact, source-ref,
  permissions, and transitive-Action contracts plus a required first hosted
  deployment proof.
- NFR-002 gains a canonical public contributor site whose version and source
  remain tied to reviewed repository state, with an explicit bounded diagram
  runtime rather than an implicit external-script dependency.
- NFR-003 requires separate candidate and post-deployment checkpoints so the
  live-setting and publication boundary remains resumable.
- NFR-011 preserves protected exact-commit publication, least privilege,
  immutable direct and nested Action policy, and separately reconciled external
  settings.

## References

- [Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Configuring a publishing source for GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [Managing environments for deployment](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [`upload-pages-artifact` v5.0.0 action definition](https://github.com/actions/upload-pages-artifact/blob/fc324d3547104276b827a68afc52ff2a11cc49c9/action.yml)
- [Mermaid CSS sibling-selector advisory and patched version](https://github.com/mermaid-js/mermaid/security/advisories/GHSA-6x64-9x62-f2gx)
