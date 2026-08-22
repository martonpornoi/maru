# ADR 0074: Newcomer-first curated Sphinx navigation

- Status: Accepted
- Date: 2026-08-22
- Refines: ADRs 0057, 0058, and 0072
- Complements: ADR 0073
- Requirements: UX-006, UX-007, NFR-001, NFR-002, NFR-003, and NFR-012

## Context

Maru's public contributor site successfully assembled maintained product,
architecture, development, operations, security, project, research, checkpoint,
and generated Python documentation. Its root used broad Sphinx globs, however,
so the homepage and global sidebar presented almost every source and many of
their headings at equal weight. Internal backlogs, historical checkpoints,
architecture decision records, and hundreds of generated API pages competed
with the first explanation of the product.

The result was complete but not approachable. A newcomer had no explicit route
for understanding Maru, judging its maturity, starting it locally, following a
representative workflow, or preparing a contribution. Search could locate a
known term but could not explain what deserved attention first. Restyling the
same exhaustive hierarchy would not correct that information architecture.

The underlying records remain valuable. ADRs preserve durable reasoning,
checkpoints preserve milestone evidence, project ledgers preserve current and
detailed status, and AutoAPI preserves source contracts. Removing them or
moving them to an unreviewed Wiki would weaken continuity and contradict ADR
0072. The site instead needs progressive disclosure: a small human front door
over complete, stable, searchable catalogs.

## Decision

### Keep exactly six primary destinations

The root toctree contains exactly these documents in this order:

1. **Start here** — `start-here/index`;
2. **Product** — `product/index`;
3. **Architecture & security** — `architecture/index`;
4. **Build & contribute** — `development/index`;
5. **Operate Maru** — `operations/index`; and
6. **Reference & history** — `reference/index`.

The root uses an explicit hidden toctree with a maximum depth of one. It does
not use `:glob:` and does not directly enumerate project records, page
contracts, module guides, research, ADRs, checkpoints, or AutoAPI children.
Changing the number, order, purpose, or document name of these primary hubs is
an information-architecture decision, not an incidental link edit.

### Give newcomers one bounded route

The homepage leads with Maru's purpose, an accurate under-active-development
statement, the synthetic-data boundary, and three goal-based choices:
understand Maru, run it locally, or contribute safely. It then offers one
five-step path:

1. what Maru is;
2. what works today;
3. how to run Maru locally;
4. one synthetic product tour; and
5. how to prepare a first contribution.

The five pages state their audience, intended outcome, and reading or activity
time. They link to deeper authoritative material instead of reproducing entire
requirements, setup guides, ledgers, or governance rules. Each step ends with a
clear next action, while the Start here hub explains where an evaluator,
explorer, contributor, or reference reader may stop or branch.

### Preserve complete material behind catalogs

Every maintained Markdown document remains reachable through nested toctrees
and keeps its existing URL unless a separately reviewed rename is necessary.
Bounded catalog pages may use local globs where the directory itself defines a
coherent archive, such as numbered ADRs or dated checkpoints. A glob may not be
used at the documentation root to turn the repository tree into the primary
navigation.

Product and page contracts sit behind Product. Architecture, security, domain,
and ADR material sit behind Architecture & security. Development and quality
standards sit behind Build & contribute. Operational tutorials and runbooks sit
behind Operate Maru. Modules, generated Python reference, project records,
research, and checkpoints sit behind Reference & history. Contextual links may
cross these catalogs when they answer a reader's current task.

ADRs and checkpoints are records, not sequential onboarding. AutoAPI has one
top-level catalog entry and does not expand every module at the root. The
maintained current-state and production-consolidation records govern present
implementation claims; a dated checkpoint or superseded ADR cannot silently
become current guidance because it is easier to find.

### Make discoverability and accessibility explicit

Hub and newcomer pages use descriptive task language and state audience,
outcome, and expected reading time. The visible page explains why and when to
open a catalog rather than printing a bare file inventory. Search remains a
secondary route for readers who already know a term.

Navigation and route cards use semantic headings and ordinary links. Essential
navigation does not depend on JavaScript, color, hover, an icon, or pointer
input. Custom presentation must reflow at narrow widths, retain visible
keyboard focus, and meet WCAG 2.2 AA contrast in Furo's light, dark, and
automatic themes. The initial card layout uses ordinary heading sections and
CSS Grid; it adds no theme extension or runtime dependency.

The repository documentation validator enforces the exact root hubs and order,
rejects root globs and direct archive placement, recursively follows explicit
and bounded-glob toctrees, and fails when a maintained Markdown source is
orphaned. Sphinx continues to build warning-fatally, so invalid references and
generated-reference failures remain acceptance failures.

### Use ethical fictional examples

ADR 0073 governs repository-owned examples throughout the new navigation.
Newcomer pages, tutorials, screenshots, and fixtures use MaruCon, MaruDance,
synthetic people, and reserved contact domains. They do not fetch or reproduce
another convention's roster, organization chart, people directory, or branding
as example data. Necessary factual attribution, software credit, standards,
security advisories, and purpose-governed research remain accurate and live in
their appropriate reference or research context rather than the newcomer path.

## Consequences

- A first-time reader sees six stable choices and one finite learning path
  instead of the repository inventory twice.
- Complete historical and generated evidence remains published, searchable,
  directly linkable, and warning-fatal without dominating the primary
  navigation.
- Adding a maintained Markdown page also requires placing it in one nested
  catalog. The validator turns forgotten discoverability into an immediate,
  deterministic failure.
- Root navigation becomes deliberately rigid. A seventh primary section or a
  reordered hub requires review of this decision and the executable contract.
- Readers use hub pages or search to enter deep archives. The global sidebar no
  longer attempts to display every available page at once.
- Furo, MyST, AutoAPI, and the protected Pages publication boundary remain
  unchanged. The change adds no package, JavaScript runtime, deployment
  authority, application route, data migration, or production-readiness claim.
- Audience and reading-time metadata are required for curated hubs and the
  newcomer path, not retroactively for every historical record. This preserves
  guidance quality without imposing ceremonial edits across the archive.

## Alternatives considered

### Restyle the exhaustive root hierarchy

Rejected because spacing, color, and cards cannot establish priority while
every backlog, ADR, checkpoint, module, and generated page remains a peer.

### Delete or stop publishing historical material

Rejected because ADRs, checkpoints, research, and project ledgers provide
continuity, decision provenance, and recovery evidence. Their placement was the
problem, not their existence.

### Use search as the only entry point

Rejected because search serves readers who know a term; it cannot teach product
scope, maturity, sequence, or the difference between current and historical
authority.

### Mirror selected guides into GitHub Wiki

Rejected consistently with ADR 0072 because a second editable source would
drift from reviewed Markdown and generated reference.

### Replace Sphinx and Furo or add a card extension

Rejected because the current toolchain already provides warning-fatal builds,
search, generated API reference, responsive theming, and semantic source. A
tool migration or another presentation dependency would add maintenance without
solving the information hierarchy more directly.

### Require audience and status metadata on every historical page

Rejected because bulk metadata would create review ceremony and stale labels
across append-only evidence. Curated hubs carry the routing contract; individual
current guides retain their existing status rules.
