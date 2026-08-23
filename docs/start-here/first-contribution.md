# Make a first contribution

**Audience:** New code and documentation contributors\
**Outcome:** Choose a reviewable task and take it through Maru's protected
workflow\
**Reading time:** 10 minutes

A good first contribution is bounded, testable, and connected to an existing
requirement or a clearly documented repository need. Prefer a focused
documentation correction, missing test, accessibility improvement, or isolated
bug over a new cross-module abstraction.

## Before editing

1. Read the repository's
   [contribution guide](https://github.com/martonpornoi/maru/blob/main/CONTRIBUTING.md).
2. Read the [current project state](../project/CURRENT.md) and
   [roadmap](../project/ROADMAP.md).
3. Find the relevant requirement, module guide, and accepted architecture
   decisions.
4. Inspect the implementation and existing tests before proposing a design.
5. Create a branch from current `main`; direct pushes to `main` are not the
   collaboration workflow.

## While working

- Preserve organization and event-edition scope and deny access by default.
- Use only synthetic people, organizations, conventions, addresses, and
  examples.
- Update implementation, tests, documentation, and current-state handoff
  together when the change is material.
- Record durable architecture changes in a new ADR instead of silently changing
  an accepted decision.

## Before review

Run focused checks while iterating, then follow the
[local certification guide](../development/local-certification.md) for the
complete exact-commit evidence expected before review. GitHub independently
evaluates the pull-request merge candidate; local evidence does not replace the
protected `PR gate`.

The [repository governance guide](../development/repository-governance.md)
explains draft behavior, destructive-change review, dependency policy, and
merge protection. The [build and contribution catalog](../development/index.md)
collects the remaining engineering standards.

**You are ready to choose a bounded issue and create a branch.**
