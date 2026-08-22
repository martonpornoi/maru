# GH-007 protected GitHub Pages candidate

Date: 2026-08-22
Status: Repository candidate; live reconciliation and hosted proof pending
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0072

## Outcome

The repository candidate adds one dedicated publication workflow for Maru's
existing professional Sphinx and AutoAPI contributor site. Pull requests keep
their warning-fatal HTML artifact and have no deployment authority. After
merge, the new workflow accepts only protected `main`, compares its commit with
current remote `main` immediately before build and deployment, rebuilds from
locked dependencies in fresh runner-temporary doctree and HTML roots, and
uploads only the generated HTML.

Build and publication are separate trust boundaries. The build job has
`contents: read` and `pages: read`; checkout does not persist credentials. The
dependent deployment job runs no checked-out repository code and receives only
`pages: write`, `id-token: write`, and the `github-pages` environment. Pages
deployments are serialized without cancelling an active production deployment.
Manual dispatch from a non-main or unprotected ref, and a retry already obsolete
at either point-in-time check, fails closed. If `main` advances just after the
deploy check, the serialized newer run must converge the site after the older
accepted run finishes.

The generated boundary requires `index.html`, the Maru AutoAPI root, no
symlink, no embedded `.doctrees`, and a total size below 1 GB. It excludes the
persistent local `docs/_build/html` tree, which can retain stale caches even
when Sphinx uses `--fresh-env`. The public site version, release, HTML title,
and active-development notice now derive from the one version in
`pyproject.toml`; the canonical base URL comes from Pages at build time.

The browser diagram boundary is also explicit. Mermaid `11.16.1` and D3 `7.9.0`
remain exact-version jsDelivr runtime dependencies for the public static site;
unused ELK support is disabled. No unversioned package or alternate script
origin is accepted. The current upstream security review rejected the
extension's `11.12.1` default because it is affected by the 2026-08-04 Mermaid
CSS sibling-selector advisory; `11.16.1` is the first patched v11 release. This
site has no Maru authentication, secret, or personal-data authority, and first-
deployment closure must still prove a maintained diagram renders without
console errors or unexpected script requests.

## Immutable Action boundary

The candidate pins the latest stable official releases observed on 2026-08-22:

- `actions/configure-pages` v6.0.0 at
  `45bfe0192ca1faeb007ade9deae92b16b8254a0d`;
- `actions/upload-pages-artifact` v5.0.0 at
  `fc324d3547104276b827a68afc52ff2a11cc49c9`; and
- `actions/deploy-pages` v5.0.0 at
  `cd2ce8fcbc39b97be8ca5fce6e763baed58fa128`.

The uploader is an immutable composite that invokes
`actions/upload-artifact` v7.0.0 at
`bbbca2ddaa5d8feaa63e36b76fdaad77386f024f`. Because GitHub evaluates nested
Actions under the selected policy, the desired list contains 16 references: 15
direct workflow references plus this one audited nested reference. The
validator now requires every direct and audited nested pin exactly, rejects a
mutable nested reference, and rejects nested authority when its exact composite
parent is no longer directly used. Both broad trust flags remain false.

## External pre-read

Authenticated read-only GitHub API checks immediately before implementation
found:

- the repository public and unarchived with default branch `main`;
- Actions enabled in selected-only, SHA-pinned mode;
- exact parity between the 12 live and checked-in selected references;
- `has_pages: false` and no Pages API resource;
- no `github-pages` environment;
- an empty repository homepage; and
- Wiki disabled.

No live setting was changed. In particular, adding repository workflow files
does not enable Pages or authorize the four extra selected references.

## Repository verification

- All 73 focused workflow and change-classifier contracts pass, including all
  23 workflow-policy contracts.
- All 1,963 database-free unit tests pass.
- Ruff lint and format verification pass for the changed Python configuration,
  policy validator, and tests. PyDocLint reports no violation, and the semantic
  docstring validator accepts all 366 Python source files.
- The recursive policy validator reports 16 exact direct and audited nested
  immutable references. `uv lock --check` passes.
- Actionlint reports no diagnostic across all six workflows.
- Documentation validation accepts 295 Markdown files and 203 unique
  requirement identifiers.
- A fresh warning-fatal Sphinx and AutoAPI build with the intended Pages base
  URL succeeds. The bounded artifact contains 1,621 files and 936 HTML pages,
  totals 171,059,977 bytes, includes the landing page, Maru AutoAPI root,
  search index, and theme assets, and contains no symlink or doctree. Every HTML
  page has the expected versioned title, development notice, and canonical URL.
- The generated HTML has only two external script elements: exact-version
  Mermaid `11.16.1` and D3 `7.9.0` jsDelivr paths. A representative maintained
  diagram page contains Mermaid source and no ELK script reference; live SVG,
  console, and network proof remains correctly deferred to first deployment.
- Whitespace validation passes.

## Remaining acceptance

1. Separately authorize an exact live mutation: preserve the prior 12 selected
   references and both false broad trust flags, add only the four GH-007
   references, enable Pages with `build_type: workflow`, and create
   `github-pages` with exact-`main` custom policy, administrator bypass disabled,
   and no reviewer, secret, or variable. Re-read every setting.
2. Push a draft pull request and prove the cheap draft boundary. Mark it ready
   only after live selected-Action and Pages/environment prerequisites match the
   candidate. Require complete hosted merge acceptance and applicable managed
   checks.
3. Merge the accepted exact tree. Verify that the main-triggered Pages run and
   deployment use the exact merge SHA and that the Pages API reports the
   workflow source, built public HTTPS URL, and no custom domain.
4. Verify HTTP 200 plus expected content for the root, a nested guide, the Maru
   AutoAPI root, and static/search assets; verify canonical URLs and the visible
   `pyproject.toml` version. In a real browser, prove a maintained Mermaid page
   becomes SVG without console errors, ELK, or script requests outside the
   exact-version Mermaid and D3 jsDelivr prefixes.
5. Only then set and re-read the repository homepage to the exact returned
   Pages URL. Add a small documentation-only closure pull request with the run,
   deployment, SHA, URL, API/HTTP evidence, and continued Wiki-off boundary.

This candidate does not deploy the Django application, publish a release,
change the authenticated OpenAPI authority, create support obligations, approve
production use, or permit production personal data.
