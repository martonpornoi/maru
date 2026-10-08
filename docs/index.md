# Maru contributor documentation

Maru is open-source operations software being built primarily for furry
conventions. It connects volunteer coordination, programme work, and organizer
tasks across recurring editions, with the aim of letting a convention adopt
one complete workflow at a time. Other community conventions can use the same
foundations.

**Current maturity:** Maru is under active development. It is not a supported
hosted service, a production-ready release, or approved for production personal
data. Use synthetic data for development and evaluation. The
[current maturity guide](start-here/current-maturity.md) explains which workflows
you can explore and which acceptance gates remain separate.

## Choose what you want to do

### Understand Maru

Learn the product purpose and current boundaries without reading the repository
history first.

[Start the guided introduction](start-here/index.md) **10 minutes to orient yourself**

### Run Maru locally

Start PostgreSQL and Django, create your own synthetic administrator, and sign
in to an empty development environment.

[Open the local route](start-here/run-locally.md) **15–30 minutes**

### Contribute safely

Choose a small improvement and get useful feedback before the complete
pre-review checks. Documentation contributions do not need a running database.

[Prepare a first contribution](start-here/first-contribution.md) **5 minutes**

## Recommended first journey

Follow these five steps if you want a guided tour. You can also go directly to
the page relevant to your task; the six navigation sections are catalogs for
later reference.

| Step | Outcome | Reading time |
| --- | --- | ---: |
| [1. What is Maru?](start-here/what-is-maru.md) | Understand the problem, intended users, and product boundaries. | 5 min |
| [2. What works today?](start-here/current-maturity.md) | Choose an exploration path and interpret its evidence. | 5 min |
| [3. Run Maru locally](start-here/run-locally.md) | Start a disposable environment and sign in. | 5 min plus setup |
| [4. Follow a product tour](start-here/product-tour.md) | See one synthetic organization-to-edition journey. | 5 min plus exercise |
| [5. Make a first contribution](start-here/first-contribution.md) | Choose a bounded change and prepare it for review. | 5 min |

## Find detailed material

- [Product](product/index.md) explains who Maru serves, its workflows,
  requirements, and interface contracts.
- [Architecture & security](architecture/index.md) explains system boundaries,
  authorization, data protection, resilience, and accepted decisions.
- [Build & contribute](development/index.md) covers setup, local verification,
  repository governance, testing, and documentation standards.
- [Operate Maru](operations/index.md) contains runbooks for deployment,
  recovery, releases, workers, and controlled operational rehearsals.
- [Reference & history](reference/index.md) contains module and Python API
  reference, project ledgers, research, and append-only checkpoints.

The generated Python reference is contributor documentation. Authenticated
Swagger and ReDoc present the authoritative OpenAPI contract for HTTP consumers.

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
