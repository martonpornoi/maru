# Documentation standards

Status: Baseline  
Last updated: 2026-09-05

Documentation is maintained with the implementation.

## Required document types

- **Product requirements:** Stable behavior and acceptance intent.
- **ADRs:** Durable technical and architectural decisions.
- **Module documentation:** Ownership, public contracts, data, permissions,
  events, failure modes, and operational considerations.
- **API documentation:** Generated OpenAPI plus human explanations and examples.
- **Runbooks:** Deployment, migration, backup, restore, reconciliation, incident,
  and external-integration procedures.
- **Role guides:** Task-oriented help for attendees, Front Desk, Registration,
  HR, department leads, programme staff, IT, and other operators.
- **Release notes:** User-visible behavior, breaking changes, migrations, and
  known limitations.
- **Checkpoints:** Concise current handoff and append-only milestone records.
- **Agent workflow support:** Always-on repository instructions plus focused,
  progressively disclosed playbooks for repeatable contributor work.

## Current handoff and historical detail

Keep `docs/project/CURRENT.md` a short restart guide, normally no more than
about 150 lines: current phase, latest completed product outcome, active scope,
verification provenance, open risks, and the smallest next actions. Replace
superseded status rather than stacking a new delivery diary above it. Remove
completed work from every next-action list, including `ROADMAP.md`.

Link detailed milestone evidence from the existing append-only checkpoints;
keep durable behavior in its owning requirement, module, ADR, or runbook.
Retain historical documents and their stable paths. Do not copy an entire old
handoff into a new archive when its evidence already has a checkpoint; Git
preserves the exact older handoff. For a new milestone, add only the new facts
and point to the existing evidence.

Distinguish implementation from local certification, hosted acceptance, and
production approval. Record exact tested revisions and link delivery evidence
without predicting a future merge. A historical test count is not the current
suite size. Do not put machine-specific Docker inventories or temporary branch
logs into the maintained product handoff.

Read the required current-state documents, then select requirements, module
contracts, and ADRs for the task. Search historical catalogs only when needed;
do not make every restart read every previously delivered module and runbook.

## Module README template

Each implemented module documents:

1. Purpose and requirements served
2. Owned data and invariants
3. Public commands, queries, and events
4. Permission and sensitivity model
5. Dependencies and consumers
6. User and operational workflows
7. Failure, retry, and reconciliation behavior
8. Retention and archival behavior
9. Tests and observability
10. Known limitations and future work

## Writing rules

- Prefer task and domain language over framework terminology.
- State what is authoritative and what is derived.
- Include examples with repository-owned fictional and synthetic data.
- Explain permission failures and sensitive boundaries.
- Date operational assumptions that depend on external providers.
- Link instead of duplicating normative content.
- Mark proposed behavior as proposed; do not describe it as implemented.
- Remove stale instructions in the same change that makes them stale.

### Purpose-first surface names

Living product, module, architecture, security, testing, setup, and operating
guidance names each management surface by the task a person is trying to
complete: for example, **Organization structure**, **Position management**, or
**Registration setup and account onboarding**. Sequential labels built from
the word "Page" plus an implementation number are history shorthand and must
not be used as current product vocabulary.

Numeric prefixes on established contract and runbook filenames may remain for
stable document order and incoming-link compatibility. They do not appear in
headings, link text, navigation labels, acceptance criteria, or current-state
prose. Accepted ADRs, append-only checkpoints, and the explicitly frozen rebuild
and production-consolidation ledgers retain their original wording as historical
evidence; current indexes and handoffs translate that history into purpose
names.

## Agent workflow documentation

Repository-root `AGENTS.md` owns always-on working, safety, reading-order, and
definition-of-done instructions. `.agents/skills/<name>/SKILL.md` owns one
focused reusable workflow whose frontmatter description says both when to use
it and when not to use it. Larger details belong in references linked directly
from that entrypoint so unrelated work does not load them.

A repository skill must:

- use a lowercase hyphenated directory and matching frontmatter name;
- stay procedural and link to current project, requirement, ADR, module, and
  operating truth instead of copying a status snapshot;
- include `agents/openai.yaml` with quoted display metadata and a default
  prompt that invokes the skill explicitly;
