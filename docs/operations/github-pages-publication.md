# GitHub Pages contributor-site publication

Status: Active; first deployment and homepage reconciled
Last updated: 2026-08-22
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0072

## Purpose and authority

GitHub Pages hosts Maru's static contributor documentation: maintained guides
plus the statically analysed Python AutoAPI reference. It does not host the
Django application, replace the authenticated Swagger/ReDoc HTTP contract,
publish a GitHub Release, establish support guarantees, approve production use,
or permit production personal data.

Repository desired state is split by API responsibility:

- [`.github/actions-allowlist.json`](../../.github/actions-allowlist.json) is
  the exact selected-Actions API payload;
- [`.github/actions-transitive-references.json`](../../.github/actions-transitive-references.json)
  records audited actions invoked inside a directly used composite action;
- [`.github/pages.json`](../../.github/pages.json) selects workflow-based Pages
  publication;
- [`.github/environments/github-pages.json`](../../.github/environments/github-pages.json)
  defines the deployment environment; and
- [`.github/environments/github-pages-main-policy.json`](../../.github/environments/github-pages-main-policy.json)
  defines its sole allowed branch.

The transitive audit file is not sent to GitHub. The selected-Actions payload
already includes every direct and audited nested reference required at runtime.
Do not add response-only fields to any desired-state payload.

## Normal publication

Every accepted merge to `main` starts `pages.yml`. The workflow:

1. rejects a non-main or unprotected source and an obsolete commit;
2. verifies the lock and exact direct/nested Action policy;
3. installs all locked documentation dependencies;
4. runs PyDocLint, semantic Python-docstring validation, and maintained-
   Markdown validation;
5. builds warning-fatal Sphinx/AutoAPI into fresh runner-temporary directories
   with the Pages-provided canonical base URL;
6. validates and uploads only the generated HTML root; and
7. deploys through the exact-main `github-pages` environment from a separate
   job with only Pages write and OIDC authority.

The `pages` concurrency group serializes deployments and never interrupts one
already in progress. A newer queued run supersedes an older pending run. Do not
rerun an obsolete SHA to restore content; correct the source on a branch and
merge another protected pull request.

The build and deploy remote-`main` comparisons are point-in-time checks, not a
lock on the branch. If `main` advances after the deploy check, the previously
accepted run may finish before the queued current run. Require the queue to
converge the public site to the newest accepted `main`; do not describe the
brief interval as an impossible state or cancel an active production
deployment.

## One-time activation

Activation changes live repository settings and requires explicit owner
authorization. Use an authenticated administrator session. Preserve the full
pre-change responses outside the repository evidence if they contain
unnecessary server metadata; record only sanitized conclusions and stable IDs.

### 1. Fail-closed pre-read

Read and compare all of the following before changing anything:

```powershell
gh api repos/martonpornoi/maru
gh api repos/martonpornoi/maru/actions/permissions
gh api repos/martonpornoi/maru/actions/permissions/selected-actions
gh api repos/martonpornoi/maru/pages
gh api repos/martonpornoi/maru/environments/github-pages
```

For the initial activation, the final two calls are expected to return 404.
Abort on any other unexpected drift. Require a public, unarchived repository,
default branch `main`, Actions `enabled`, selected-only execution, mandatory SHA
pinning, exact prior selected references, both broad trust flags false, Pages
absent, environment absent, Wiki disabled, and an empty homepage.

### 2. Reconcile exact selected Actions

Run the local validator, inspect the four additions, then replace the server's
whole selected payload with the reviewed checked-in payload:

```powershell
uv run python scripts/validate_actions_allowlist.py
gh api --method PUT repos/martonpornoi/maru/actions/permissions/selected-actions --input .github/actions-allowlist.json
```

Immediately read the parent and selected policies again. Require 16 unique
lowercase 40-hex references, exact order-insensitive parity with the file,
mandatory SHA pinning, selected-only execution, and both broad flags false.

### 3. Create workflow-source Pages and its environment

```powershell
gh api --method POST repos/martonpornoi/maru/pages --input .github/pages.json
gh api --method PUT repos/martonpornoi/maru/environments/github-pages --input .github/environments/github-pages.json
gh api --method POST repos/martonpornoi/maru/environments/github-pages/deployment-branch-policies --input .github/environments/github-pages-main-policy.json
```

Read back Pages, the environment, its deployment branch policies, secrets, and
variables. Require `build_type: workflow`; exact branch `main` and no tag or
pull-request policy; custom policy enabled and protected-branch matching
disabled; administrator bypass disabled; zero wait, reviewer, secret, and
variable. `prevent_self_review: false` is intentional because there is no
reviewer under the sole-maintainer boundary.

