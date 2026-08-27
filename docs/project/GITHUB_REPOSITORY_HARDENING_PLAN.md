# GitHub repository hardening plan

Status: GH-000, GH-001, and GH-003 through GH-007 complete; GH-002 repository
verification implemented with its first candidate rehearsal pending; GH-008
and GH-009 tracked

Requirements: NFR-001, NFR-002, NFR-003, NFR-011

## Purpose

Evolve Maru's public-repository controls through small, independently
reviewable milestones. A completed milestone may be committed and merged after
its own requirements, tests, documentation, and external-state evidence are
complete. GH-002 through GH-009 are a maintained backlog; they do not block the
GH-000 and GH-001 repository-hardening milestone.

GitHub settings are external state and cannot be contained in a repository
commit. A plan or checked-in desired-state file does not authorize a remote
write. Each accepted setting change requires separate authorization, a
read-only observation before mutation, and a read-only reconciliation after
mutation. The relevant checkpoint records those observations separately from
the committed tree.

## Verified public baseline

The 2026-08-20 live audit, refined by the 2026-08-21 GH-003 audit, established
the following starting point:

- the public repository has active no-bypass rulesets for `main` and `v*`;
- `main` requires the up-to-date repository-owned `PR gate`, pull requests,
  resolved conversations, squash-only linear history, and deletion and
  non-fast-forward protection;
- Actions use read-only default permissions, selected exact-SHA references,
  first-time-contributor approval, and no self-hosted runner;
- CodeQL default setup, secret scanning, push protection, Dependabot security
  updates, and private vulnerability reporting are enabled;
- there was no open CodeQL, Dependabot, or secret-scanning alert on `main`;
- candidate and gold environments accept only `main` deployments; and
- release immutability was disabled at the initial inspection; it was enabled
  and read back later on 2026-08-20; and
- standard secret scanning and push protection are enabled. Validity checks and
  generic-pattern scanning were unavailable for this user-owned repository at
  the 2026-08-21 GH-003 audit boundary and remain deferred.

Live values can drift. This baseline is evidence for the recorded date, not a
substitute for the pre-change read required by a later milestone.

## Milestone GH-000 and GH-001: repository supply-chain boundary

The first focused hardening commit completes this milestone. ADR 0064 records
the durable decision and NFR-011 provides the stable requirement.

### GH-000: Security-only dependency automation and fail-fast inputs

Routine grouped Dependabot pull requests exposed incompatible automation
assumptions: Python metadata could change without the `uv.lock` result, a broad
npm group could cross an incompatible major version, and an Actions updater
could not change both workflow SHAs and Maru's exact Actions allowlist. These
were routine version updates rather than responses to open security alerts.

Accepted and implemented outcome:

- Dependabot uses the native `uv`, npm, and GitHub Actions ecosystems only for
  grouped security updates;
- `open-pull-requests-limit: 0` suppresses routine version-update pull requests
  without disabling security updates;
- ordinary dependency maintenance moves to a maintainer-owned branch at least
  quarterly and before a release when material dependency drift exists;
- manifests and locks, and workflow SHAs and the exact allowlist, must be
  reviewed together; and
- complete hosted acceptance starts with a lightweight `uv lock --check` and
  exact Actions-allowlist validation before expensive jobs fan out.

The preflight does not weaken or replace locked installation, dependency
audits, immutable Action revisions, or the hosted merge-candidate gate.

Decision state: complete in this repository milestone.

### GH-001: Explicit CodeQL protection and ruleset reconciliation

The previous live ruleset required only `PR gate`; managed CodeQL influenced
merging indirectly. Medium-severity exception and redirect findings proved
actionable at Maru's personal-data and authorization boundary, so high-only
security enforcement would be too permissive.

Accepted and implemented outcome:

- the normalized `main` ruleset requires CodeQL general alerts to remain below
  `errors` and security alerts to remain below `medium_or_higher`;
- `PR gate` remains the sole required status check;
- the native rule consumes GitHub-managed default CodeQL instead of adding a
  duplicate repository workflow;
- repository contracts assert the exact normalized CodeQL tool and thresholds;
  and
- live reconciliation submits only documented desired inputs, then verifies
  CodeQL, status, pull-request, deletion, non-fast-forward, enforcement, and
  bypass protections without copying undocumented server response fields into
  the write payload.

