# Contributing to Maru

Maru welcomes code, tests, documentation, accessibility observations, and
experience from furry convention operations. Start with one problem you can
explain and verify; you do not need to learn the whole platform first.

For a guided route, use [Make a first contribution](docs/start-here/first-contribution.md).
For application setup, use [Run Maru locally](docs/start-here/run-locally.md).

## Issue triage and newcomer work

- Search [Issues](https://github.com/martonpornoi/maru/issues) for existing bugs
  and bounded proposals. Small documentation corrections and isolated fixes
  may go directly to a pull request.
- Use [Discussions](https://github.com/martonpornoi/maru/discussions) for setup
  help and ideas that still need exploration. Discuss substantial behavior or
  architecture changes before implementing them.
- Report vulnerabilities privately through [SECURITY.md](SECURITY.md).
- Use synthetic data only. Do not include real convention records, personal
  data, secrets, or private material in issues, screenshots, tests, or fixtures.

An issue earns `good first issue` only when it has a bounded outcome, observable
acceptance criteria, usable setup and verification commands, and no private data,
maintainer-only access, or hidden cross-module prerequisites. The list may be
empty. `help wanted` can cover broader work; neither label reserves a task,
promises scheduling, or pre-approves a design. Support is best effort.

Requirements and accepted ADRs own product and architecture decisions.
[ROADMAP](docs/project/ROADMAP.md) sets direction, and
[CURRENT](docs/project/CURRENT.md) records the active handoff. Issues are the
execution queue, not a second roadmap. Use the feature-proposal form for one
independently closable outcome; use the umbrella form for a bounded outcome
that requires dependent child issues. The native GitHub sub-issue relationships record
membership, while the umbrella describes scope, dependencies, and integrated
acceptance. Update that contract when a split changes.

## Make one coherent change

Fork the repository if needed, branch from current `main`, and use a descriptive
name such as `docs/clearer-setup` or `fix/readiness-timeout`.

For material work, follow the reading order in [`AGENTS.md`](AGENTS.md): current
state, roadmap, relevant requirements and module docs, accepted ADRs, then
current code and tests. Preserve organization/edition scope, deny-by-default
access, auditability, recovery, and module ownership.

Keep implementation, tests, and documentation together. Product behavior maps
to a stable requirement; durable architecture decisions need an ADR. Update
`CURRENT.md` for material work and add a checkpoint for milestones and externally
visible features. Add contributor- or user-visible changes under **Unreleased**
in [CHANGELOG.md](CHANGELOG.md). Use `Not user-visible` in the pull-request
release-note field only when no evaluator, operator, user, or contributor
behavior changes.

Follow [documentation standards](docs/quality/documentation-standards.md),
including meaningful NumPy-style Python docstrings. Agent-assisted work follows
the same rules; the [agent workflow guide](docs/development/agent-workflows.md)
explains the focused playbooks. Tools and generated output grant no additional
authority, and the contributor remains responsible for the diff and evidence.

## Verify and request review

Run focused checks while developing, then install the push guard and complete
local certification of a clean commit before marking the pull request ready:

```powershell
./scripts/install_git_hooks.ps1
./scripts/certify.ps1
```

The [local certification guide](docs/development/local-certification.md) defines
prerequisites, scope selection, evidence preservation, and the shared
local/hosted policy. Current-schema PostgreSQL behavior remains required for
code changes; relevant historical and recovery checks follow the change's risk.
`-Mode Full` explicitly requests exhaustive history. Diagnostic runs do not
replace certification.

Open unfinished work as a draft. Draft updates run cheap feedback and
intentionally leave `PR gate` red. After local certification passes, **Ready for
review** starts independent hosted acceptance. First-time fork runs may await a
maintainer's execution approval; that is not approval of the contribution.

Complete the pull-request template with the outcome, security/privacy impact,
migrations/recovery, checks, documentation, and remaining work. Resolve review
conversations. The repository uses protected squash merges; local evidence does
not replace GitHub's `PR gate`.

Large deletions and deletion or rename of protected source, test, automation,
governance, or critical root files require the owner's exact-head
`destructive-change-reviewed` label event. A stale label is not approval. The
[repository governance guide](docs/development/repository-governance.md) owns
that policy and the full protected workflow. Do not weaken checks to make a
change pass.

By contributing, you agree that your contribution is licensed under
[Apache-2.0](LICENSE) and that the [Code of Conduct](CODE_OF_CONDUCT.md) applies
to project spaces. [Governance](GOVERNANCE.md) explains maintainer authority and
continuity.
