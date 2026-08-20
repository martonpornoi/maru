# Maru contributor documentation

Maru is an API-first convention operations platform built as a Django and
PostgreSQL modular monolith. This site combines the maintained product and
engineering guides with a source-derived Python API reference.

```{toctree}
:caption: Project
:maxdepth: 2
:glob:

project/*
```

```{toctree}
:caption: Product and architecture
:maxdepth: 2
:glob:

product/*
product/page-contracts/*
architecture/*
architecture/decisions/*
domain/*
security/*
```

```{toctree}
:caption: Engineering
:maxdepth: 2
:glob:

development/*
quality/*
modules/*
operations/*
research/*
checkpoints/*
```

```{toctree}
:caption: Python API reference
:maxdepth: 3

autoapi/maru/index
```

The generated reference is contributor documentation. The authenticated
Swagger and ReDoc views remain the authoritative human presentations of the
checked-in OpenAPI contract for HTTP consumers.