Ruleset `21093924` was separately authorized, applied, and re-read on
2026-08-20. It reported the accepted CodeQL thresholds, strict `PR gate`,
pull-request-only squash history, resolved conversations, deletion and
non-fast-forward protections, active enforcement, an empty bypass list, and
`current_user_can_bypass: never`. The milestone checkpoint remains the durable
evidence boundary for this external mutation.

Decision state: complete in the repository and reconciled live.

### Included repository changes

The focused GH-000/GH-001 commit contains only their coherent outcome:

- security-only Dependabot configuration;
- the reusable full-acceptance lock and Actions-policy preflight;
- the repository-owned exact Actions-allowlist validator;
- the normalized CodeQL ruleset desired state and repository contracts;
- ADR 0064, NFR-011, operating guidance, this maintained plan, the concise
  current-state handoff, current public-state corrections, and one append-only
  completion checkpoint.

It does not contain a release, tag, package, deployment, generated Sphinx HTML,
GitHub setting mutation, collaborator change, or implementation from GH-002
through GH-009.

### Acceptance boundary

Before this milestone is merged:

1. Dependabot, preflight, allowlist, and normalized ruleset contracts pass.
2. Ruff, PyDocLint where affected, the documentation validator, and whitespace
   validation pass.
3. The workflow-sensitive hosted full-acceptance path passes for the exact
   branch commit.
4. `docs/project/CURRENT.md` and the completion checkpoint distinguish
   repository state, live external state, verification, remaining risks, and
   the smallest next actions.
5. The completed milestone may merge without resolving any later GH item.

## Remaining tracked milestones

Each item below is a separate reviewed milestone or explicitly recorded
decision. Its completion criteria and any external write are scoped to that
item. Multiple focused commits may travel on the same hardening branch without
combining their decision or checkpoint boundaries.

### GH-002: Immutable releases and deployment environments

Repository release immutability is enabled and the administrator endpoint was
read back as `enabled: true`, `enforced_by_owner: false`. No release or tag
exists. Candidate and gold remain exact-`main`, disallow administrator bypass,
have no required reviewer, secret, variable, or deployment, and stay unchanged
while Maru has one maintainer.

ADR 0065 accepts the repository verification boundary. Immediately before
dispatch, the maintainer must re-read the administrator-only immutability
endpoint and record confirmation in the manual workflow input. The release then
stages every asset on a draft, verifies the exact commit, tag, asset set, upload
state, and local/remote digest equality, and publishes only that verified draft.
After publication it requires immutable state, GitHub release and per-asset
attestations, the exact remote tag commit, the image tag's certified digest, and
OCI provenance issued by Maru's exact Release workflow. It stores the available
evidence even after a later verification failure and never introduces a long-
lived administrator token.

The first `rc.1` remains separately authorized because it creates a real public
prerelease and GHCR image. It needs a dedicated release pull request and the
complete release procedure after this repository candidate is merged.

The current GitHub-experience branch adds the missing public-note contract:
externally meaningful work is curated under `CHANGELOG.md` **Unreleased**, a
release pull request creates one dated section matching the derived CalVer and
merge date, and the workflow places that exact content before source/image
evidence and GitHub's supplemental generated notes. Live issue #21 tracks the
separately reviewed first-candidate procedure; it is not publication
authorization.

State: live setting reconciled and repository verification implemented; first
candidate rehearsal pending.

### GH-003: Secret validity and one-time public-history audit

ADR 0067 records the bounded launch decision. The one-time audit covered the
four public branch heads and eight pull-request heads as one 46-commit graph,
verified reachable Git objects strictly, and scanned the current repository
candidate separately. A checksum-verified Gitleaks 8.30.1 archive produced one
sanitized documentation false-positive category and zero unresolved secret
findings. Public issue, pull-request, and discussion metadata, seven tracked
owner-attested project-controlled brand assets and their embedded metadata, and
dependency-license and notice obligations were also reviewed. The audit did not
independently prove asset ownership or cover historical-only assets. Maru-owned
source remains Apache-2.0; Python distribution metadata and the release
application manifest represent bundled MIT Staff Console code with the
`Apache-2.0 AND MIT` expression. Release assets and the OCI image carry the
license and third-party notice, and the image carries SBOM and provenance; no
aggregate image-wide license expression is asserted. No remaining publication
blocker or raw finding was committed within the audited scope.

GitHub-hosted Actions log and artifact bytes were not downloaded or scanned. A
drift-prone snapshot observed 62 workflow runs and 188 unexpired artifacts under
short retention, so GH-003 does not claim to cover all public server-generated
bytes.

