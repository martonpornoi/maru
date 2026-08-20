# ADR 0058: Professional Python documentation contracts

- Status: Accepted
- Date: 2026-08-19
- Partially supersedes: ADR 0057
- Requirements: NFR-001, NFR-002, NFR-003

## Context

ADR 0057 established NumPy-style docstrings, PyDocLint, and a warning-fatal
Sphinx reference. Its first repository-wide migration produced complete public
coverage, but PyDocLint skipped summary-only docstrings and the policy did not
reject mechanically generated prose. A build could therefore pass while a
public callable omitted meaningful parameter, result, or failure information.

PyDocLint can compare direct `raise` statements exactly with a `Raises`
section, but exact control-flow matching is not Maru's public failure contract.
Application boundaries translate exceptions and public callables may propagate
stable failures from lower layers. Conversely, disabling the check entirely
left directly raised exceptions undocumented.

## Decision

Keep NumPy style, annotations as the type authority, and static Sphinx AutoAPI
generation. Strengthen the executable contract as follows:

1. PyDocLint checks short and long public docstrings. Named inputs require
   `Parameters`; meaningful results and streams require `Returns` or `Yields`.
   Framework `*args` and `**kwargs` forwarding does not require ceremonial
   prose.
2. Explicit constructor inputs are documented on the class. Public dataclasses
   document all public fields through `Attributes`; Django declarative model,
   serializer, form, and administration attributes are not duplicated merely
   because they are class assignments.
3. A repository-owned AST validator rejects known generated summary and
   description patterns, requires every directly named exception in `Raises`,
   and permits additional propagated exceptions that form a stable caller
   contract.
4. `Notes`, `Warnings`, and `Examples` remain judgment-based rather than count
   based. They are added where fail-closed behavior, transaction boundaries,
   sensitive values, canonicalization, or isolated deterministic use would
   otherwise be unclear. Examples use synthetic values and avoid production
   personal data.
5. GitHub and the complete local gate run both PyDocLint and the semantic
   validator before the warning-fatal Sphinx build. Ruff writes LF line endings
   for stable cross-platform documentation diffs.

## Consequences

- Public Python signatures cannot gain an undocumented named input or
  meaningful result without failing CI.
- Directly introduced exceptions and public dataclass fields cannot silently
  disappear from the generated reference.
- Repository-known boilerplate fails with stable `PDQ` codes even when it is
  syntactically valid NumPy prose.
- Review remains necessary: static checks can prove structure and reject known
  low-value wording, but cannot prove that every explanation captures all
  domain nuance.
- The stronger source docstrings may refresh OpenAPI descriptions and generated
  client comments where those artifacts intentionally consume endpoint
  docstrings. Schema shapes and runtime behavior do not change.
- This decision adds no route, model, migration, authority, data-retention,
  recovery, or production-cutover boundary.

## Alternatives considered

### Keep summary-only docstrings acceptable everywhere

Rejected because coverage without inputs, outputs, and failures produced a
clean but shallow reference for the public API surface.

### Enable PyDocLint's exact direct-raise matching

Rejected because exact syntactic matching excludes useful propagated failures
and couples public documentation to internal exception translation structure.

### Require examples or notes on every callable

Rejected because quotas create ceremonial prose around framework hooks and
database-bound commands. Context sections are useful when they clarify a
contract, not when they satisfy a counter.
