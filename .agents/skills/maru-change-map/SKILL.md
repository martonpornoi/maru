---
name: maru-change-map
description: "Map a material Maru implementation, diagnosis, or review to current requirements, ADRs, owning modules, trust boundaries, tests, and documentation before changing code. Use for work that crosses a product or technical contract; do not use for trivial formatting or a self-contained factual answer."
---

# Maru Change Map

Turn a material request into a bounded evidence map, then proceed with the work.
The map is a thinking aid, not another project artifact unless the user asks for
a plan or the decision belongs in maintained documentation.

## Establish current truth

1. Follow the repository reading order in `AGENTS.md`.
2. Treat [CURRENT](../../../docs/project/CURRENT.md), the
   [roadmap](../../../docs/project/ROADMAP.md), requirements, accepted ADRs,
   module documentation, code, and tests as the authority. Never copy a current
   status snapshot into this skill.
3. Classify the request as an answer, diagnosis, product decision,
   implementation, review, rehearsal, or delivery operation. Preserve the
   authority implied by that request type.
4. Inspect the existing implementation and tests before proposing a new
   abstraction or boundary.

## Build the compact map

Identify, in working notes:

- the human outcome and explicit non-goals;
- stable requirement identifiers and accepted or needed ADRs;
- the owning module and its public commands, queries, events, APIs, and pages;
- organization, edition, principal, relationship, field, and lifecycle scope;
- privacy, retention, audit, observability, recovery, and degraded behavior;
- migrations, runtime-role implications, generated artifacts, and rollback or
  fix-forward boundaries;
- focused checks needed while iterating and the authoritative acceptance gate;
- affected product, architecture, module, API, operations, role, current-state,
  and checkpoint documentation.

Keep the map proportional. A localized documentation correction may need only a
sentence; a privileged cross-module mutation needs every relevant boundary.

## Load detail only when relevant

- For commands, protected reads, APIs, events, database invariants, migrations,
  or runtime roles, read
  [the governed-workflow reference](references/governed-workflow.md).
- For a management or personal interface, navigation, forms, drawers, or
  responsive behavior, read
  [the management-surface reference](references/management-surface.md).
- For repository automation or delivery policy, use
  [repository governance](../../../docs/development/repository-governance.md)
  and [local certification](../../../docs/development/local-certification.md)
  rather than inventing a parallel process.

## Execute and close

Implement one coherent outcome through the owning boundary. Preserve unrelated
worktree changes, verify in proportion to risk, and update the current handoff
and affected documentation. Distinguish focused local evidence, hosted merge
acceptance, deployment evidence, and production approval; none substitutes for
another.
