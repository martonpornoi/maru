# Architecture decision record catalog

**Audience:** Contributors and maintainers investigating why a durable choice
was made\
**Outcome:** Locate a decision without treating the ADR archive as a reading
list\
**Reading time:** 2 minutes plus the selected record

Use the [ADR status index](README.md) to find decisions by number and current
status. Search this catalog by a domain term, requirement identifier, or file
boundary. Accepted ADRs are historical records: a later change supersedes one
with a new ADR rather than rewriting the original decision. ADR 0073 records a
one-time terminology sanitation of current rendered prose; the original public
evidence remains in Git history and that exception is not a general rewrite
policy.

For present implementation status, use the
[current project state](../../project/CURRENT.md) and
[production-consolidation ledger](../../project/PRODUCTION_CONSOLIDATION.md).

## Current documentation decisions

| ADR | Status | Decision |
| --- | --- | --- |
| [0072](0072-protected-exact-main-sphinx-pages-publication.md) | Accepted | Publish warning-fatal Sphinx output from protected `main` through a least-privilege Pages boundary. |
| [0073](0073-repository-owned-fictional-convention-examples.md) | Accepted | Keep current examples in Maru's fictional namespace and prohibit real convention rosters or copied organization charts as example data. |
| [0074](0074-newcomer-first-curated-sphinx-navigation.md) | Accepted | Present exactly six primary hubs, one five-step newcomer route, and complete maintained material behind reachable catalogs. |
| [0075](0075-governed-position-and-opportunity-management.md) | Accepted | Manage Positions and paired volunteer opportunities through the versioned edition structure boundary and a purpose-oriented owner workflow. |

ADR 0073 partially supersedes the example-data and source-derived-template
parts of [ADR 0042](0042-synthetic-only-educational-fixtures.md) and
[ADR 0045](0045-governance-anchored-copy-on-write-edition-structure.md).
Their synthetic-person, copy-on-write, versioning, provenance, authorization,
and structure-management boundaries remain accepted. Use the
[complete status index](README.md) for every decision.

```{toctree}
:hidden:
:maxdepth: 1
:glob:

README
[0-9][0-9][0-9][0-9]-*
```
