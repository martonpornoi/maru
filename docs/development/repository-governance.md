# Repository governance and collaboration

## Branch workflow

Create work from current `main`, push a focused branch, and open a pull request.
The protected status is `PR gate`; isolated GitHub-hosted runners evaluate the
current pull-request merge candidate derived from the submitted head and
up-to-date `main` through the repository's fail-closed change plan.
Squash merge is the only permitted merge method, and merged branches are
deleted automatically.

Drafts receive change classification plus locked-input and Actions-policy
feedback only. Their `PR gate` is intentionally red because they are not yet
merge-certified. Marking a draft **Ready for review** starts authoritative
selected acceptance; later ready-state pushes and reopenings rerun it.
Converting a pull request back to draft cancels obsolete work. The pull-request
workflow does not repeat acceptance on the protected squash push to `main`;
managed CodeQL retains its separate default-branch scan.

The current sole-maintainer rules require a pull request, successful status,
linear history, and resolved conversations but zero approving reviews. When a
second trusted maintainer is available, change the ruleset to require one
approval and CODEOWNER review. Never add a routine bypass actor.

Deleting 25 or more paths, mass-renaming them, or deleting or renaming source,
tests, repository automation, ADRs, locks, license, security policy, or critical
root collaboration/deployment files requires the repository owner to apply
`destructive-change-reviewed`. Under the current sole-maintainer policy, the
label event is evidence that the exact scope was reviewed; it is not permission
to bypass tests. Every destructive plan
takes full acceptance, and repository safety must pass before expensive work
starts. Acceptance consumes approval only from the exact owner-applied
`destructive-change-reviewed` label event; all other pull-request events and
actors are unapproved. An issues-only, no-checkout `pull_request_target`
workflow removes
stale label display state after synchronize, reopen, ready-for-review, and
conversion-to-draft events. Its token-generated change is UI cleanup, not a
relied-upon `unlabeled` retrigger. A maintainer must inspect the current scope
and reapply the label to create a fresh approval event. This cleanup may remove
only that stale label and must never check out or execute pull-request code.

The pull-request workflow and `scripts/ci_changes.py` classifier are evaluated
from the candidate merge tree. Their read-only token and lack of secrets bound
the effect of untrusted execution, but a green result still assumes the sole
maintainer reviews candidate changes to that workflow and classifier before
merging. Before another account receives write or merge authority, record and
implement a trusted review boundary for these files, such as mandatory
CODEOWNER approval or default-branch-controlled gate logic. Never add write
authority to a candidate-evaluated workflow without a separate security
decision.

Every clone must activate `.githooks/pre-push` through
`scripts/install_git_hooks.ps1`. The hook blocks direct `main` pushes, branch
deletion, and non-fast-forward updates in ordinary Git use. It remains
bypassable by design; the no-bypass GitHub ruleset is the authoritative
boundary. The active public-repository ruleset reports that the current owner
can never bypass it through an ordinary Git operation.

## Applying repository rules

Reviewed desired-state payloads live in `.github/rulesets/`. They were applied
when Maru became public on 2026-08-20. On a new repository, apply them with an
owner token:

```powershell
gh api --method POST repos/martonpornoi/maru/rulesets --input .github/rulesets/main.json
gh api --method POST repos/martonpornoi/maru/rulesets --input .github/rulesets/release-tags.json
```

Do not repeat the POST commands against this repository because that would
create duplicate rulesets. Compare the active rule first and update its exact
identifier when the checked-in desired state changes.

The active `main` rule requires an up-to-date `PR gate`, a pull request, linear
squash history, and resolved conversations; it rejects deletion and non-fast-
forward updates with no bypass actors. It also requires CodeQL to report no
error-level alerts and no security alert at medium severity or higher. The
reviewed payload records those thresholds as `alerts_threshold: errors` and
`security_alerts_threshold: medium_or_higher`. Ruleset `21093924` was read back
after the 2026-08-20 update with those exact thresholds, the sole strict
required status still set to `PR gate`, and every prior pull-request and no-
bypass protection intact. The active `v*` tag rule rejects update, deletion,
and non-fast-forward mutation. Verify the complete live rules after every
visibility, ownership, or plan change rather than trusting this prose.

