# ADR 0079: Keep contributor playbooks focused and repository-scoped

- Status: Accepted
- Date: 2026-08-26
- Extends: ADRs 0037, 0059, 0066, and 0074
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011, and NFR-013

## Context

Maru's modular-monolith, tenant, authorization, audit, migration, recovery,
documentation, browser-acceptance, and protected-delivery contracts make a
material change intentionally rigorous. Root `AGENTS.md` establishes the
required reading order and invariant working boundaries, but repeating every
specialized procedure there would make those always-on instructions too long
and less useful.

The project also cannot depend on one contributor's private prompts, personal
skills, conversation history, or agent memory. Those inputs are not shared,
reviewed, versioned, or reliably current. Copying current branch state into an
agent playbook would create another handoff file that can disagree with
`CURRENT.md`. One catch-all skill would load unrelated product, database,
browser, and delivery detail into every task and make ambiguous selection more
likely.

The repository needs a small support layer that helps agents and humans find
the right procedure while preserving Maru's existing sources of truth,
authority boundaries, review, and executable acceptance.

## Decision

### Separate always-on policy from selected procedure

Root `AGENTS.md` remains the always-on repository contract. It owns required
reading, checkpoints, decision discipline, modularity, security and data rules,
and the definition of done. Focused skills live under
`.agents/skills/<name>/SKILL.md` and supplement that contract only when their
frontmatter description matches the task or a contributor invokes them
explicitly.

The initial curated catalog has four non-overlapping responsibilities:

- `maru-change-map` maps a material implementation, diagnosis, or review to
  requirements, ADRs, module ownership, trust boundaries, tests, and affected
  documentation;
- `maru-product-planning` separates collect-only, analysis, and accepted-
  contract modes while prioritizing complete human journeys and progressive
  modular adoption;
- `maru-browser-rehearsal` exercises visible role, state, responsive,
  accessibility, keyboard, and disclosure behavior without overstating the
  evidence; and
- `maru-pr-delivery` preserves the exact protected branch, pull-request,
  hosted-check, merge-verification, and fast-forward synchronization flow.

Each entrypoint stays short and routes optional detail through directly linked
Markdown references. `agents/openai.yaml` provides quoted interface metadata
and an explicit default invocation prompt. Skills do not use separate README
files or retain unfinished scaffold text.

### Keep project truth and authority outside skills

Skills contain reusable procedure, not a snapshot of current implementation,
test counts, branch status, credentials, private data, or personal memory. They
link to current requirements, ADRs, module documentation, runbooks,
`CURRENT.md`, and checkpoints. Those maintained documents remain authoritative.

A selected skill does not broaden the user's request. It cannot turn an answer
or diagnosis into authorization to edit, or authorize a push, merge,
repository-setting change, release, deployment, destructive operation,
external message, or production-data access. Passing skill validation is not
code review, runtime correctness, hosted merge acceptance, deployment
evidence, or production approval.

### Make the catalog deterministic and reviewable

The documentation policy validates the exact curated skill catalog, matching
lowercase-hyphenated names, required frontmatter descriptions, quoted display
metadata, explicit default prompts, routed references, placeholders, and
ordinary Markdown links. Unit tests exercise valid packages and representative
catalog drift.

Changes under `.agents/` route to documentation acceptance. Deleting a skill is
a protected deletion under the repository's destructive-change review policy.
The public contributor guide explains selection, authority, privacy,
maintenance, and validation in human terms. Adding, renaming, or removing a
skill therefore requires an intentional policy, test, and guide change instead
of silently changing agent behavior.

### Operationalize progressive modular adoption

NFR-013 and the product vision are the stable authority for progressive modular
adoption. The product-planning skill links to a reusable adoption-profile
reference covering foundations, visible destinations, records and side
effects, purpose-specific identity, incumbent-system coexistence, imports,
exports, print and manual fallback, recovery, and expansion or removal. The
skill does not replace those product contracts; it makes them difficult to
forget during roadmap and navigation decisions.

## Consequences

- Contributors get consistent change mapping, product framing, visible journey
  acceptance, and protected delivery without loading every procedure into every
  task.
- Shared repository behavior can be reviewed, tested, versioned, and improved
  alongside the code rather than hidden in personal configuration.
- Human-readable guidance and deterministic checks reduce drift between what a
  skill claims and what Codex can discover.
- The catalog has a maintenance cost. Procedures must link to current truth,
  descriptions must remain distinct, and format changes in the upstream skill
  interface may require an intentional compatibility update.
- Skills improve discipline and speed but cannot guarantee judgment, complete
  context, or correctness; focused tests, review, hosted acceptance, and human
  product authority remain necessary.

## Alternatives considered

- **Put every procedure in `AGENTS.md`:** rejected because optional database,
  UX, product, and delivery detail would burden every task and weaken the
  always-on signal.
- **Create one comprehensive Maru skill:** rejected because its trigger would
  overlap almost every request and progressive disclosure would begin too late.
- **Keep skills in one maintainer's personal Codex directory:** rejected
  because collaborators and hosted work would not share or review them.
- **Rely only on documentation search and CI:** rejected because those remain
  essential authorities and gates but do not provide task-sensitive procedure
  routing before work begins.
- **Copy current status into each skill:** rejected because `CURRENT.md` and
  append-only checkpoints already own that information and can be kept
  coherent.

## Requirements affected

- **NFR-001:** Repeatable playbooks and focused checks improve testing
  selection without weakening authoritative acceptance.
- **NFR-002:** Skills route contributors to living documentation and are
  validated as maintained documentation themselves.
- **NFR-003:** Change mapping and browser rehearsal preserve the current-state
  and checkpoint handoff discipline.
- **NFR-011:** Skill changes participate in protected documentation routing and
  destructive-deletion review.
- **NFR-013:** Product planning consistently evaluates complete standalone
  workflows and the absence of side effects in unadopted modules.
