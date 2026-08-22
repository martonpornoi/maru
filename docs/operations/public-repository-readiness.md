# Public repository readiness

Changing visibility is a deliberate governance and security event. The
repository became public on 2026-08-20. Actions were disabled during the
transition, the persistent workstation runner was unregistered, and Actions
were re-enabled only in exact-allowlist hosted mode.

## Verified transition controls

- The active no-bypass `main` ruleset requires a pull request, an up-to-date
  `PR gate`, resolved conversations, squash-only linear history, and rejects
  deletion and non-fast-forward updates. The active `v*` tag ruleset rejects
  mutation and deletion.
- The required `PR gate` is bound to GitHub Actions integration ID `15368`.
  The authorized GH-005 ruleset update was independently read back with every
  prior enforcement, no-bypass, pull-request, ref-mutation, and CodeQL
  protection intact.
- Repository-level self-hosted runner inventory is empty. Public pull requests
  use only standard GitHub-hosted runners with read-only default permissions.
  Eligible contribution-code runs from first-time fork contributors may await
  maintainer approval; that starts isolated execution and does not approve the
  pull request. Trusted base-branch metadata cleanup runs without contribution
  checkout and is not subject to fork-code approval.
- Actions run in `selected` mode, require SHA pinning, and allow only the exact
  revisions in `.github/actions-allowlist.json`.
- ADR 0071's merged GH-006 control pins dependency-review Action v5.0.0
  at `a1d282b36b6f3519aa1f3fc636f609c47dddb294`. It runs inside the existing
  ready-state classification job with `contents: read`, no comment, no
  Scorecard output, no license enforcement, and no new status, runner, or
  database. The separately authorized live selected-Actions update was read
  back at exactly the same 12 immutable references as the checked-in policy,
  with selected-only trust, SHA pinning, and both broad trust flags preserved.
  Ready-state run `32531845794` executed the pinned Action successfully, passed
  complete selected acceptance and `PR gate`, and pull request 11 squash-merged
  as `0d8af12`. The Action reported no introduced vulnerable packages at the
  configured moderate-or-higher threshold for that base-to-head comparison; it
  did not approve licenses, inspect container bases, or prove unchanged
  dependencies vulnerability-free. Post-merge CodeQL run `32553943756` passed
  all three configured languages on `main`.
- Secret scanning, push protection, Dependabot security updates, and private
  vulnerability reporting are enabled. GitHub-managed default CodeQL is
  configured for Actions, Python, and JavaScript/TypeScript. The `main` ruleset
  rejects CodeQL errors and security alerts of medium severity or higher;
  `PR gate` remains the sole required status check. The default branch currently
  has zero open CodeQL, Dependabot, or secret-scanning alerts as of the
  2026-08-21 GH-004 readback.
  Managed CodeQL default setup does not analyze fork pull requests, and its
  native merge protection does not cover Dependabot pull requests; the required
  `PR gate` plus default-branch and weekly scans remain the available boundary.