Standard GitHub secret scanning and push protection stay enabled. Validity
checks and generic-pattern scanning were unavailable for the current user-owned
repository, so they remain deferred pending eligibility, provider-contact, and
synthetic-fixture noise review. No GitHub setting was changed and no permanent
pull-request history scanner was added. The owner accepted the already-public
personal Gmail author metadata without rewriting history; future maintainer
commits use a GitHub no-reply address by default.

State: complete as a bounded repository and security-audit milestone. Repeat a
whole-history audit only after a material visibility, ownership,
imported-history, or incident boundary.

### GH-004: Public policy and repository-description consistency

Reconcile README, security, support, conduct, governance, public-readiness, and
repository metadata with the actual public state. Remove private or pre-launch
wording, link the private vulnerability form, refresh evidence summaries, and
keep the active-development and production-readiness boundary explicit.

The 2026-08-21 authenticated audit reports 100 percent Community Profile
health, an accurate eight-topic set, every label consumed by Issue Forms and
automation, and the then-intended Issues/Discussions-on and
Projects/Wiki/Pages/Downloads-off feature shape. GH-007 subsequently enabled
verified Pages publication and set its exact URL as the homepage; Wiki,
Projects, and Downloads remain off. Funding and a custom social preview are
deliberately deferred instead of receiving placeholders. ADR 0070 accepts the
live description **Security-
focused Django and PostgreSQL platform for operating multi-convention events,
under active development.** Its separately authorized description-only change
and exact post-change readback are complete.

The repository candidate replaces brittle README evidence, fixes support and
security discovery, defines best-effort triage and safe `good first issue`
criteria, and records a truthful sole-maintainer continuity policy. GH-003
already completed the bounded public-material audit; GitHub-hosted log and
artifact bytes remain its documented exclusion rather than unfinished GH-004
scope.

The owner declined to publish a login or historical personal address or create
a placeholder mailbox. The candidate explicitly records that no private
project-specific conduct channel or independent reviewer exists, warns against
sensitive public reports and security-advisory misuse, and scopes GitHub's
abuse route to GitHub-hosted behavior.

The current GitHub-experience branch adds a purpose-built README header and
direct public navigation, and refines Issue Forms around bounded outcomes,
non-goals, traceability, safety, and sanitized evidence. Issues #21 through #24
are the first maintained execution queue. Projects remains disabled; these
issues do not replace requirements, accepted ADRs, the roadmap, or the current
handoff and do not promise response or delivery.

State: complete. GH-008 retains actual multi-maintainer succession, independent
moderation/security rotation, and approval/release separation.

### GH-005: Post-merge CI duplication

Pull request 8 supplied the required measurement. Draft open, draft synchronize,
ready-for-review, and squash-push runs consumed 1,436.66 aggregate runner-
minutes. The ready run checked synthetic merge commit `9899c1f`; its tree, the
final pull-request head tree, and the squash-commit tree were identical, so the
359.40-runner-minute main workflow repeated accepted content. The ready event
was also associated with the preceding draft head. Accepted main run
`32427570856` supplied a current JUnit timing inventory for all 157 then-current
integration files.

ADR 0066 accepts the repository correction:

- drafts run only classification plus locked-input and Actions-policy preflight,
  with an explicitly non-green `PR gate` until **Ready for review**;
- ready opens, synchronizations, reopenings, and `ready_for_review` run selected
  authoritative acceptance, while `converted_to_draft` cancels obsolete work;
- the pull-request workflow no longer repeats on the squash push to `main`;
- managed CodeQL retains its default-branch push scan, and manual and release
  full certification remain available;
- repository safety precedes expensive fan-out, protected renames are treated as
  deletions, every destructive change takes full acceptance, and approval is
  consumed only by the exact fresh repository-owner label event;
- an issues-only, no-checkout `pull_request_target` workflow clears stale label
  display state without executing contribution code or serving as a relied-upon
  acceptance retrigger; and
- the database-free unit boundary reduces full certification from nine to eight
  PostgreSQL services while the accepted timing refresh improves shard balance;
  missing timings or a targeted estimate over 1,800 seconds route to full
  acceptance.

