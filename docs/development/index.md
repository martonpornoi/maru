# Build & contribute

**Audience:** Code, test, documentation, and design contributors\
**Outcome:** Prepare a development environment and follow Maru's quality and
collaboration contracts\
**Reading time:** 3 minutes to choose a guide

## Begin

- [Development setup](setup.md) installs locked dependencies, starts local
  PostgreSQL, and explains the application and generated references.
- [First contribution](../start-here/first-contribution.md) is the short
  newcomer route.
- [Repository governance](repository-governance.md) defines branches, pull
  requests, protected acceptance, dependency policy, and release authority.
- [Agent-assisted workflows](agent-workflows.md) explain Maru's always-on
  instructions, focused repository skills, and their authority boundaries.

## API contract review

- [Dated API inventory](api-contract-inventory.md) maps the declared operations
  to source adapters and separates documentation gaps from runtime evidence.
- [Catalog edition API review](catalog-edition-api-contract-review.md) traces
  exactly two operations and records the remaining conformance decisions.

## Verify

- [Testing strategy](../quality/testing-strategy.md) explains layers, database
  isolation, coverage, authorization, and failure evidence.
- [Local certification](local-certification.md) produces the complete
  pre-review exact-commit evidence.
- [Local Docker housekeeping](docker-housekeeping.md) distinguishes disposable
  test resources from persistent and unrelated data before approved cleanup.
- [Documentation standards](../quality/documentation-standards.md) define
  maintained prose, NumPy docstrings, generated reference, and review duties.

Use the [module catalog](../modules/index.md) to find ownership and public
contracts before changing production code. Durable boundary changes also need
a new [architecture decision](../architecture/decisions/index.md).

```{toctree}
:hidden:
:maxdepth: 1

setup
agent-workflows
api-contract-inventory
catalog-edition-api-contract-review
repository-governance
local-certification
docker-housekeeping
../quality/testing-strategy
../quality/documentation-standards
```