- expose every Markdown reference through `SKILL.md` and contain no unfinished
  scaffold placeholder or separate skill README; and
- preserve request authority: a playbook cannot authorize implementation,
  external mutation, merge, release, deployment, or production-data access.

The curated catalog is documented in the
[agent-assisted workflow guide](../development/agent-workflows.md). Changes to
the catalog require an intentional documentation-policy update and tests. Run
the deterministic gate with:

```powershell
uv run python scripts/validate_docs.py
```

Skills supplement human-readable project documentation; they never replace a
stable requirement, accepted ADR, role guide, runbook, current-state handoff,
checkpoint, code review, or acceptance evidence.

## Contributor site information architecture

ADR 0074 defines the public Sphinx navigation. The portal is a guided entry
point over complete maintained material, not a rendering of the repository tree.

### Primary navigation contract

`docs/index.md` contains one explicit, hidden, maximum-depth-one toctree with
exactly these hubs in this order:

| Rendered title | Document name | Reader outcome |
| --- | --- | --- |
| **Start here** | `start-here/index` | Follow the bounded newcomer route. |
| **Product** | `product/index` | Understand users, workflows, requirements, and page contracts. |
| **Architecture & security** | `architecture/index` | Find system, domain, authorization, privacy, resilience, and decision boundaries. |
| **Build & contribute** | `development/index` | Set up, verify, document, and contribute safely. |
| **Operate Maru** | `operations/index` | Select an exact tutorial, runbook, migration, recovery, or release procedure. |
| **Reference & history** | `reference/index` | Look up modules, generated Python APIs, project records, research, and checkpoints. |

The root toctree never uses `:glob:`. It does not directly enumerate backlogs,
page contracts, module files, research, ADRs, checkpoints, or AutoAPI children.
Those sources remain published behind their owning hubs rather than becoming a
second exhaustive listing on the homepage or global sidebar.

The visible homepage leads with Maru's purpose, accurate active-development and
synthetic-data boundaries, and goal-based routes to understand, run, or
contribute. A theme or visual redesign must preserve that priority before
adding presentation.

### Curated newcomer path

Only `docs/start-here/` is intended to be read in sequence. Its stable five
steps are:

1. `what-is-maru` — product purpose, users, and boundaries;
2. `current-maturity` — implemented, partial, proposed, historical, and
   deployment-gated status;
3. `run-locally` — disposable local setup and safe data boundary;
4. `product-tour` — one coherent synthetic convention journey; and
5. `first-contribution` — bounded work, local evidence, and protected review.

Every newcomer page and primary hub states its audience, intended outcome, and
expected reading or activity time. Newcomer steps link to deeper authorities
instead of copying complete requirements, setup guides, ledgers, or governance
rules, and each step gives a clear next action. Start here also tells an
evaluator, explorer, contributor, or reference reader where they may branch or
stop.

### Catalog and discoverability rules

- Every maintained Markdown source is reachable from `docs/index.md` through a
  nested toctree. Adding an orphan is a validation failure even if another page
  contains an inline link to it.
- A bounded catalog may use a local glob when its directory defines one coherent
  collection, such as numbered ADRs or dated checkpoints. Broad or cross-domain
  root globs are prohibited.
- ADRs and checkpoints remain append-only records, not onboarding sequences.
  Project plans and research remain reference material. AutoAPI appears as one
  catalog destination and does not expand every module at the root.
- Existing document URLs remain stable unless a separately reviewed rename is
  necessary. Moving a page behind a catalog changes priority, not availability.
- Hub copy uses task and outcome language rather than exposing filenames or
  database models as the reader's primary mental model. Link text explains why
  a reader should follow it.
- Contextual cross-links are encouraged when they answer the current task.
  Search supports readers who know a term but does not replace curated routes,
  maturity guidance, or authoritative-source labels.
- Current implementation claims come from the maintained project state and
  production-consolidation ledger. A dated checkpoint, research note, legacy
  scenario, or superseded ADR must not be presented as current merely because
  it remains searchable.

`scripts/validate_docs.py` enforces the exact root order, rejects root globs and
direct archive placement, recursively follows explicit and bounded-glob
toctrees, and reports unreachable Markdown. The warning-fatal Sphinx build
continues to enforce valid source and generated references.

