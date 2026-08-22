# Documentation standards

Status: Baseline  
Last updated: 2026-08-22

Documentation is maintained with the implementation.

## Required document types

- **Product requirements:** Stable behavior and acceptance intent.
- **ADRs:** Durable technical and architectural decisions.
- **Module documentation:** Ownership, public contracts, data, permissions,
  events, failure modes, and operational considerations.
- **API documentation:** Generated OpenAPI plus human explanations and examples.
- **Runbooks:** Deployment, migration, backup, restore, reconciliation, incident,
  and external-integration procedures.
- **Role guides:** Task-oriented help for attendees, Front Desk, Registration,
  HR, department leads, programme staff, IT, and other operators.
- **Release notes:** User-visible behavior, breaking changes, migrations, and
  known limitations.
- **Checkpoints:** Concise current handoff and append-only milestone records.

## Module README template

Each implemented module documents:

1. Purpose and requirements served
2. Owned data and invariants
3. Public commands, queries, and events
4. Permission and sensitivity model
5. Dependencies and consumers
6. User and operational workflows
7. Failure, retry, and reconciliation behavior
8. Retention and archival behavior
9. Tests and observability
10. Known limitations and future work

## Writing rules

- Prefer task and domain language over framework terminology.
- State what is authoritative and what is derived.
- Include examples with synthetic data.
- Explain permission failures and sensitive boundaries.
- Date operational assumptions that depend on external providers.
- Link instead of duplicating normative content.
- Mark proposed behavior as proposed; do not describe it as implemented.
- Remove stale instructions in the same change that makes them stale.

## API documentation

OpenAPI is generated and checked in CI. Every public operation has:

- a stable operation identifier;
- purpose and audience;
- authentication and required capabilities;
- organization and edition scoping;
- request, response, and error schemas;
- idempotency and pagination behavior where relevant;
- examples without personal data;
- deprecation information.

## Python reference documentation

Public production Python under `src/` and repository tooling under `scripts/`
use NumPy-style docstrings. Ruff's `D` rules enforce presence, placement, and
summary form with `pydocstyle.convention = "numpy"`. PyDocLint validates public
and private callable sections against their signatures. Python annotations
remain the implementation and static-analysis authority; NumPy declarations
mirror their types and defaults so the generated Sphinx reference is complete
without requiring readers to inspect source signatures.

### Enforced public contract

- Every input appears in `Parameters`, in signature order, with the signature
  type and default where applicable. Forwarded `*args` and `**kwargs` retain
  their stars and explain which framework implementation receives them.
- Every meaningful return or stream has `Returns` or `Yields`. A procedure that
  returns nothing does not add a ceremonial return section. Documented return
  and yield types must agree with the signature.
- A class explains its role and public attributes; explicit constructor inputs
  are documented on `__init__`, beside the signature that PyDocLint validates.
  Public dataclasses document every public field in `Attributes`.
- Every named exception raised directly by a callable appears exactly in
  `Raises`.
  Additional stable exceptions propagated from a documented boundary may also
  be listed when callers are expected to handle them.
- A callable containing an assertion documents `AssertionError` when that
  assertion is part of its contract.
- Summaries state domain intent. The semantic quality gate rejects generated
  prefixes such as `Handle`, `Represent`, and `Compute`, placeholder value or
  result prose, and other repository-known boilerplate patterns.

The description of an input states its meaning, scope, accepted form, or
constraint. The description of a result states what is authoritative,
filtered, ordered, persisted, or safe to disclose. Public domain commands,
queries, services, adapters, views, and models must not merely expand their
Python name.

### Context sections

Use the remaining NumPy sections when they make a durable contract clearer:

- `Notes` explains fail-closed behavior, transaction and locking boundaries,
  idempotency, canonicalization, scope ownership, or a non-obvious design
  choice.
- `Warnings` identifies sensitive material, irreversible behavior, or a safety
  condition a caller could otherwise miss.
- `Examples` is expected for deterministic parsers, normalizers, predicates,
  value objects, and other isolated APIs when a short synthetic example is more
  precise than prose. Examples should be copyable, contain no personal data,
  and avoid database ceremony that obscures the contract.
