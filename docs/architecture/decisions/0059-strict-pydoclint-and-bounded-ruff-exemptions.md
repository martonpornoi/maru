# ADR 0059: Strict PyDocLint and bounded Ruff exemptions

- Status: Accepted
- Date: 2026-08-19
- Partially supersedes: ADR 0058
- Requirements: NFR-001, NFR-002, NFR-003

## Context

ADR 0058 made public NumPy docstrings structurally complete and added a
repository semantic-quality gate. Its initial migration deliberately left
several PyDocLint checks disabled while the repository-wide prose was repaired.
It also retained broad Ruff exemptions for annotations, magic and nested-class
docstrings, redundant `raise` parentheses, type-only imports, and private
member access.

That staging boundary no longer represented the intended contributor contract.
A docstring could drift from a signature's types or defaults, private tooling
could remain shallow, and a new violation in one framework adapter could rely
on a repository-wide Ruff exemption. Conversely, enabling every available
switch literally would make the reference worse: PyDocLint treats Django's
declarative class configuration as public instance attributes, reports public
dataclass fields as extraneous under its `ClassVar` mode, and would require
hundreds of ceremonial `Returns: None` sections.

## Decision

Use the strictest PyDocLint contract that improves generated reference quality:

1. Validate short and private callables, private and underscore-prefixed
   parameters, signature order, documented types, documented defaults, and
   starred arguments. Keep Python annotations authoritative while requiring
   the NumPy declaration to mirror them exactly enough for Sphinx readers.
2. Validate return and yield types, including an explicit `Yields: None` for a
   context manager that yields no value. Require an `AssertionError` contract
   when a callable contains a public assertion.
3. Enable PyDocLint's exact direct-raise check. A definition-scoped `DOC503`
   suppression is permitted only for a bare re-raise that deliberately
   preserves the caught exception after audit or cleanup; the suppression
   carries an inline reason. Ruff recognizes `DOC` as an external rule family
   so its unused-suppression check preserves those PyDocLint directives.
4. Permit constructor contracts on `__init__`. Classes continue to explain
   their role and public attributes, while explicit construction parameters
   live beside the signature whose order, type, and default PyDocLint checks.
5. Keep `check-class-attributes` disabled. Maru's AST quality gate remains the
   authority for public dataclass fields because it understands that boundary
   without misclassifying Django models, forms, serializers, administrators,
   and nested configuration classes. Property methods remain documented as
   methods, not duplicated as class attributes.
6. Keep `require-return-section-when-returning-nothing` disabled. Procedures do
   not gain a `Returns: None` section unless a meaningful protocol, such as a
   generator or context manager, requires it.

Keep Ruff on `select = ["ALL"]`, but halve its global ignore list from sixteen
broad entries to these eight bounded categories:

- `ANN401` for deliberate dynamic framework and serialization boundaries;
- `C901` and `PLR0913` for domain orchestration whose decomposition requires a
  separately reviewed behavior-preserving refactor;
- `COM812` and `ISC001` for compatibility with Ruff's formatter;
- `EM101`, `EM102`, and `TRY003` because extracting thousands of local,
  caller-facing exception messages would separate failure text from its guard
  without improving the public contract.

Do not globally exempt missing annotations, magic or nested-class docstrings,
redundant `raise` syntax, private-member access, or type-only import rules.
Tests retain file-scoped annotation, docstring, and private-test-access
exclusions. Production access to framework-owned private state receives only a
narrow adapter/readiness file exemption. These per-file boundaries must not
be widened into global policy.

## Consequences

- CI rejects drift in parameter, return, and yield types; parameter defaults;
  argument order; star-argument spelling; direct raises; and documented
  assertions across both public and private production/tooling callables.
- Sphinx receives richer, signature-aligned NumPy sections while annotations
  remain the implementation and static-analysis authority.
- Ruff now enforces annotation coverage apart from explicit `Any`, documents
  magic methods and nested classes, normalizes redundant raises, and applies
  its type-checking import rules repository-wide.
- Local `DOC503` and production `SLF001` exceptions are reviewable at the exact
  boundary that needs them. A repository-wide ignore can no longer conceal a
  new occurrence.
- Mechanical compliance is not accepted as professional prose. The semantic
  validator also rejects contract-shaped placeholders such as “accepted by
  this callable contract” and “defined by this callable's public contract.”
- The migration changes source documentation, annotations, import placement,
  and generated descriptions. It adds no route, model, migration, authority,
  data-retention, recovery, or production-cutover behavior.

## Alternatives considered

### Enable every PyDocLint class-attribute switch

Rejected because the available heuristics do not model Django declarative
classes or Maru's dataclass policy accurately. The result was hundreds of
false contracts and contradictory reports for legitimate dataclass fields.

### Require `Returns: None` for every procedure

Rejected because it produced hundreds of sections that communicate no caller
contract and make meaningful return documentation harder to scan.

### Keep exact raises disabled and rely only on the semantic validator

Rejected because exact matching is now viable for named direct raises. The
small bare-re-raise limitation is clearer as a reasoned, local suppression than
as a disabled repository-wide check.

### Remove every remaining Ruff ignore in the same change

Rejected because formatter-conflict rules cannot be enabled together, while
the complexity, argument-count, dynamic-typing, and exception-message families
represent intentional refactors rather than safe lint-only rewrites. Their
bounded inventory is visible and may shrink in later focused changes.
