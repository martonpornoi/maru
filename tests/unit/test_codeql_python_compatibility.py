"""Repository contracts for CodeQL-compatible Python syntax."""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOTS = ("src", "scripts", "tests")
EXPLICIT_PYTHON_FILES = (REPOSITORY_ROOT / "docs" / "conf.py",)
DECLARATION_KEYWORDS = {"class", "def", "type"}
IGNORED_TOKEN_TYPES = {
    tokenize.COMMENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.INDENT,
    tokenize.NEWLINE,
    tokenize.NL,
}


def _incompatible_type_parameter_headers(
    source: str,
) -> tuple[tuple[int, int], ...]:
    tokens = tuple(
        token
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in IGNORED_TOKEN_TYPES
    )
    violations: list[tuple[int, int]] = []
    for index, token in enumerate(tokens[:-2]):
        if token.type != tokenize.NAME or token.string not in DECLARATION_KEYWORDS:
            continue
        name = tokens[index + 1]
        opener = tokens[index + 2]
        if name.type != tokenize.NAME or opener.string != "[":
            continue

        square_depth = 0
        for cursor in range(index + 2, len(tokens)):
            current = tokens[cursor]
            if current.string == "[":
                square_depth += 1
            elif current.string == "]":
                square_depth -= 1
                if square_depth == 0:
                    if tokens[cursor - 1].string == ",":
                        violations.append(current.start)
                    break
            elif current.string == "|" and square_depth == 1:
                violations.append(current.start)
    return tuple(violations)


def test_detector_rejects_known_incompatible_header_shapes() -> None:
    assert _incompatible_type_parameter_headers("def invalid[T,]():\n    pass\n")
    assert _incompatible_type_parameter_headers(
        "def invalid_union[T: Left | Right]():\n    pass\n"
    )
    assert not _incompatible_type_parameter_headers(
        "def valid[T: tuple[int, str], U]():\n    pass\n"
    )
    assert not _incompatible_type_parameter_headers(
        "def valid_bound[T: Model]():\n    pass\n"
    )
    assert not _incompatible_type_parameter_headers(
        "def valid_nested[T: tuple[Left | Right, str]]():\n    pass\n"
    )


def test_known_codeql_incompatible_type_parameter_headers_are_absent() -> None:
    violations = []
    python_files = list(EXPLICIT_PYTHON_FILES)
    for root_name in PYTHON_ROOTS:
        python_files.extend((REPOSITORY_ROOT / root_name).rglob("*.py"))
    for path in sorted(python_files):
        source = path.read_text(encoding="utf-8")
        for line, column in _incompatible_type_parameter_headers(source):
            relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
            violations.append(f"{relative_path}:{line}:{column + 1}")

    assert not violations, (
        "Maru rejects PEP 695 header shapes that have caused the active "
        "GitHub-managed CodeQL extractor to omit a Python file: "
        + ", ".join(violations)
    )