The repository correction itself changed no live rule. Ruleset `21093924` was
subsequently updated under separate authorization and independently re-read
with `PR gate` bound to GitHub Actions integration ID `15368` and every prior
protection intact. Label events remain intentionally conservative
because GitHub treats skipped required jobs as successful, cannot filter the
pull-request trigger by label name, and suppresses recursive workflow events
from the cleanup workflow's GitHub token.

Draft pull request 9 proved that ADR 0066's trailing-comma-only CodeQL
correction was insufficient: run `32483580306` stayed green while its Python
log repeated the raw syntax diagnostic and omitted `workforce/queries.py`.
ADR 0069 supersedes that compatibility mechanism with one equivalent bounded
`TypeVar`, a line-level `UP047` exception, and a repository guard against the
known incompatible header shapes.

State: complete. Managed run `32485597468`, Python job `96781280766`, explicitly
extracts `workforce/queries.py` with zero raw diagnostic at commit `6317538`.
Corrected ready-state run `32504876594` passed every selected full-acceptance
category at head `7b7add0`; CodeQL run `32504873965` passed all three languages;
pull request 9 squash-merged as `a42358b`. The live required-status provenance
binding is reconciled.

### GH-006: Dependency review

ADR 0071 accepts dependency-diff review as a complement to locked resolution,
`pip-audit`, `pnpm audit`, Dependabot, exact Action validation, and release
evidence. The live graph contains 294 entries: 108 PyPI packages, 173 npm
packages, 12 GitHub Actions, and the root repository document. Read-only
comparisons recognize Maru's `uv.lock`, `pyproject.toml`, Staff Console
`pnpm-lock.yaml`, and workflow inputs.

The merged default-branch control runs verified v5.0.0 commit
`a1d282b36b6f3519aa1f3fc636f609c47dddb294` as one step in the existing
`changes` job when a ready pull request's dedicated classifier output identifies
a graph-visible manifest, lock, or workflow change. It rejects introduced
moderate-or-higher vulnerabilities in runtime, development, and unknown scopes
with patched-version guidance. The workflow remains
`contents: read`, posts no pull-request comment, disables OpenSSF Scorecard and
license enforcement, and adds no job, required status, runner startup, or
PostgreSQL service. Failure flows through the existing stable `PR gate` and
prevents selected fan-out.

The current-tree audits remain mandatory. Pull request 9's already-present
vulnerable `pip 26.1.2` demonstrates the gap in any diff-only control. GitHub's
graph can also omit unsupported inputs and does not cover the `Dockerfile` base
image. License automation remains deferred until a bounded compatibility policy
is accepted.

State: complete. The separately authorized live update followed an exact
11-pattern pre-read and was independently read back at 12 unique immutable
patterns, with selected-only trust, mandatory SHA pinning, and both broad trust
flags preserved. Ready-state run `32531845794` checked out synthetic merge
candidate `105c9ac`, executed the pinned Action successfully against base
`cf0235f` and head `1d7f17a`, and passed complete selected acceptance plus
`PR gate`. Pre-merge CodeQL run `32531757710` passed all three languages. Pull
request 11 squash-merged as `0d8af12`; its accepted head, synthetic merge, and
squash merge share tree `3e84dde66be774e7b293471c699978f8ed7ba8bc`.
Post-merge CodeQL run `32553943756` passed all three languages on `main`.

### GH-007: Sphinx publication through GitHub Pages

Design a main-only Pages workflow that rebuilds the warning-fatal Sphinx and
AutoAPI site from locked dependencies and deploys only generated HTML. Pin and
allowlist all Pages Actions, constrain deployment to `github-pages`, derive the
displayed version from `pyproject.toml`, and set the repository homepage only
after the first verified deployment. Do not create a Wiki mirror.

State: complete. Pull request 13's ready-state run was associated with head
`a0b3fd6` while its checkout-bearing jobs tested synthetic merge `e988f050`;
both and eventual squash merge `b50e665` share exact tree `8fa25b99`.
Main-triggered Pages run `32565940418` built, verified, uploaded, and deployed
the fresh site from that exact merge SHA. The dedicated Pages deployment
endpoint reports `succeed`;
root, nested guide, AutoAPI, CSS, and search assets return HTTP 200; and a fresh
browser run rendered the maintained Mermaid diagram with zero console errors,
no unexpected external script path, and no ELK request.

The live selected policy contains the exact 16 reviewed references with both
broad trust flags false and mandatory SHA pinning. Environment `github-pages`
retains no administrator bypass and accepts only branch `main`, with no
reviewer, secret, variable, or wait timer. The repository homepage is the exact
public HTTPS Pages URL, and Wiki remains disabled. The implementation continues
to separate read-only build authority from Pages write/OIDC deployment
authority and models the official uploader's immutable nested Action.