The active `main` ruleset binds `PR gate` to GitHub Actions integration ID
`15368`; the context name alone is not sufficient provenance. Ruleset
`21093924` was independently read back after the authorized update with the
exact pair and every prior protection intact. Reverify the complete rule after
visibility, ownership, plan, or desired-state changes.

## Public hosted acceptance

Public pull requests run only on GitHub-hosted standard Linux runners. The
persistent `maru-local-certifier` registration was removed before Actions were
re-enabled, and repository-level self-hosted runner inventory must remain empty.
Fork pull-request acceptance receives only read permissions; do not add
`pull_request_target` execution of contribution code or expose environments,
package publication, or repository secrets.

GitHub may hold a first-time fork contributor's workflow until a maintainer
approves execution. That action permits the hosted job to start; it is not pull-
request approval, a code review, or permission to merge. Managed CodeQL default
setup does not analyze fork pull requests, and its native ruleset protection
does not cover Dependabot pull requests. The required `PR gate` still applies
to those pull requests, while managed CodeQL retains default-branch and weekly
scans. Review these coverage limits explicitly rather than interpreting a
missing pull-request CodeQL result as complete analysis.

The hosted `PR gate` retains ADR 0060's change-aware boundary: documentation-
only changes avoid PostgreSQL, ordinary Python work runs unit and bounded
affected integration tests, and high-risk paths invoke the complete eight-
shard reusable matrix. Targeted selection also routes to the full matrix when
the accepted timing map is unavailable, any selected file lacks an accepted
timing, or the estimate exceeds 1,800 seconds. This 30-minute execution ceiling
leaves 15 minutes for setup and runtime variance inside the targeted lane's
45-minute timeout. Before the full matrix fans out, a lightweight preflight
requires a current `uv.lock` and exact parity between every workflow reference
and `.github/actions-allowlist.json`. `scripts/certify.ps1` remains the required
local pre-review command, but its unsigned receipt is contributor evidence
rather than a server trust boundary. Details are in
[local exact-commit certification](local-certification.md), ADR 0063, and ADR
0064. The unit layer is database-free; successful full acceptance starts eight
independent PostgreSQL services for the eight whole-file integration shards.

For a ready pull request whose dedicated classifier output identifies a graph-
visible manifest, lock, or workflow change, the same `changes` job performs
GitHub dependency review before any selected path starts. It rejects graph-
visible dependencies introduced with a moderate-or-higher vulnerability in
runtime, development, or unknown scope. The step uses a read-only token, posts
no comment, and adds no job or required status; a failure makes `changes`
unsuccessful and therefore fails the stable `PR gate`.

## Public documentation deployment

ADR 0072 defines one separate publication path for the generated contributor
site. Pull requests validate Sphinx warning-fatally and retain an inspectable
artifact but receive no Pages, OIDC, environment, or preview authority. After
merge, `pages.yml` rebuilds from protected `main` with locked dependencies and
fresh temporary doctree/HTML directories. It checks current remote `main`
immediately before build and deployment, but does not lock the branch: a newer
queued run converges the site if `main` advances after the final check. It
starts no PostgreSQL service and does not repeat application acceptance.

The build job is read-only. Only its generated HTML root crosses into the
deployment job, whose authority is limited to `pages: write`, `id-token: write`,
and the `github-pages` environment. The live environment accepts only exact
`main`, disallows administrator bypass, and contains no reviewer, secret,
variable, or wait timer while Maru has one maintainer. Configure-time
enablement remains off; creating or changing the Pages site is a separately
authorized administrator operation.

The exact selected-Action policy includes all direct workflow references plus
explicitly audited immutable actions invoked inside a composite action. The
official `upload-pages-artifact` v5.0.0 pin invokes `upload-artifact` v7.0.0 at
its own fixed commit, so both references are required. The checked-in validator
rejects an audited nested reference whose exact composite parent is not used.
Do not resolve this dependency by enabling either broad GitHub-owned or
verified-creator trust flag.

