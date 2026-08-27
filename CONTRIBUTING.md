# Contributing to Maru

Thank you for improving Maru. The project is open for public collaboration,
but its security, privacy, tenant-isolation, and audit boundaries already apply
to every change.

## Before you start

1. Search existing issues and discussions before proposing overlapping work.
2. Open an issue for behavior changes or architectural work. Small documentation
   and clearly isolated fixes may go directly to a pull request.
3. Never report a vulnerability in a public issue; follow [SECURITY.md](SECURITY.md).
4. Read [the development setup](docs/development/setup.md),
   [testing strategy](docs/quality/testing-strategy.md), and
   [documentation standards](docs/quality/documentation-standards.md).
5. If a coding agent will participate, read the
   [agent-assisted workflow guide](docs/development/agent-workflows.md) and keep
   the same human review and evidence obligations.

## Development workflow

- Branch from current `main`; do not work directly on `main`.
- Use a descriptive branch name such as `feature/registration-export` or
  `fix/readiness-timeout`.
- Keep one coherent outcome per pull request and include tests and documentation.
- Add or update a stable product requirement identifier for product behavior.
- Record durable architecture decisions as ADRs; never rewrite an accepted ADR.
- Add externally meaningful changes to the appropriate **Unreleased** category
  in [`CHANGELOG.md`](CHANGELOG.md); write `Not user-visible` in the pull-request
  release-note field only when no evaluator, operator, user, or contributor
  behavior changes.
- Use synthetic data only. Never commit production data, secrets, credentials,
  private keys, tokens, or customer-identifying examples.
- Use NumPy-style Python docstrings and keep parameters, returns, yields, raises,
  notes, and examples meaningful where they help a contributor.

Activate the repository-managed push guard once after cloning:

```powershell
./scripts/install_git_hooks.ps1
```

Run the local acceptance command before requesting review:

```powershell
./scripts/certify.ps1
```

For a focused change, run the smallest relevant tests during development. The
full local command remains the contributor's pre-review obligation, but its
receipt is not a server trust boundary. Every ready pull request independently
satisfies the repository-owned `PR gate` on isolated GitHub-hosted runners.
Low-risk changes use a fail-closed affected-test plan; workflows, dependencies,
models, migrations, settings, security boundaries, and test infrastructure run
the complete hosted acceptance matrix.

Open unfinished work as a draft. Draft updates run only the cheap locked-input
and automation-policy feedback and intentionally keep `PR gate` red. After the
complete local certification passes, choose **Ready for review** to start the
authoritative hosted path. Converting back to draft cancels obsolete acceptance.

## Agent-assisted contributions

Repository-root [`AGENTS.md`](AGENTS.md) is the always-on project contract.
Maru also provides focused playbooks under `.agents/skills/` for change
mapping, product planning, browser rehearsal, and protected pull-request
delivery. Use the smallest matching set and load routed references only when
the task needs them.

These playbooks do not grant authority to implement, push, merge, deploy,
change repository settings, or use personal data. They do not turn generated
output into accepted behavior. The contributor remains responsible for
checking current requirements and ADRs, inspecting the actual diff, running
appropriate tests, documenting the outcome, and satisfying the protected
`PR gate`.

## Issue triage and newcomer work

Requirements and accepted ADRs remain the product and architecture authority.
`ROADMAP.md` sets direction, while `CURRENT.md` records the maintained handoff.
GitHub Issues are the bounded execution queue: each accepted issue should name
one observable outcome, affected roles and states, explicit non-goals,
dependencies, safety implications, and acceptance evidence. Closing an issue
does not silently change a requirement or decision; the corresponding pull
request updates those documents when needed.

Use Discussions for setup help and ideas that still need exploration. Do not
copy every historical backlog note into GitHub or use Issues as a second
roadmap. Convert maintained next actions only when they are sufficiently
bounded to implement, review, and close.

New bug reports and proposals start with the `triage` label. The maintainer may
request a synthetic reproduction, redirect a support question to Discussions,
link a duplicate, or decline work that does not fit the roadmap. Labels express
current classification, not a promise of scheduling or a response-time SLA.

An issue receives `good first issue` only when it is independently bounded,
contains observable acceptance criteria and relevant setup or verification
commands, needs no private data or maintainer-only access, and avoids hidden
security, migration, or cross-module prerequisites. `help wanted` may identify
broader work that still needs design discussion. Comment before investing in a
large implementation, because a label is not a reservation or pre-approval of
a particular design.

## Pull requests

Complete the pull request template. Explain the user or operator outcome,
security/privacy implications, migrations and recovery, tests, documentation,
and any intentionally deferred work. Resolve review conversations and use
squash merge so `main` remains linear.

Large deletions and any deletion or rename of source, tests, repository
automation, governance records, or critical root policy/deployment files
require the repository owner to apply `destructive-change-reviewed`. Under the
current sole-maintainer policy, automation accepts approval only on that exact
owner label-application event for the current head; every other pull-request
action treats an existing label as stale. A trusted metadata workflow also
removes the stale label after a head change, so the owner must inspect the new
scope and reapply it. Readiness and reopen transitions clear stale approval too.
Mark a destructive pull request ready before applying the label. Automation
must not be weakened
merely to make a check green. If a check is wrong, fix its contract and explain
why.

Eligible contribution-code `pull_request` runs from a first-time fork
contributor may wait for a maintainer to approve execution. That permits
untrusted code to run with read-only authority on an isolated hosted runner; it
does not approve the pull request or its changes. The trusted base-branch
metadata cleanup is not subject to fork-code approval and never checks out the
contribution.

By submitting a contribution, you agree that it is licensed under the
[Apache License 2.0](LICENSE) and that the [Code of Conduct](CODE_OF_CONDUCT.md)
applies to project spaces.
