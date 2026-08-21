# CodeQL union-bound extraction correction

Date: 2026-08-21
Status: Local corrective candidate; replacement hosted extraction proof pending
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0069

## Outcome

The first ADR 0066 compatibility edit was insufficient. Draft pull request 9's
managed Python CodeQL job completed successfully but still omitted
`src/maru/workforce/queries.py` after reporting a syntax diagnostic. The local
candidate now replaces that one PEP 695 union-bounded function header with a
bounded `TypeVar` that preserves its type-checking relationship and call/return
behavior, and strengthens the known-incompatibility contract. No Maru code
introspects the private function's intentionally different `__type_params__`.

This checkpoint corrects the earlier attribution without rewriting it: legal
Python 3.12 syntax remained valid throughout, the trailing comma was not the
only active-extractor incompatibility, and a green CodeQL check did not prove
file coverage.

## Hosted evidence that failed

Managed CodeQL run `32483580306`, Python job `96775038325`, analyzed draft pull
request 9 head `6fedb02`. Its log contained all of the following:

- one raw diagnostic message;
- `Could not process some files due to syntax errors (1 result)`;
- a parse location in `src/maru/workforce/queries.py` at line 391; and
- an aggregate claim that 802 of 802 Python files were scanned.

The job and aggregate check were green. Maru therefore treats the log as a
failed coverage proof and does not claim that the Workforce file was analyzed.

## Corrective implementation

- `_ParentGraphRowT` is a module-level `TypeVar` with the exact prior union
  bound `_DepartmentRow | _PositionRow`.
- `_validate_parent_graph` uses the ordinary function header and the same type
  variable for its row map and parent callback.
- Ruff's `UP047` exception is local to that definition and carries the CodeQL
  rationale; the global ALL-rule policy is unchanged.
- NumPy parameter contracts name the replacement type and clarify the scoped
  graph, parent callback, bounded-depth return, missing-parent failure, and
  cycle failure.
- The repository tokenizer now rejects a trailing type-parameter comma and a
  top-level union bound while proving that simple bounds and nested union type
  expressions remain allowed.

## Local verification

- Python 3.12 byte-compilation of `workforce/queries.py`: pass.
- Ruff ALL-rule lint and format over the source and compatibility contract:
  pass.
- Strict mypy over the source and compatibility contract: pass.
- PyDocLint over `workforce/queries.py`: no violation.
- CodeQL compatibility unit contracts: 2 passed.
- Workforce department-depth and position-reporting-depth integration cases:
  2 passed in 52.68 seconds against PostgreSQL.
- Whitespace validation: pass.

These checks prove Python and project behavior, not CodeQL extraction.

## Required hosted acceptance

Push this focused correction while pull request 9 remains draft. Inspect the
new managed Python CodeQL log rather than relying on the green aggregate. The
correction is accepted only when the log contains no raw extraction diagnostic,
no syntax-error processing summary, and no parse location for
`workforce/queries.py`. Ready-state repository acceptance remains separately
required before merge.