Do not use `configure-pages` enablement, a personal token in the workflow, a
branch publishing source, a `gh-pages` branch, a Wiki mirror, a preview
deployment, or a custom domain.

## First deployment verification

Merge only after the ready pull request's `PR gate` and every applicable
provider-managed protection pass. Record the squash merge SHA and Pages workflow
run ID. The main-triggered run must report that same `head_sha` and both **Build
Pages documentation** and **Deploy GitHub Pages** must succeed.

GitHub publication may be asynchronous. Retry read-only checks boundedly for up
to ten minutes. Require:

- the deployment and its latest status to reference the exact merge SHA,
  environment `github-pages`, and the action-returned environment URL;
- the Pages API to report `build_type: workflow`, `public: true`, HTTPS
  enforcement, the same HTTPS URL, and no custom domain;
- the dedicated Pages deployment-status endpoint for the exact merge SHA to
  report `status: succeed`;
- HTTP 200 for the site root, one nested maintained guide,
  `autoapi/maru/index.html`, and representative CSS and search assets;
- the root HTML to contain the Maru contributor title, current
  `pyproject.toml` version, and active-development notice; and
- canonical links to use the returned Pages base URL, including the `/maru/`
  project path unless GitHub returns a different authoritative URL.

Open `architecture/resilience-and-offline.html` in a real browser with the
network and console panels visible. Require its Mermaid source to become an SVG,
no console error, and every external script request to remain below exactly
`https://cdn.jsdelivr.net/npm/mermaid@11.16.1/` or
`https://cdn.jsdelivr.net/npm/d3@7.9.0/`. The optional ELK runtime must not be
requested. Same-origin Sphinx assets remain permitted. Any unversioned package,
alternate script origin, failed diagram, or unexpected request fails closure.
The accepted rationale and license boundary are recorded in
[generated documentation third-party licenses](generated-documentation-licenses.md).

Do not interpret an Action success alone as proof that public bytes are
available or correctly rooted.

For workflow-based publication, do not require the site-level `status` field or
the legacy Pages-build endpoints as acceptance authority. During Maru's first
verified workflow deployment, `GET /repos/{owner}/{repo}/pages` returned
`status: null` and `GET /repos/{owner}/{repo}/pages/builds/latest` returned 404
after public bytes were available. The exact-SHA endpoint below returned
`status: succeed` and is the workflow-specific API proof:

```powershell
gh api repos/martonpornoi/maru/pages/deployments/<merge-sha>
```

Retain the Actions run, environment deployment record, direct HTTP checks, and
browser proof alongside that response. A null site-level field does not excuse
any missing exact-SHA or public-content evidence.

## Homepage and closure

Only after the first deployment passes all API, HTTP/content, and fresh
browser/network checks above, update the repository homepage to the exact
returned Pages URL. Re-read the repository, Pages site, environment,
deployment, selected-Actions policy, and Wiki state. Record the run ID,
deployment ID, exact SHA, URL, relevant stable environment and policy fields,
HTTP/content checks, and browser proof in an append-only checkpoint. Add the
public documentation link to README in that closure change.

The homepage is metadata, not an authority source. If Pages is later disabled
or moved, clear or update it in the same separately authorized reconciliation.

## Failure and recovery

- A build failure leaves the previously published site intact. Fix source or
  tooling on a branch; never suppress a warning or validator merely to deploy.
- A deployment failure retains its red run and environment evidence. Retry only
  if its SHA is still current when rechecked; otherwise allow the newer main run
  to publish.
- An Action-policy failure requires comparing the checked-in direct references,
  audited nested map, upstream immutable composite definition, and complete live
  selected list. Do not enable broad trust as a shortcut.
- A wrong-path, missing-asset, version, or canonical-link result is a failed
  deployment even when the API reports `built`. Correct and republish through a
  protected pull request.
- A Mermaid failure or unexpected browser script origin is also a failed
  deployment. Do not broaden the accepted origin set merely to make a diagram
  render; reconcile `docs/conf.py`, the generated-license record, and ADR 0072
  on a branch.
- If public content creates an urgent security or privacy incident, preserve
  the run/deployment evidence, unpublish Pages through an explicitly authorized
  administrator action, clear the homepage, and follow the incident and secret-
  response policies. Never commit sensitive operational evidence to the public
  repository.

## Ongoing review

At least quarterly and whenever a Pages Action changes, inspect the exact
upstream action definition for new nested `uses` references, update the
transitive audit and selected payload together, run the complete contract, and
reconcile live state before merging. Whenever Mermaid, D3, or
`sphinxcontrib-mermaid` changes, repeat the exact generated-script and real-
browser diagram checks. Reverify Pages, environment, homepage, Wiki, selected
Actions, and the diagram runtime after a visibility, ownership, plan, default-
branch, CSP, or custom-domain change.