GH-007 reconciled all 16 selected references, enabled workflow-source Pages,
protected `github-pages`, and verified the first exact-main deployment before
setting the homepage. Future Pages, runtime, environment, or homepage changes
must repeat the applicable exact-SHA API, HTTPS, content, asset, canonical,
version, and fresh-browser proof. Mermaid requests must remain inside the
exact-version Mermaid `11.16.1` and D3 `7.9.0` jsDelivr prefixes unless a new
decision changes the runtime; unused ELK support remains disabled. Keep Wiki
disabled. The public site is contributor documentation, not an application
deployment, release, or production approval. Follow the
[Pages publication runbook](../operations/github-pages-publication.md) for the
exact verification, reconciliation, and recovery procedure.

## Dependency update policy

Dependabot is security-only for the uv, npm, and GitHub Actions ecosystems.
Each entry uses `open-pull-requests-limit: 0` to suppress routine version-
update pull requests while retaining one grouped security-update rule. Python
uses the native `uv` ecosystem so a security update must keep `pyproject.toml`
and `uv.lock` coherent.

Dependency review is diff evidence, not a replacement for the current-tree
audits. It cannot catch an unchanged dependency whose vulnerability becomes
known later, and GitHub may omit unsupported or unparseable inputs. In
particular, it does not scan the `Dockerfile` base image. Maru therefore keeps
locked installation, `pip-audit`, `pnpm audit`, immutable Action validation,
source review, and release SBOM/provenance. Action-based license enforcement is
disabled until a separately accepted compatibility policy can distinguish
legal obligations without creating a brittle contributor allowlist.

At least quarterly, and before a candidate or gold release when dependencies
have changed materially, a maintainer creates one dependency-maintenance branch
from current `main`. Update Python manifests and `uv.lock` together, frontend
manifests and `pnpm-lock.yaml` together, and workflow SHAs and the exact Actions
allowlist together. Review major runtime and toolchain updates separately when
combining them would obscure compatibility risk. Run `scripts/certify.ps1`
before requesting review; never weaken locked installation or the allowlist to
make an update pass.

These Dependabot and full-acceptance preflight definitions are repository files.
They become the default-branch automation policy only when their reviewed pull
request is merged. A pull request can exercise its own candidate workflow, but
documentation of the candidate does not itself mutate GitHub settings or the
configuration currently present on `main`.

The dependency-review Action is pinned to verified v5.0.0 commit
`a1d282b36b6f3519aa1f3fc636f609c47dddb294`. Adding its exact twelfth pattern
to the live selected-Actions policy requires separate owner authorization, a
complete pre-read, an exact append that preserves both broad trust flags as
`false`, and a complete post-change readback. For pull request 11, that process
found the exact prior 11 patterns, added only the reviewed v5.0.0 reference, and
read back exact parity with the 12-entry checked-in allowlist. Ready-state run
`32531845794` then checked out synthetic merge candidate `105c9ac`, while the
Action compared base `cf0235f` with head `1d7f17a`. The pinned Action, complete
selected acceptance, and `PR gate` passed. Pull request 11 squash-merged as
`0d8af12`, completing GH-006 without enabling either broad trust flag.

## Immutable release boundary

Repository release immutability is enabled and must be read back with an
authenticated administrator session immediately before every manual Release
dispatch. Record the workflow input confirmation only after that read. Do not
store a repository-administrator token in `candidate` or `gold`; the release
workflow needs only scoped content, package, identity-token, and attestation
write permissions after complete certification.

The workflow publishes only from exact current `main`. It verifies the complete
draft asset set and digests before publication and then verifies immutable
server state, the exact tag commit, GitHub's release and per-asset attestations,
the OCI tag-to-digest binding, and image provenance. Candidate and gold allow
only exact `main`, disallow administrator bypass, and have no required reviewer
while one maintainer exists. Follow the complete procedure and irreversible
failure rules in [the release process](../operations/release-process.md) and ADR
0065. Wrong-branch, missing-immutability, invalid candidate/gold input
combinations, non-current `main`, version/changelog drift, identity collisions,
and a release PR that is not merged into `main` at the workflow commit fail
before complete source certification starts.

