# Generated contributor documentation

Date: 2026-08-19

Status: Repository-verified documentation milestone

Requirements: NFR-001, NFR-002, NFR-003
Decision: ADR 0057

## Outcome

Maru's public production Python and repository tooling now carry NumPy-style
docstrings, with existing behavioral detail preserved and missing public
contracts filled in. Ruff's complete rule selection uses the NumPy pydocstyle
convention, while PyDocLint checks structured docstrings against signatures.
Tests and generated migrations retain explicit, documented exclusions.

The new Sphinx portal combines the maintained Markdown tree with a statically
generated public Python reference. MyST, Napoleon, Mermaid, AutoAPI, and Furo
produce a warning-clean HTML site without starting Django or connecting to a
database. Build output is ignored locally and retained as a GitHub Actions
artifact.

The GitHub workflow now has an independent `documentation` job. It validates
docstrings, performs a fresh warning-fatal build, uploads the HTML, and feeds
the stable `CI gate`. The local PowerShell gate runs the same commands.

## Verification

- `ruff check .` passed after the NumPy documentation and explicit ALL-rule
  compatibility baseline.
- `pydoclint src scripts` reported no violations.
- `sphinx-build -W --keep-going --fresh-env -b html docs docs/_build/html`
  completed without warnings.
- Strict mypy passed over 356 source files, documentation validation passed
  over 245 Markdown files and 202 requirement identifiers, and all five CI
  workflow-contract tests passed.
- All 1,842 unit tests passed. Django reported no migration drift and only the
  expected local fail-closed invitation warning; both production-settings
  verification modes passed.
- Fresh OpenAPI 3.1 generation reported zero errors and exactly matched the
  updated checked-in schema at SHA-256
  `79ae8f720e6ce942413e19cb1a973480554159364abecf8ba64ea01b0a035b1c`;
  the TypeScript contract comments were regenerated from it.

## Boundary and follow-up

This is contributor documentation, not a public deployment or a replacement
for the private schema-backed API reference. The smallest follow-up is to
review the uploaded HTML artifact in the corrective GitHub run and keep new
public contracts descriptive as implementation evolves.
