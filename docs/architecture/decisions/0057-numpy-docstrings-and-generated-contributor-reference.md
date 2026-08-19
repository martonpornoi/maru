# ADR 0057: NumPy docstrings and generated contributor reference

- Status: Accepted
- Date: 2026-08-19
- Clarifies: ADR 0001 and ADR 0056
- Requirements: NFR-001, NFR-002, NFR-003

## Context

Maru has extensive product, architecture, module, security, and operations
documentation, but its Python contracts were documented unevenly and no
generated contributor site proved that maintained prose and source reference
could be assembled together. Enabling Ruff's complete rule catalog exposed
missing documentation throughout public production code, while Ruff alone
could not validate that structured parameter and return sections matched each
callable's signature.

ADR 0056 governs the authenticated Swagger and ReDoc presentations of the HTTP
OpenAPI contract. A source-level contributor reference serves a different
audience and must not become another runtime API or authority surface.

## Decision

Use NumPy-style docstrings for public Python under `src/` and repository tools
under `scripts/`. Ruff remains the fast repository-wide format, presence, and
style gate with `select = ["ALL"]` and the NumPy pydocstyle convention.
Repository-level exclusions are explicit: descriptive test names replace
mandatory test docstrings, generated migrations are not hand-maintained, and
private or magic implementation details do not require prose unless their
contract needs explanation.

Use PyDocLint as the structural docstring gate. It checks NumPy sections and
signature agreement while Python annotations remain authoritative for types.
Short docstrings and private callables are not forced into ceremonial sections.
Direct-`raise` matching is disabled because Maru translates domain failures at
application and adapter boundaries; stable caller-facing failures remain
documented where they form a public contract.

Build contributor documentation with Sphinx, MyST, Napoleon, Furo, Mermaid,
and Sphinx AutoAPI. AutoAPI statically analyses `src/maru` without importing
the Django application, excludes generated migrations, and emits public
members into the same portal as every maintained Markdown document. Build
output and intermediate generated sources are ephemeral artifacts.

GitHub Actions runs PyDocLint and a fresh Sphinx HTML build with warnings
treated as errors. The generated site is retained as a reviewable artifact,
and the stable CI gate depends on this documentation job.

## Consequences

- Contributors receive one searchable product, engineering, and Python source
  reference built from repository-owned inputs.
- Public source contracts must remain synchronized with signatures, and broken
  links, unsupported diagram syntax, orphaned documents, or AutoAPI failures
  block acceptance.
- The complete Ruff catalog remains usable through documented, narrowly
  justified compatibility exclusions for Django, strict mypy, and the Ruff
  formatter.
- The Sphinx site is a contributor artifact, not public production hosting,
  production approval, or a substitute for the canonical OpenAPI contract.
- The change introduces no model, migration, tenant, authority, runtime-role,
  API-shape, recovery, or production-cutover boundary.

## Alternatives considered

### Use Ruff docstring checks alone

Rejected because style and presence checks do not verify structured sections
against signatures or prove the complete documentation site can build.

### Require types in docstrings

Rejected because annotations are already checked by strict mypy; repeating
types creates two authorities that can drift.

### Import Django modules through autodoc

Rejected because documentation generation should not require a configured
database, secrets, or executable application startup. Static AutoAPI analysis
keeps the build deterministic and safer.

### Generate reference pages without a warning-fatal CI build

Rejected because an unchecked generator can silently publish broken links,
unreadable directives, and stale source contracts.
