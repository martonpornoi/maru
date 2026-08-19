# Professional Python documentation contracts

Date: 2026-08-19

Status: Repository-verified

Requirements: NFR-001, NFR-002, NFR-003
Decision: ADR 0058

## Outcome

Maru's public Python reference now requires complete NumPy sections rather than
accepting summary-only callable documentation. The repository contains 1,333
`Parameters`, 1,406 `Returns`, 5 `Yields`, 891 `Raises`, and 194 `Attributes`
sections across production source and tooling. Curated `Notes`, `Warnings`,
and synthetic `Examples` explain selected fail-closed, parsing,
canonicalization, transaction, and sensitive-token boundaries.

The new semantic validator complements Ruff and PyDocLint. It rejects known
generated summary and description patterns, checks every directly named public
exception, and verifies public dataclass attributes. GitHub and the complete
local gate run it before the warning-fatal Sphinx build. Tests and generated
migrations retain the exclusions defined by ADR 0057.

## Verification

- `pydoclint src scripts` reports no violations with short-docstring checks
  enabled and framework varargs excluded.
- `python scripts/validate_python_docstrings.py src scripts` validates 360
  source files with no semantic-quality violations.
- Ruff formatting and the complete `ALL` lint baseline pass over 636 files;
  strict mypy passes over 356 source files.
- The documentation validator passes over 247 Markdown files and 202 unique
  requirements. A fresh warning-fatal Sphinx/AutoAPI HTML build succeeds.
- All 1,844 unit tests pass, including the seven semantic-validator and CI
  workflow-contract tests. The 106 focused tests covering curated examples and
  adjacent behavior also pass.
- OpenAPI 3.1 regenerates with zero errors, the corresponding Staff Console
  definitions regenerate and typecheck, and the resulting artifact SHA-256
  values are recorded in `docs/project/CURRENT.md`.

## Boundary and follow-up

This milestone changes contributor documentation and generated descriptions,
not runtime behavior or schema shape. Static gates cannot replace review of
domain nuance. Future changes should add context sections when a public caller
could otherwise misunderstand authorization, side effects, idempotency,
failure handling, or sensitive values.
