# Maru contributor documentation

Maru is an API-first platform for running recurring community conventions. The
project combines one coherent participant experience with task-oriented tools
for organizers, volunteers, and operators.

**Current maturity:** Maru is under active development. It is not a supported
hosted service, a production-ready release, or approved for production personal
data. Use synthetic data for development and evaluation. The
[current maturity guide](start-here/current-maturity.md) explains what evidence
is available and how to distinguish implemented behavior from plans.

## Choose what you want to do

### Understand Maru

Learn the product promise, current boundaries, and architecture without reading
the repository history first.

[Start the guided introduction](start-here/index.md) **45–60 minutes**

### Run Maru locally

Prepare a disposable local environment, start the application, and use only
synthetic demonstration data.

[Open the local route](start-here/run-locally.md) **15–30 minutes**

### Contribute safely

Understand the branch, verification, documentation, and review expectations
before making a focused change.

[Prepare a first contribution](start-here/first-contribution.md) **10 minutes**

## Recommended first journey

You do not need to read this site page by page. Follow these five steps, then
use the six navigation sections as catalogs when a task needs more detail.

| Step | Outcome | Reading time |
| --- | --- | ---: |
| [1. What is Maru?](start-here/what-is-maru.md) | Understand the problem, intended users, and product boundaries. | 5 min |
| [2. What works today?](start-here/current-maturity.md) | Interpret implemented, partial, proposed, and historical material correctly. | 7 min |
| [3. Run Maru locally](start-here/run-locally.md) | Start a disposable environment and find the management surface. | 4 min plus setup |
| [4. Follow a product tour](start-here/product-tour.md) | See one synthetic organization-to-edition journey. | 10 min plus exercise |
| [5. Make a first contribution](start-here/first-contribution.md) | Choose a bounded change and take it through Maru's protected workflow. | 10 min |

## Find detailed material

- [Product](product/index.md) explains who Maru serves, its workflows,
  requirements, and interface contracts.
- [Architecture & security](architecture/index.md) explains system boundaries,
  authorization, data protection, resilience, and accepted decisions.
- [Build & contribute](development/index.md) covers setup, local verification,
  repository governance, testing, and documentation standards.
- [Operate Maru](operations/index.md) contains runbooks for deployment,
  recovery, releases, workers, and supported operational journeys.
- [Reference & history](reference/index.md) contains module and Python API
  reference, project ledgers, research, and append-only checkpoints.

The generated Python reference is contributor documentation. Authenticated
Swagger and ReDoc remain the human presentations of Maru's authoritative
OpenAPI contract for HTTP consumers.

```{toctree}
:hidden:
:maxdepth: 1

start-here/index
product/index
architecture/index
development/index
operations/index
reference/index
```