### GH-008: Multi-maintainer governance

Defer organization transfer, secure 2FA enforcement, CODEOWNER approval,
latest-push approval, gold-environment review, actual successor appointment,
and independent moderation/security rotation until a second trusted maintainer
exists. Enabling them for one maintainer would deadlock work or create
meaningless self-approval.

Before an organization transfer or another account may approve destructive
scope, replace the current `github.actor == github.repository_owner` check with
an explicitly reviewed maintainer authority policy. Reassess the live
`first_time_contributors` fork-workflow approval setting if hosted-compute abuse
appears; `all_external_contributors` is stronger but creates recurring
maintainer approval work for safe external runs.

State: deliberately deferred until the prerequisite exists.

### GH-009: Rejected or demand-triggered controls

Maintain explicit reasons to avoid or defer signed-commit enforcement under
GitHub squash limitations, merge queues at low concurrency, preview coverage
rules, broad security-extended CodeQL, overlapping scanners and dependency
bots, stale-issue automation, mandatory CLA or DCO, Projects without triage
volume, self-hosted pull-request runners, and `pull_request_target` execution of
contribution code.

State: tracked decision register; individual controls require new evidence and
a focused decision before adoption.

## External settings ledger

| Setting | Observed state | Tracked outcome | Milestone |
| --- | --- | --- | --- |
| CodeQL merge protection | Active: `errors` and `medium_or_higher` | Accepted and reconciled | GH-001 |
| Required status provenance | `PR gate` bound to GitHub Actions integration `15368` | Accepted and reconciled; re-read after visibility, ownership, or plan drift | GH-005 |
| Release immutability | Enabled directly on Maru; no release or tag | Re-read before every dispatch; require immutable post-publication evidence | GH-002 |
| Candidate environment | Exact `main`; no admin bypass or reviewer | Keep unless operational separation is needed | GH-002 |
| Gold environment | Exact `main`; no admin bypass or reviewer | Add independent review only with a second maintainer | GH-002/GH-008 |
| Secret scanning | Enabled; no unresolved alert at the 2026-08-21 audit boundary | Keep enabled and triage every alert | Continuous/GH-003 |
| Push protection | Enabled | Keep enabled; use only synthetic non-secret fixtures for exercises | Continuous/GH-003 |
| Secret-validity checks | Unavailable for the current user-owned repository | Reassess eligibility and provider contact after an ownership or plan change | GH-003 |
| Generic-pattern scanning | Unavailable for the current user-owned repository | Reassess eligibility and synthetic-fixture noise before enablement | GH-003 |
| Actions selected allowlist | Live: exact 16 immutable direct/audited-nested references | Keep selected-only trust, SHA pinning, and both broad trust flags false | Every workflow milestone |
| Repository description | 2026-08-21: security-focused Django/PostgreSQL multi-convention platform, under active development | Accepted and reconciled under ADR 0070; future changes require separate authorization and readback | GH-004 |
| Repository topics | 2026-08-21: exact accepted eight-topic set | Retain; change only when product scope changes materially | GH-004 |
| Community and issue metadata | 2026-08-21: 100 percent profile health; required Issue Form and automation labels exist | Keep templates, labels, and public policies coherent; do not manufacture newcomer issues | GH-004 |
| Social preview | Default generated preview | Defer until an approved purpose-built asset exists | GH-004 |
| GitHub Pages source | Workflow-based public HTTPS site at `https://martonpornoi.github.io/maru/` | Publish only fresh protected-`main` workflow artifacts | GH-007 |
| `github-pages` environment | Exact branch `main`; no admin bypass, reviewer, secret, variable, or wait timer | Reconcile after ownership, default-branch, or deployment-policy drift | GH-007 |
| Repository homepage | Exact verified Pages URL | Update or clear only with a separately authorized Pages reconciliation | GH-007 |

## Completion rule for later milestones

A later GH item is complete when its bounded decision, implementation, tests,
documentation, and checkpoint are coherent. Durable architecture or governance
changes receive an ADR; product-wide contracts map to a stable requirement.
Appropriate local checks and the risk-selected hosted path must pass. External
settings remain separately authorized and reconciled. Completion of one item
does not require bundling unrelated backlog items into the same commit.
