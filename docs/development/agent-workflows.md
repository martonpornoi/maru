# Agent-assisted workflows

**Audience:** Contributors and maintainers working with Codex or another
compatible coding agent\
**Outcome:** Select the smallest useful Maru playbook without weakening current
project truth, review, or authority boundaries\
**Reading time:** 6 minutes

Maru uses a layered support model. Repository instructions establish invariant
working rules; focused skills provide repeatable procedures only when a task
matches; maintained product and engineering documents remain the source of
truth. This keeps routine work fast without forcing every task to load the
entire project's operational history.

## Support layers

| Layer | Purpose | Authority |
| --- | --- | --- |
| Root `AGENTS.md` | Always-on reading order, safety, modularity, security, and definition of done | Applies to every material task |
| `.agents/skills/<name>/SKILL.md` | Focused procedure selected explicitly or from its description | Supplements but never overrides repository or user instructions |
| `references/` inside a skill | Detail needed only for a particular branch of that procedure | Loaded only when routed from `SKILL.md` |
| `agents/openai.yaml` | Human-readable display name, short description, and invocation prompt | Presentation metadata, not project policy |
| Requirements, ADRs, modules, runbooks, `CURRENT.md`, and checkpoints | Product intent, durable decisions, current truth, and evidence | Authoritative for Maru behavior and status |
| Tests, local certification, and hosted `PR gate` | Executable feedback and protected merge acceptance | Evidence for the exact code and commit tested |

Codex discovers repository skills from `.agents/skills/`. A contributor may
invoke one explicitly with its `$skill-name`; otherwise its frontmatter
description is the routing contract. The upstream format and discovery rules
are described in OpenAI's
[Build skills documentation](https://developers.openai.com/codex/skills).

## Curated Maru skill catalog

| Skill | Use it for | Do not use it for |
| --- | --- | --- |
| `$maru-change-map` | Material implementation, diagnosis, or review crossing a product or technical contract | Trivial formatting or a self-contained factual answer |
| `$maru-product-planning` | Requirement collection, journey review, prioritization, roadmap work, or progressive modular adoption | A narrow implementation whose behavior is already accepted |
| `$maru-browser-rehearsal` | Visible role, state, responsive, keyboard, accessibility, and disclosure acceptance | API-only testing or styling without a human journey |
| `$maru-pr-delivery` | Pull-request preparation, hosted-check repair, exact merge verification, and main synchronization | Ordinary local implementation or an unrequested merge |

Use the smallest matching set. A product decision that later becomes code may
use product planning first and change mapping second; a visible acceptance pass
may add browser rehearsal; delivery applies only when the work reaches a pull
request. A skill should not be invoked merely because it exists.

## Expected working sequence

1. Read `AGENTS.md`, `CURRENT.md`, `ROADMAP.md`, the relevant requirements and
   module documentation, the ADR index and related decisions, then inspect code
   and tests.
2. Classify what the user asked for: answer, collect, diagnose, change, review,
   rehearse, deliver, or monitor. Preserve that authority boundary.
3. Select only the matching skill and follow its complete entrypoint. Load a
   linked reference only when its branch applies.
4. Work through the owning module and canonical contract. Keep temporary
   reasoning in working notes rather than creating an unrequested planning
   artifact.
5. Verify in proportion to risk, update affected human documentation, keep
   `CURRENT.md` concise, and add a checkpoint when the outcome is a milestone.
6. Report focused local evidence, hosted acceptance, deployment evidence, and
   production approval as distinct facts.

## Authority and privacy boundaries

For handoff maintenance, follow the
[current-state and history boundary](../quality/documentation-standards.md#current-handoff-and-historical-detail).
Keep one current priority list, reconcile completed work against delivery
evidence, and link existing checkpoints instead of accumulating delivery logs
in `CURRENT.md`. The required reading order still applies; it does not require
loading every historical module, runbook, or checkpoint for an unrelated task.

A skill never grants permission to edit when the request asks only for an
answer or diagnosis. It also cannot authorize a push, merge, repository-setting
change, release, deployment, external message, destructive operation, or
production-data access. Those actions still require the user's request and the
repository's normal controls.

Do not put secrets, credentials, private data, personal memories, transient
branch status, or copied conversation history in a skill. Use synthetic data
for examples. Current project state belongs in `CURRENT.md`; historical detail
belongs in append-only checkpoints; durable behavior and decisions belong in
requirements, contracts, and ADRs.

## Maintaining the catalog

Keep each skill narrow enough that its description can route unambiguously.
Prefer a short entrypoint and linked references over one catch-all playbook.
Adding, renaming, or removing a skill is a reviewed repository-policy change:
update this guide, `AGENTS.md`, the documentation validator's curated catalog,
tests, and an ADR when the working contract changes durably.

Validate an edited catalog with:

```powershell
uv run python scripts/validate_docs.py
uv run pytest tests/unit/test_documentation_policy.py tests/unit/test_ci_changes.py
```

The documentation gate checks the exact catalog, frontmatter identity,
discoverability metadata, linked progressive-disclosure references, unfinished
placeholders, and normal Markdown links. Changes under `.agents/` also route to
documentation acceptance, and deleting a repository skill is treated as a
protected deletion requiring explicit review.
