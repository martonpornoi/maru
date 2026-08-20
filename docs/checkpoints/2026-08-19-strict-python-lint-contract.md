# Strict Python lint contract

Date: 2026-08-19

Status: Repository-verified

Requirements: NFR-001, NFR-002, NFR-003
Decision: ADR 0059

## Outcome

Maru now uses the strictest PyDocLint configuration that improves the generated
NumPy reference without manufacturing misleading Django class-attribute or
ceremonial procedure-return documentation. Ruff continues to select its entire
rule catalog, while its global ignore list is reduced from sixteen broad
entries to eight justified categories.

## Contract changes

- PyDocLint checks short and private callables; private, underscore-prefixed,
  and starred parameters; argument order; documented types and defaults;
  return and yield types; assertion failures; and exact named direct raises.
- Eleven bare re-raise boundaries use definition-scoped `DOC503` suppressions
  with an inline reason. They preserve a caught exception after audit, cleanup,
  or command translation; Ruff recognizes `DOC` as an external rule family.
- Constructor parameters are documented on `__init__`, while classes retain
  role and attribute documentation. The repository AST gate remains responsible
  for public dataclass fields.
- The semantic validator rejects two additional contract-shaped placeholder
  families. Mechanically introduced generic parameter, return, and constructor
  prose was replaced with contract-specific language.
- Ruff now enforces missing annotations except explicit `Any`, magic and nested
  class docstrings, redundant-raise normalization, type-checking import
  placement/casts, and production private-member access outside named framework
  adapters. Tests retain scoped executable-documentation and private-test-access
  exclusions.
- The remaining global Ruff categories are `ANN401`, `C901`, `COM812`, `EM101`,
  `EM102`, `ISC001`, `PLR0913`, and `TRY003`. ADR 0059 records why each is not a
  safe repository-wide mechanical rewrite.

## Verification

- Ruff formatting and `select = ["ALL"]` lint pass over 636 files.
- PyDocLint's strict useful configuration and Maru's semantic validator pass
  over 360 production/tooling source files.
- Strict mypy passes over 356 source files.
- The documentation graph validates 249 Markdown files and 202 unique
  requirement identifiers; a fresh warning-fatal Sphinx/AutoAPI HTML build
  succeeds.
- All 1,847 unit tests pass in 60.20 seconds. Repository-wide collection finds
  4,104 tests without an import or collection failure.
- OpenAPI regeneration reports zero errors, retaining 18 known enum-name
  diagnostics and the expected local fail-closed `identity.W001` warning. The
  regenerated Staff Console declarations typecheck. Their SHA-256 values are
  `cbd3cd981fd9b9ae60e8f11745bc759acc6a491af390574b2b62d2ed54e642d0` and
  `1d82884c2d4fc5a0fd7c831dd4b37fb4932ef11df215811bf8549299aced436c`.
- Focused lint-policy and CI-workflow contract tests pass 10 of 10.

## Limits and next actions

Static checks prove agreement and reject known boilerplate; they cannot prove
that every explanation captures every domain nuance. Reviews must still
challenge authorization, disclosure, transaction, idempotency, and failure
semantics. PyDocLint's general class-attribute inference and mandatory
`Returns: None` setting remain intentionally disabled. The eight bounded Ruff
categories may be reduced only through focused, behavior-preserving refactors;
they must not be widened for unrelated changes.

The smallest next action is to let the complete GitHub matrix validate the
generated documentation artifact and stable `CI gate` on the final commit.