### Accessibility and presentation

- Navigation uses semantic headings, descriptive ordinary links, and logical
  source order. An icon, color, position, hover state, or reading-time estimate
  is never the only way to understand or activate a route.
- Essential navigation works without JavaScript and with keyboard or assistive
  technology. Custom cards remain ordinary headings and links in the document
  tree and retain visible focus.
- Custom layout reflows without page-level horizontal scrolling at 320 CSS
  pixels and at 200 percent zoom. Tables and code blocks may use clearly bounded
  local scrolling when their content requires it.
- Link, focus, text, border, and state colors meet WCAG 2.2 AA contrast in
  Furo's light, dark, and automatic themes. A light-theme override must not
  silently replace Furo's accessible dark-theme variables.
- New presentation dependencies require a demonstrated information or
  accessibility benefit. The baseline route cards use ordinary semantic
  heading sections and CSS Grid; they do not require a JavaScript widget or
  another Sphinx extension.

### Ethical fictional examples

ADR 0073 governs current repository-owned examples:

- Named example conventions use **MaruCon** or **MaruDance** and never imply a
  customer, partner, endorsement, or globally cleared commercial mark.
- People, organizations, contact details, screenshots, fixtures, tutorials,
  and generated examples are synthetic. Contacts use RFC-reserved domains such
  as `.invalid`; production personal data is prohibited.
- Current examples do not fetch, parse, snapshot, reproduce, or rename another
  convention's roster, people directory, organization chart, people-to-role
  mapping, or branding.
- Necessary factual attribution for software, standards, dependencies,
  licenses, security advisories, and purpose-governed research remains accurate.
  Such material belongs in its reference, license, ADR, or research context and
  does not become tutorial or fixture data.
- Partner-specific research or migration requires an explicit purpose,
  authority, provenance, minimization, correction, access, retention, and
  removal contract before repository or deployment data is collected.

## API documentation

OpenAPI is generated and checked in CI. Every public operation has:

- a stable operation identifier;
- purpose and audience;
- authentication and required capabilities;
- organization and edition scoping;
- request, response, and error schemas;
- idempotency and pagination behavior where relevant;
- examples without personal data;
- deprecation information.

## Python reference documentation

Public production Python under `src/` and repository tooling under `scripts/`
use NumPy-style docstrings. Ruff's `D` rules enforce presence, placement, and
summary form with `pydocstyle.convention = "numpy"`. PyDocLint validates public
and private callable sections against their signatures. Python annotations
remain the implementation and static-analysis authority; NumPy declarations
mirror their types and defaults so the generated Sphinx reference is complete
without requiring readers to inspect source signatures.

### Enforced public contract

- Every input appears in `Parameters`, in signature order, with the signature
  type and default where applicable. Forwarded `*args` and `**kwargs` retain
  their stars and explain which framework implementation receives them.
- Every meaningful return or stream has `Returns` or `Yields`. A procedure that
  returns nothing does not add a ceremonial return section. Documented return
  and yield types must agree with the signature.
- A class explains its role and public attributes; explicit constructor inputs
  are documented on `__init__`, beside the signature that PyDocLint validates.
  Public dataclasses document every public field in `Attributes`.
- Every named exception raised directly by a callable appears exactly in
  `Raises`.
  Additional stable exceptions propagated from a documented boundary may also
  be listed when callers are expected to handle them.
- A callable containing an assertion documents `AssertionError` when that
  assertion is part of its contract.
- Summaries state domain intent. The semantic quality gate rejects generated
  prefixes such as `Handle`, `Represent`, and `Compute`, placeholder value or
  result prose, and other repository-known boilerplate patterns.

The description of an input states its meaning, scope, accepted form, or
constraint. The description of a result states what is authoritative,
filtered, ordered, persisted, or safe to disclose. Public domain commands,
queries, services, adapters, views, and models must not merely expand their
Python name.

### Context sections

Use the remaining NumPy sections when they make a durable contract clearer:

- `Notes` explains fail-closed behavior, transaction and locking boundaries,
  idempotency, canonicalization, scope ownership, or a non-obvious design
  choice.
- `Warnings` identifies sensitive material, irreversible behavior, or a safety
  condition a caller could otherwise miss.
