# GH-007 publication and homepage closure

Date: 2026-08-22
Status: Complete
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0072
Follows: `2026-08-22-gh007-pages-live-reconciliation.md`

## Outcome

Pull request 13 completed protected hosted acceptance, squash-merged to `main`,
and triggered Maru's first protected-main GitHub Pages publication. The exact
merge SHA passed the dedicated Pages deployment status, direct public HTTP,
generated-content, asset, canonical-link, and fresh real-browser diagram
checks. Only after those checks passed did the owner separately authorize the
repository homepage update to the exact returned Pages URL.

The public contributor portal is:

`https://martonpornoi.github.io/maru/`

Wiki remains disabled. This checkpoint closes GH-007. It does not deploy the
Django application, publish a release, establish a supported hosted service,
approve production personal data, add a custom domain, or provide an offline
documentation guarantee.

## Protected candidate and merge

The final pull-request candidate had:

- base `4a6380cc05284f955bec9bb14b1a082ad76e6e13`;
- head `a0b3fd6ef35318666236012a976163332104f835`;
- GitHub synthetic merge candidate
  `e988f050428e4b140da2ce6eb58a220e42ee411a`;
- shared tree `8fa25b99fd9ba6239cee0d9f780222e9cfc447cf` for the
  head, synthetic merge candidate, and eventual squash merge; and
- squash merge `b50e665ce1f17eb9779874d56e1de5b7c3a6915b`.

Ready-state run `32562549166` started at `2026-08-22T08:32:19Z` and completed
successfully at `2026-08-22T09:32:18Z`. Run metadata associates it with head
`a0b3fd6`, while its checkout-bearing jobs tested GitHub's synthetic pull-
request merge `e988f050`. Repository safety, locked inputs and Actions policy,
Python static analysis, warning-fatal contributor documentation,
Django/contracts/frontend, dependency security, unit coverage, all eight
PostgreSQL shards, combined coverage, **Full CI gate**, and `PR gate` passed.
Provider-managed protection also passed before pull request 13 squash-merged at
`2026-08-22T09:48:41Z` with the same tested tree.

## Exact-main Pages publication

Push-triggered workflow run `32565940418` reported the exact merge SHA as its
`head_sha` and completed successfully:

- **Build Pages documentation**, job `97014464997`, ran from
  `2026-08-22T09:48:46Z` through `2026-08-22T10:00:20Z`; and
- **Deploy GitHub Pages**, job `97015660232`, ran from
  `2026-08-22T10:00:24Z` through `2026-08-22T10:00:34Z`.

The build rechecked protected and current `main`, locked inputs, and the exact
Actions policy before building into fresh runner-temporary roots. Source
validation, warning-fatal Sphinx/AutoAPI generation, generated-artifact
validation, and upload passed before the separate least-privilege deployment
job ran.

GitHub environment deployment `6035581239` references exact SHA `b50e665`, ref
`main`, and environment `github-pages`. Its latest status record `17158570480`
is `success` and returns the same public environment URL. GitHub's current
dedicated Pages endpoint for the exact SHA reports `status: succeed`.

## Pages and public-content proof

Authenticated readback using API version `2026-03-10` reports:

- `build_type: workflow`;
- `public: true` and `https_enforced: true`;
- `https://martonpornoi.github.io/maru/` as the authoritative URL; and
- no custom domain.

The site-level `status` field is `null`, and the legacy
`pages/builds/latest` endpoint returns 404 for this workflow publication. Those
fields are not used as success evidence. The publication run, environment
deployment, dedicated exact-SHA Pages status, and public bytes provide the
workflow-specific evidence. The operating runbook now records this observed
API boundary.

Direct requests returned HTTP 200 for:

| Resource | First-deployment bytes |
| --- | ---: |
| Site root | 453,342 |
| `architecture/resilience-and-offline.html` | 155,921 |
| `autoapi/maru/index.html` | 127,349 |
| Furo stylesheet | 50,789 |
| Maru stylesheet | 216 |
| `searchindex.js` | 1,899,486 |

The root title is **Maru 0.1.0a0 contributor documentation**. It contains the
`0.1.0a0` project version and the active-development/no-production-personal-
data notice. Root and nested canonical links remain below the authoritative
`https://martonpornoi.github.io/maru/` project path; the root canonical is
`https://martonpornoi.github.io/maru/index.html`.

## Fresh browser proof

A fresh real-browser load of
`architecture/resilience-and-offline.html` produced one Mermaid container and
one rendered SVG with no unrendered source and zero console errors. The browser
observed 32 script resources. All 28 external resources remained below exactly:

- `https://cdn.jsdelivr.net/npm/mermaid@11.16.1/`; or
- `https://cdn.jsdelivr.net/npm/d3@7.9.0/`.

No alternate origin, unversioned package path, or ELK resource was requested.
Same-origin Sphinx and Furo resources remained below the `/maru/` publication
root.

## Homepage and control readback

After the deployment, public-byte, generated-content, asset, canonical-link,
and fresh browser/network checks passed, the owner separately authorized
setting only the repository homepage. Immediate readback returned the exact
value `https://martonpornoi.github.io/maru/` and reconfirmed:

- a public, unarchived repository with default branch `main`;
- Wiki disabled;
- workflow-source Pages public over enforced HTTPS at the same URL, with no
  custom domain;
- environment deployment `6035581239` successful for exact merge SHA
  `b50e665`, with the same URL, and the dedicated exact-SHA Pages status still
  `succeed`;
- selected-only Actions with mandatory SHA pinning;
- exactly 16 immutable selected references and both broad trust flags false;
- environment `github-pages`, stable ID `20378219386`, with administrator
  bypass disabled and custom branch policy matching enabled;
- sole deployment branch policy `main`, stable ID `57973137`, type `branch`;
  and
- zero environment reviewers, wait time, secrets, or variables.

No Wiki mirror, `gh-pages` branch, custom domain, preview deployment, personal
access token, reviewer, secret, variable, or release was created.

## Closure-record verification

The closure branch passes:

- documentation validation over 297 Markdown files and 203 unique requirement
  identifiers;
- PyDocLint plus semantic docstring validation over 366 Python source files;
- Ruff lint and format checks; and
- a fresh warning-fatal Sphinx/AutoAPI HTML build using
  `https://martonpornoi.github.io/maru/` as `html_baseurl`.

## Remaining boundaries

GH-007 publishes contributor documentation only. The next separately
authorized repository-release action is GH-002's first `rc.1` candidate
rehearsal. GH-008 remains deferred until a second trusted maintainer exists.
Application deployment, accessibility, recovery, provider, legal/privacy,
finance, safeguarding, and production-governance gates remain open.
