# ADR 0069: CodeQL-compatible union-bounded generic

- Status: Accepted
- Date: 2026-08-21
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011
- Implements: GH-005 corrective evidence
- Supersedes: ADR 0066 decision 8 and its trailing-comma-only compatibility
  consequence

## Context

ADR 0066 removed a legal trailing comma from the PEP 695 type-parameter header
of Workforce's `_validate_parent_graph`. Local Python 3.12 compilation, Ruff,
mypy, and tests passed, but only a GitHub-managed CodeQL run could prove that
the extractor analyzed the file.

Draft pull request 9 supplied that proof and disproved the first diagnosis.
Python CodeQL run `32483580306`, job `96775038325`, finished green but emitted
one raw syntax diagnostic at `src/maru/workforce/queries.py:391`. It reported
that the file could not be processed. The aggregate also said that all 802
Python files were scanned, so a green check and its file count were not
sufficient file-coverage evidence.

Other repository PEP 695 generics with a simple bound were accepted. The
remaining declaration was distinguished by its union bound. Python's syntax is
valid and intentional; the defect is loss of security-analysis coverage, not a
runtime syntax error.

## Decision

1. Express this one union-bounded generic with a module-level
   `_ParentGraphRowT = TypeVar(..., bound=_DepartmentRow | _PositionRow)` and
   an ordinary function header. It preserves the type-checking relationship and
   call/return behavior. Maru has no consumer of this private function's
   `__type_params__`; the legacy form intentionally does not preserve that
   introspection detail.
2. Retain Ruff's `UP047` rule globally. Suppress it only on this function and
   place the hosted CodeQL rationale immediately above the declaration.
3. Extend the repository compatibility contract to reject the two known
   unsupported header shapes: a trailing type-parameter comma and a top-level
   union bound within a PEP 695 type-parameter header. Continue allowing simple
   bounds and nested union expressions; this is not a repository-wide rollback
   to legacy typing syntax or a broader ban without hosted evidence.
4. Describe the contract as a guard against known incompatible shapes, not as
   proof of server-side file coverage. Acceptance requires a fresh managed
   Python CodeQL log with zero raw extraction diagnostic, zero
   `Could not process some files due to syntax errors` summary, and no
   `workforce/queries.py` parse location.
5. Treat run `32483580306` as a failed coverage proof even though its CodeQL
   check is green. Do not mark ADR 0066's Workforce coverage objective complete
   until the replacement hosted log satisfies decision 4.

## Consequences

- Python call/return behavior and the checked generic relationship remain
  unchanged while the security-relevant Workforce query file becomes
  expressible to the active extractor. The unused `__type_params__`
  introspection differs intentionally.
- One narrowly documented modernize-typing suppression is preferable to a
  global Ruff exemption or disabling PEP 695 throughout the project.
- The tokenizer contract prevents recurrence of the two known parser gaps,
  but it does not claim compatibility with every future Python syntax feature
  or CodeQL version.
- Managed CodeQL can remain GitHub-owned; no duplicate custom CodeQL workflow or
  parser version pin is added.

## Alternatives considered

### Accept the green CodeQL aggregate

Rejected because the job log explicitly says the complete Workforce file was
not processed. Merge protection over findings cannot protect code that the
extractor omitted.

### Ban every PEP 695 declaration

Rejected because the live extractor accepts the repository's simple bounded
and unbounded declarations. A broad ban would discard useful Python 3.12
syntax without evidence.

### Disable Ruff UP047 globally

Rejected because the compatibility exception applies to one evidenced
declaration. The rest of the repository should retain the modern-typing rule.

### Add a repository-owned CodeQL workflow with another version

Rejected because managed default setup already owns analysis and merge
protection. A second workflow would add cost, permissions, and configuration
drift without fixing the source-level compatibility boundary.

## References

- [Pull request 9 Python CodeQL run](https://github.com/martonpornoi/maru/actions/runs/32483580306/job/96775038325)
- [Python `TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)
- [CodeQL Python syntax-error query](https://codeql.github.com/codeql-query-help/python/py-syntax-error/)

## Requirements affected

- NFR-001 requires the security analyzer to cover the relevant source file, not
  merely return a green aggregate result.
- NFR-002 requires current state and checkpoints to distinguish local syntax
  validity from hosted extraction coverage.
- NFR-003 records the failed first attempt and the exact replacement proof in a
  new append-only checkpoint.
- NFR-011 keeps managed CodeQL and its protection intact while adding a narrow,
  testable source compatibility boundary.
