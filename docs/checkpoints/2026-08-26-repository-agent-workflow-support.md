# Repository-scoped agent workflow support

- Date: 2026-08-26
- Outcome: Added a focused, validated, human-documented contributor support
  layer and made progressive modular adoption a durable product boundary
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011, and NFR-013
- Decision: ADR 0079

## Baseline synchronization

PR #18 was verified merged before this work began. Local `main` and
`origin/main` were fast-forwarded and matched exact protected-main squash commit
`c4e04fec2c7a3ffb51fe059af3e6e884ec8d2b17` with a clean worktree. The support
work then began on `codex/maru-agent-support`; it does not amend the merged
Workforce Shift branch.

GitHub Actions run `32897740582` passed the full hosted acceptance path for PR
#18, including all eight PostgreSQL shards, combined coverage, and the stable
`PR gate`. That evidence belongs to the merged Shift commit and is not claimed
as hosted acceptance of this support branch.

## Delivered support model

Root `AGENTS.md` remains the concise always-on project contract and now routes
four focused repository skills:

- `maru-change-map` for bounded requirement, ADR, ownership, trust, test, and
  documentation mapping;
- `maru-product-planning` for collect-only, analysis, prioritization, accepted
  contracting, and progressive modular adoption;
- `maru-browser-rehearsal` for visible role, state, responsive, keyboard,
  accessibility, and disclosure evidence; and
- `maru-pr-delivery` for exact pull-request preparation, hosted-check repair,
  merge verification, and protected-main synchronization.

Each `.agents/skills/<name>/SKILL.md` has a narrow positive and negative routing
description. Optional detail is progressively disclosed through linked
references, while `agents/openai.yaml` provides the display name, short
description, and explicit default invocation prompt. No skill copies transient
project status or grants authority beyond the user's request.

The [agent-assisted workflow guide](../development/agent-workflows.md) explains
the support layers, current catalog, working sequence, authority and privacy
boundaries, maintenance obligations, and validation commands to human
contributors. Setup, contribution, documentation-standard, and Sphinx hub
guidance link to the same contract.

## Product continuity

NFR-013 now requires progressive modular adoption. An organization may use one
complete Maru workflow without enabling Registration, payments, attendance, or
unrelated modules. Adoption profiles must identify foundations, visible
destinations, purpose-specific relationships, records and side effects,
coexistence, imports, exports, print and manual fallback, and expansion or
removal behavior.

The product vision and roadmap apply this rule to Workforce-only, Programme and
event submissions, Communications publishing, Charity art auction, and
Registration without payments. These are intended adoption profiles, not a
claim that zero-configuration activation or safe production cutover already
exists. The product-planning skill routes contributors back to this stable
contract rather than becoming another source of product truth.

## Validation and acceptance routing

`scripts/validate_docs.py` now validates the exact curated catalog, directory
and frontmatter identity, concise discovery descriptions, quoted interface
metadata, explicit default prompts, reachable references, unfinished scaffold
markers, and normal Markdown links. Its unit tests cover a valid catalog plus
wrong names, orphaned references, and prompts that omit explicit invocation.

`.agents/` changes are classified as documentation changes. Deleting a skill
is protected deletion scope, so catalog removal requires the same explicit
destructive-change review as other critical repository policy. The existing
documentation and full hosted gates consume these classifiers; no parallel
acceptance workflow was added.

## Verification

Completed locally while implementing the support layer:

- the upstream skill-creator quick validator accepts all four skill packages;
- the documentation-policy and change-classifier suites pass all 68 focused
  tests;
- documentation policy passes across 343 Markdown files, four repository
  skills, and 205 unique requirement identifiers;
- whole-tree Ruff lint and formatting pass;
- strict mypy reports no issues across 369 source files;
- full PyDocLint passes and the semantic Python-docstring validator passes 379
  source files;
- warning-fatal Sphinx/AutoAPI builds the complete contributor portal; and
- `git diff --check` passes.

Hosted acceptance remains required for the exact eventual pull-request head.

## Runtime, migration, and deployment impact

This outcome changes contributor instructions, product intent, documentation
policy, tests, and CI change classification only. It adds no Django model,
migration, API, browser route, database permission, runtime setting, generated
client, external integration, deployment, or production-data approval.

## Known limitations and next actions

- Skill selection improves routing but cannot guarantee complete context,
  judgment, review quality, or runtime correctness.
- Upstream skill-format changes may require an intentional compatibility
  update; repository validation catches Maru's accepted current shape, not every
  future client behavior.
- NFR-013 is accepted intent. The first concrete next outcome is a
  **Workforce-only** adoption profile and rehearsal proving that unrelated
  Registration, payment, and attendance state remains absent.
- Browser, owner, recovery, privacy, load, deployment, and production-readiness
  gates from the Shift journey remain unchanged.