The same workflow requires exactly one non-empty dated `CHANGELOG.md` section
for the derived display CalVer. That curated section leads the GitHub Release
body; exact pull-request, commit, image, and asset evidence follows it, and
GitHub's generated categorized change list remains supplementary. A release PR
must never substitute generated titles for maintained operator-facing notes.

## Maintainer settings

Use squash merge, automatically delete merged branches, require immutable
Action SHAs, keep workflow tokens read-only by default, and grant write
permissions only to the release job and the issues-only, no-checkout stale-label
cleanup. Repository Actions run in `selected` mode;
`.github/actions-allowlist.json` must exactly match every external immutable
workflow reference plus every explicitly audited nested reference in
`.github/actions-transitive-references.json`. Composite Actions are executable
supply-chain boundaries: audit their pinned action definition, record each
exact nested SHA, and reconcile the complete checked-in set with the live
selected-Actions policy before relying on a workflow that invokes them. The
checked-in CODEOWNERS file is ownership discovery even before its review rule is
enabled.

All contributors follow `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
and `GOVERNANCE.md`. Architecture and requirements remain the durable decision
system; GitHub conversation does not silently supersede either.

## Public collaboration metadata

The authenticated GH-004 snapshot on 2026-08-21 reports 100 percent Community
Profile health, the intended eight repository topics, all labels referenced by
the Issue Forms and automation, and the feature state at that checkpoint:
Issues and Discussions enabled; Projects, Wiki, Pages, and Downloads disabled.
GH-007 subsequently enabled verified workflow-source Pages at
`https://martonpornoi.github.io/maru/` and set that exact URL as the repository
homepage. Projects, Wiki, and Downloads remain disabled. Wiki must not become a
manually maintained copy of the Sphinx source.

GH-007's reviewed Pages workflow, exact direct-and-nested Action policy, and
deployment contracts are accepted on `main`. The exact-main deployment, public
HTTP/content/assets, real-browser diagram, homepage, environment, Actions
policy, and Wiki readbacks are recorded in the append-only closure checkpoint.

The accepted live description is **Security-focused Django and PostgreSQL
platform for operating multi-convention events, under active development.** ADR
0070 records its separately authorized description-only mutation and exact
post-change readback. Keep the existing topics. A custom social preview and
funding configuration remain deferred until the project has, respectively, a
purpose-built approved asset and a real recipient plus stewardship decision.
The preview is a live setting; funding links normally come from committed
`.github/FUNDING.yml`, while connecting a recipient is separate external
stewardship work.

Issues are the bounded execution queue for observable defects and scoped
proposals. Requirements and accepted ADRs remain authoritative, `ROADMAP.md`
sets direction, `CURRENT.md` carries the maintained handoff, and Discussions
hold setup/design exploration. Do not bulk-copy historical todo documents into
Issues or enable Projects without demonstrated triage volume. Issue Forms ask
for preparation, affected behavior, acceptance boundaries, non-goals,
traceability, and safety evidence without collecting personal or secret data.
The dedicated umbrella form is reserved for one bounded end-to-end outcome that
requires multiple independently closable children. Each child uses GitHub's
native sub-issue relationship and names its owned checklist item, acceptance,
dependencies, and inherited non-goals. The hierarchy records membership and
progress; the umbrella body records scope and dependency truth and remains open
through integrated acceptance.

Root `GOVERNANCE.md` is the authority and continuity policy;
`CODE_OF_CONDUCT.md`, `SECURITY.md`, and `SUPPORT.md` own their respective
reporting channels and expectations. This document owns technical branch,
workflow, and repository-setting mechanics. Do not collapse those roles into a
single ambiguous "governance" link.

The current Code of Conduct deliberately provides no private Maru-specific
conduct channel. Do not infer an address, repurpose private vulnerability
reporting, or direct sensitive details into a public issue. Any future private
channel requires an explicit policy change, an operational owner, and defined
independent-review and retention boundaries.