- `See Also` links genuinely related public contracts without duplicating their
  documentation.

A concise summary is still sufficient for an obvious zero-input framework hook
with no meaningful result, direct exception, or public attributes. Private
implementation details may remain undocumented only when Ruff's presence rules
permit it; once documented, private callable sections receive the same
signature checks as public contracts.

Tests are exempt from docstring-presence rules because descriptive test names
are their executable documentation. Generated Django migrations are also
excluded. PyDocLint's exact direct-`raise` matcher is enabled. Its known bare
re-raise limitation receives a definition-scoped `DOC503` only where audit or
cleanup deliberately preserves the caught exception; every suppression states
that reason inline. Maru's semantic validator independently requires every
directly named exception while permitting additional stable caller-facing
failures.

PyDocLint's general class-attribute inference remains disabled because it
misclassifies Django declarative configuration and reports valid dataclass
fields inconsistently. The repository AST gate enforces public dataclass
`Attributes` instead. PyDocLint also does not require `Returns: None` on every
procedure or duplicate property methods as class attributes; those settings
would add ceremony rather than contract information.

Ruff selects its complete rule catalog. The only global exemptions are
`ANN401`, `C901`, `COM812`, `EM101`, `EM102`, `ISC001`, `PLR0913`, and `TRY003`:
dynamic framework boundaries, separately reviewed complexity refactors,
formatter compatibility, and exception-message locality. Tests have scoped
annotation, docstring, and private-access exclusions. Production `SLF001`
exclusions are limited to named framework adapters and readiness inspectors;
new occurrences must not widen the global policy. ADR 0059 records the full
rationale.

Sphinx builds the contributor portal from all maintained Markdown documents and
a statically analysed AutoAPI reference. Napoleon interprets NumPy sections,
MyST parses Markdown, Mermaid renders diagrams, and Furo provides the HTML
theme. The source reference is distinct from the private Swagger/ReDoc HTTP
contract described in ADR 0056.

`docs/conf.py` reads the one project version from `pyproject.toml` and uses it
for the Sphinx version, release, HTML title, and active-development notice. Do
not copy that value into documentation configuration. A Pages build supplies
its canonical base URL at publication time; a local build deliberately remains
independent of the public deployment address.

Run the documentation gates with:

```powershell
uv run pydoclint src scripts
uv run python scripts/validate_python_docstrings.py src scripts
uv run sphinx-build -W --keep-going --fresh-env -j auto -d docs/_build/doctrees -b html docs docs/_build/html
```

The semantic validator reports stable `PDQ` codes for boilerplate summaries,
contract-shaped placeholder descriptions, missing direct exceptions, and
undocumented public dataclass attributes. The Sphinx build treats every warning
as an error.
Generated files under `docs/_build/` and intermediate AutoAPI pages are build
products and are not committed. Ruff emits LF line endings so generated and
reviewed Python diffs are stable across contributor platforms.

ADR 0072 defines public publication. Pull requests validate and retain the HTML
artifact but cannot deploy. After merge, a dedicated workflow rebuilds from
protected `main` with locked dependencies, checks current remote `main`
immediately before build and deployment, uses fresh temporary HTML and doctree
directories, and uploads only the generated HTML root. The write/OIDC token
exists only in the separate `github-pages` deployment job. Mermaid and D3 use
the exact external versions recorded in `docs/conf.py` and the generated-asset
license record; unused ELK support is disabled. Wiki remains disabled rather
than mirroring maintained source. A public static contributor site does not
change the authenticated OpenAPI authority or establish application deployment,
release, support, or production-data approval.

## User documentation

Role guides are organized around questions and outcomes, not database models.
Common workflows include screenshots or short recordings when the UI exists.
Terminology must match the interface.

## Documentation review

Every material task reviews:

- `docs/project/CURRENT.md`;
- affected requirements;
- relevant ADRs;
- module and API documentation;
- operations and role guides;
- checkpoint need.
