---
name: maru-product-planning
description: "Prioritize Maru product work, collect requirements, review user journeys, or turn an accepted idea into a documented contract. Use for roadmap, UX, modular-adoption, and 'what next' discussions; do not use for a narrowly specified implementation whose behavior is already accepted."
---

# Maru Product Planning

Keep product decisions human-centered, evidence-backed, and compatible with a
convention adopting only the capability it currently trusts Maru to run.

## Select the mode

- **Collect only:** When the user says not to solve or investigate yet, append
  the input to a categorized, extensible todo list. Do not inspect code, choose
  a design, or edit files.
- **Analyze and prioritize:** Read current project truth, inspect the visible
  experience and relevant implementation, compare options, and recommend the
  smallest high-impact complete outcome.
- **Contract an accepted outcome:** Update the stable requirement first or with
  the page/module contract and ADR, then hand implementation to the owning
  module boundary.

Do not collapse these modes. A request to capture an idea is not permission to
implement it.

## Establish the decision frame

Read [the product vision](../../../docs/product/vision.md),
[requirements](../../../docs/product/requirements.md),
[current state](../../../docs/project/CURRENT.md),
[roadmap](../../../docs/project/ROADMAP.md), and the relevant page, module, and
architecture contracts. Inspect the current interface when the recommendation
depends on what a person can actually see or do.

Prioritize, in order of relevance:

1. a complete and understandable human journey rather than another isolated
   record;
2. safety, reliability, recovery, and honest failure behavior;
3. progressive modular adoption and coexistence with incumbent systems;
4. task-focused navigation, consistency, accessibility, and low interaction
   cost;
5. import, export, print, manual fallback, and integration boundaries that
   reduce adoption risk;
6. durable history and a credible path to the next capability.

Use evidence and dependencies to explain priority. Do not turn repository age,
code volume, or an attractive but disconnected screen into user impact.

## Apply progressive modular adoption

Read [the progressive-adoption reference](references/progressive-adoption.md)
when proposing a module, navigation model, account flow, integration, rollout,
or roadmap sequence. Apply NFR-013: one complete workflow must be able to stand
as the organization's only adopted Maru capability without creating records or
obligations in unrelated modules.

## Produce a decision-ready result

State the user or operator problem, affected roles, current evidence, proposed
outcome, why it ranks now, required foundations, explicit non-goals, risks, and
acceptance evidence. Offer alternatives only when they represent materially
different tradeoffs. If a decision is accepted, give it stable requirement
language before implementation begins.