- The twelve findings from the first public CodeQL analysis were remediated and
  accepted through [pull request 2](https://github.com/martonpornoi/maru/pull/2).
- Issues and Discussions are enabled. Projects, Wiki, and GitHub Pages are
  disabled.
- The `candidate` and `gold` environments accept deployments only from the exact
  `main` branch, disallow administrator bypass, and currently have no required
  reviewer. Neither environment has a deployment, secret, or variable.
- Repository release immutability is enabled directly on Maru. The 2026-08-20
  administrator readback returned `enabled: true` and
  `enforced_by_owner: false`. No release or tag existed at that boundary.
- Merge commits and rebase merges are disabled; squash merge and automatic
  deletion of merged branches are enabled.

## Public policy and metadata snapshot

The authenticated 2026-08-21 GH-004 readback reported a public repository and
100 percent GitHub Community Profile health. GitHub recognizes README,
Apache-2.0 licensing, contribution guidance, the Code of Conduct, and the pull-
request template. SECURITY, SUPPORT, GOVERNANCE, CODEOWNERS, two Issue Forms,
and the Issue Form chooser are also present. The Community Profile API's
singular `issue_template` field was null; direct repository inspection found
both forms and the chooser, so that field did not demonstrate their absence.
The score is a discovery/file-presence signal, not independent assurance that
the policy content or repository is production-ready.

The live description is **Security-focused Django and PostgreSQL platform for
operating multi-convention events, under active development.** ADR 0070 records
the explicit authorization and exact post-change readback for that description-
only mutation. The wording signals maturity without implying a release stage,
hosted service, production approval, or permission to use real personal data.

The live topic set is accepted without change: `django`, `event-management`,
`modular-monolith`, `openapi`, `postgresql`, `python`, `react`, and
`typescript`. The homepage is the exact verified public documentation URL,
`https://martonpornoi.github.io/maru/`. Issues, Discussions, and workflow-source
Pages are enabled; Projects, Wiki, and Downloads remain disabled. Sphinx
documentation uses Pages, not an unversioned Wiki mirror.

ADR 0072's GH-007 implementation is accepted on `main`. It provides a
protected-main-only, warning-fatal Sphinx/AutoAPI workflow with separate read-
only build and Pages-write/OIDC deployment jobs, fresh temporary output, a 1 GB
ceiling, and project-version metadata derived from `pyproject.toml`. The live
selected policy contains 16 immutable references: 15 direct workflow actions
plus the exact `upload-artifact` revision invoked by the official Pages uploader
composite.

The generated site's browser runtime is also bounded: Mermaid `11.16.1` and D3
`7.9.0` load only from their exact-version jsDelivr package prefixes, and
unused ELK support is disabled. First-deployment verification proved a
maintained diagram renders without console errors or an unexpected script
request; future runtime or hosting changes repeat that proof. GitHub Pages
publication does not establish an application CSP.

The separately authorized live policy, workflow-source Pages site, and
`github-pages` environment reconciliation preceded protected merge. After
merge, exact-SHA deployment status, HTTPS, root, nested guide, generated
AutoAPI, static assets, canonical URL, visible version, and real-browser checks
passed before the separately authorized homepage update. The closure checkpoint
records the exact run, deployment, URL, and readbacks. Wiki remained disabled
throughout.

The exact commands, desired-state files, first-deployment checks, and failure
handling are maintained in the
[GitHub Pages publication runbook](github-pages-publication.md).

GitHub currently generates the default social preview. A custom preview is
optional polish and is deferred until a purpose-built, owner-approved social
asset exists; application icons and logos are not silently repurposed. Funding
is also deferred because no sponsorship recipient or stewardship policy has
been accepted. Do not add `.github/FUNDING.yml` or connect a recipient as a
placeholder.

The 23 live labels include every label used by the Issue Forms and current
automation, including `bug`, `proposal`, `triage`,
`destructive-change-reviewed`, `good first issue`, and `help wanted`. No issue
currently carries either newcomer label. `good first issue` is reserved for
bounded work with observable acceptance, safe synthetic inputs, usable setup
and verification instructions, no maintainer-only access, and no hidden
security, migration, or cross-module prerequisite. Do not manufacture newcomer
work merely to populate the label.

Support is best effort with no response or resolution SLA. Vulnerabilities use
GitHub private vulnerability reporting. The sole current human repository
administrator is responsible for response; notification delivery depends on
that account's settings, and the reporter plus any explicitly added advisory
collaborators retain access. The Code of Conduct explicitly records that Maru
has no private project-specific conduct-reporting channel or independent
reviewer. It rejects public disclosure of sensitive reports and misuse of the
security-advisory form, and it scopes GitHub Support to GitHub-hosted abuse. The
owner chose not to publish a login or historical personal address or create an
unattended placeholder mailbox.

## Completed one-time public-history audit

GH-003 audited the four public branch heads and eight pull-request heads as one
46-commit graph, passed strict reachable-object verification, and scanned the
current repository candidate separately with checksum-verified Gitleaks 8.30.1.
Manual review resolved the single documentation-prose detector result as a
false positive; no unresolved credential or production-personal-data finding
remained. Public issue, pull-request, and discussion metadata also produced no
scanner finding. The durable checkpoint contains only sanitized scope, counts,
and conclusions, never a matched string or raw report.

All seven currently tracked brand assets and their embedded metadata, plus the
locked dependency inventories and publication inputs, were reviewed for
provenance, license, and notice obligations. The owner attests that those assets
are project-controlled; the audit did not independently prove ownership or
examine historical-only assets. Maru-owned source remains Apache-2.0. Python
distribution metadata and the release application manifest declare
`Apache-2.0 AND MIT`; release assets and the OCI image carry the license and MIT
notice, while the image's SBOM and provenance describe its contents without an
aggregate image-wide license expression. No blocker remained within that scope.
The owner accepted the already-public historical personal Gmail author metadata
without a destructive rewrite; future maintainer commits use a GitHub no-reply
address by default.

GH-003 did not download or scan GitHub-hosted Actions log or artifact bytes. Its
drift-prone snapshot observed 62 workflow runs and 188 unexpired artifacts,
which remain governed by short retention. The audit therefore makes no claim
about every public server-generated byte.

Standard GitHub secret scanning and push protection remain live. Validity
checks and generic-pattern scanning were unavailable for the current user-owned
repository and remain deferred pending eligibility, provider-contact, and
synthetic-fixture noise review. GH-003 changed no live setting and deliberately
added no permanent pull-request history scanner. Repeat the full audit only
after a material visibility, ownership, imported-history, or incident boundary.

## Outstanding public-readiness work

Visibility changed before every item in the original pre-public checklist had
fresh evidence. GH-007 is now complete; treat the remaining items as immediate
launch tasks, not optional later work:

- Exercise the protected-tag refusal and confirm push protection blocks a
  synthetic non-secret test pattern without publishing credentials. Add a
  second trusted maintainer before requiring one approval, CODEOWNER review,
  or independent `gold` approval.
- Rehearse a first-time cross-repository fork contribution and its maintainer
  workflow-approval boundary.
- Rehearse the first explicitly authorized `rc.1` through ADR 0065's merged
  draft-first and post-publication verification boundary. Exercise the
  `candidate` and `gold` environment policies, immutable release and asset
  attestations, GHCR visibility, image provenance, deployment targets, and
  package cleanup.
- The live description, topics, feature states, default social preview, absent
  funding, issue-label inventory, support expectations, and first-good-issue
  boundary are reviewed and accepted by GH-004. Future external metadata
  changes require another explicit authorization and readback.
- Keep the detailed production-readiness boundary current. Do not imply that
  the repository or a candidate release is safe for production personal data.

## Post-transition acceptance

Re-query repository rules and security features rather than assuming settings
survived the transition. Run a documentation-only pull request, a protected
deletion refusal, an ordinary targeted change, a high-risk full change, and a
candidate release in a synthetic environment. Verify forks receive read-only
tokens, untrusted pull requests cannot access secrets or publish packages, and
all Actions remain pinned to immutable commits.

Public source does not require public operational data. Keep vulnerability
reports, incident details, personal data, credentials, production topology, and
partner-confidential material in their separately governed systems.