- `Examples` is expected for deterministic parsers, normalizers, predicates,
  value objects, and other isolated APIs when a short synthetic example is more
  precise than prose. Examples should be copyable, contain no personal data,
  and avoid database ceremony that obscures the contract.
- `See Also` links genuinely related public contracts without duplicating their
  documentation.

A concise summary is still sufficient for an obvious zero-input framework hook
with no meaningful result, direct exception, or public attributes. Private
implementation details may remain undocumented only when Ruff's presence rules
permit it; once documented, private callable sections receive the same
signature checks as public contracts.

Tests are exempt from docstring-presence rules because descriptive test names
are their executable documentation. Generated Django migrations are also
excluded. PyDocLint's exact direct-`raise` matcher is enabled. Its known bare
re-raise limitation receives a definition-scoped `DOC503` only where audit or
cleanup deliberately preserves the caught exception; every suppression states
that reason inline. Maru's semantic validator independently requires every
directly named exception while permitting additional stable caller-facing
failures.

PyDocLint's general class-attribute inference remains disabled because it
misclassifies Django declarative configuration and reports valid dataclass
fields inconsistently. The repository AST gate enforces public dataclass
`Attributes` instead. PyDocLint also does not require `Returns: None` on every
procedure or duplicate property methods as class attributes; those settings
would add ceremony rather than contract information.

Ruff selects its complete rule catalog. The only global exemptions are
`ANN401`, `C901`, `COM812`, `EM101`, `EM102`, `ISC001`, `PLR0913`, and `TRY003`:
dynamic framework boundaries, separately reviewed complexity refactors,
formatter compatibility, and exception-message locality. Tests have scoped
annotation, docstring, and private-access exclusions. Production `SLF001`
exclusions are limited to named framework adapters and readiness inspectors;
new occurrences must not widen the global policy. ADR 0059 records the full
rationale.

Sphinx builds the contributor portal from all maintained Markdown documents and
a statically analysed AutoAPI reference. Napoleon interprets NumPy sections,
MyST parses Markdown, Mermaid renders diagrams, and Furo provides the HTML
theme. The source reference is distinct from the private Swagger/ReDoc HTTP
contract described in ADR 0056.

`docs/conf.py` reads the one project version from `pyproject.toml` and uses it
for the Sphinx version, release, HTML title, and active-development notice. Do
not copy that value into documentation configuration. A Pages build supplies
its canonical base URL at publication time; a local build deliberately remains
independent of the public deployment address.

Run the documentation gates with:

```powershell
uv run pydoclint src scripts
uv run python scripts/validate_python_docstrings.py src scripts
uv run sphinx-build -W --keep-going --fresh-env -j auto -d docs/_build/doctrees -b html docs docs/_build/html
```

The semantic validator reports stable `PDQ` codes for boilerplate summaries,
contract-shaped placeholder descriptions, missing direct exceptions, and
undocumented public dataclass attributes. The Sphinx build treats every warning
as an error.
Generated files under `docs/_build/` and intermediate AutoAPI pages are build
products and are not committed. Ruff emits LF line endings so generated and
reviewed Python diffs are stable across contributor platforms.

ADR 0072 defines public publication. Pull requests validate and retain the HTML
artifact but cannot deploy. After merge, a dedicated workflow rebuilds from
protected `main` with locked dependencies, checks current remote `main`
immediately before build and deployment, uses fresh temporary HTML and doctree
directories, and uploads only the generated HTML root. The write/OIDC token
exists only in the separate `github-pages` deployment job. Mermaid and D3 use
the exact external versions recorded in `docs/conf.py` and the generated-asset
license record; unused ELK support is disabled. Wiki remains disabled rather
than mirroring maintained source. A public static contributor site does not
change the authenticated OpenAPI authority or establish application deployment,
release, support, or production-data approval.

## User documentation

Role guides are organized around questions and outcomes, not database models.
Common workflows include screenshots or short recordings when the UI exists.
Terminology must match the interface.

## Documentation review

Every material task reviews:

- `docs/project/CURRENT.md`;
- affected requirements;
- relevant ADRs;
- module and API documentation;
- operations and role guides;
- checkpoint need.
