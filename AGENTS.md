# Working on Maru

These instructions keep the project understandable across long development
cycles and agent or maintainer handoffs.

## Required reading order

At the start of every material task:

1. Read `docs/project/CURRENT.md`.
2. Read `docs/project/ROADMAP.md`.
3. Read the relevant product requirements and module documentation.
4. Read the ADR index and any ADRs related to the change.
5. Inspect the current code and tests before proposing implementation.

Do not infer current state from conversation history when the repository
contains a newer checkpoint.

## Required end-of-task checkpoint

Before declaring a material task complete:

1. Run the checks appropriate to the changed area.
2. Update `docs/project/CURRENT.md` with:
   - the current phase and last completed outcome;
   - decisions made or ADRs added;
   - verification performed and its result;
   - known risks, blockers, and incomplete work;
   - the smallest sensible next actions.
3. Add an append-only file under `docs/checkpoints/` for milestones, releases,
   migrations, major architecture changes, and externally visible features.
4. Update affected product, architecture, API, operations, and user
   documentation in the same change.

`CURRENT.md` is a concise handoff, not a diary. Checkpoint files preserve
historical detail.

## Decision discipline

- Record durable architecture decisions as ADRs in
  `docs/architecture/decisions/`.
- Do not silently reverse an accepted ADR. Supersede it with a new ADR.
- Product behavior must map to a stable requirement identifier in
  `docs/product/requirements.md`.
- If implementation reveals that a requirement is ambiguous, update the
  requirement before or with the implementation.

## Modularity rules

- Keep the application as a modular monolith until an accepted ADR says
  otherwise.
- Each Django module owns its models and migrations.
- Other modules use documented commands, queries, or domain events; they do not
  import another module's private implementation.
- Shared code must be genuinely domain-neutral. Do not create a dumping-ground
  `utils` package.
- Cross-module writes belong in explicit application services and transactions.
- External integrations use adapters and never become the source of truth.

## Security and data rules

- Deny access by default.
- Scope every tenant-owned query by organization and, where relevant, event
  edition.
- Test object-level and field-level authorization.
- Separate platform identity from organizer-specific records.
- Never use production personal data in tests, examples, or fixtures.
- Audit sensitive administrative reads and all privileged mutations.
- Do not add user activity collection without a documented purpose, retention
  rule, visibility rule, and lawful basis.

## Definition of done

A change is not complete unless:

- behavior is tested at the appropriate levels;
- permissions and tenant isolation are tested;
- migrations and rollback or recovery implications are reviewed;
- relevant documentation is updated;
- observability and failure behavior are considered;
- `docs/project/CURRENT.md` accurately describes the resulting state.
