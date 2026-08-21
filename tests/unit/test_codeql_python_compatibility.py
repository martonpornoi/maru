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


def _trailing_type_parameter_commas(source: str) -> tuple[tuple[int, int], ...]:
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
    return tuple(violations)


def test_type_parameter_detector_rejects_only_a_trailing_header_comma() -> None:
    assert _trailing_type_parameter_commas("def invalid[T,]():\n    pass\n")
    assert _trailing_type_parameter_commas(
        "def invalid_nested[T: tuple[int, str],]():\n    pass\n"
    )
    assert not _trailing_type_parameter_commas(
        "def valid[T: tuple[int, str], U]():\n    pass\n"
    )


def test_type_parameter_headers_preserve_codeql_file_coverage() -> None:
    violations = []
    python_files = list(EXPLICIT_PYTHON_FILES)
    for root_name in PYTHON_ROOTS:
        python_files.extend((REPOSITORY_ROOT / root_name).rglob("*.py"))
    for path in sorted(python_files):
        source = path.read_text(encoding="utf-8")
        for line, column in _trailing_type_parameter_commas(source):
            relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
            violations.append(f"{relative_path}:{line}:{column + 1}")

    assert not violations, (
        "Maru's active CodeQL compatibility boundary rejects a trailing comma "
        "in a PEP 695 type-parameter header because it can omit the containing "
        "file: " + ", ".join(violations)
    )
