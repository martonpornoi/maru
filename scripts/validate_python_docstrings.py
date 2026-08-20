"""Validate semantic quality rules that style-oriented docstring linters omit."""

from __future__ import annotations

import argparse
import ast
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tools",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "migrations",
    "node_modules",
    "tests",
}
SECTION_UNDERLINE = re.compile(r"^-{3,}$")
PLACEHOLDER_SUMMARY = re.compile(r"^(?:Compute|Handle|Represent)\b")
PLACEHOLDER_DESCRIPTION = re.compile(
    r"^(?:"
    r"The [A-Za-z_][A-Za-z0-9_]* value\."
    r"|The result of the operation\."
    r"|The .+ supplied to the operation\."
    r"|The .+ produced by .+\."
    r"|The documented value produced by the operation\."
    r"|The value to process\."
    r"|The resulting .+\."
    r"|The .+ in scope for the operation\."
    r"|Whether to enable .+\."
    r"|The ordered .+ collection to process\."
    r"|The .+ required by this documented contract\."
    r"|The .+ consumed by this public contract\."
    r"|The .+ accepted by this callable contract\."
    r"|The value defined by this callable's public contract\."
    r"|The committed .+ returned by .+\."
    r")$"
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Describe one source-documentation quality violation.

    Attributes
    ----------
    path
        The Python source file containing the violation.
    line
        The one-based source line where the documented object begins.
    code
        The stable validation code used in CI output.
    message
        The contributor-facing explanation of the violation.
    """

    path: Path
    line: int
    code: str
    message: str


class _DirectRaiseVisitor(ast.NodeVisitor):
    """Collect named exceptions raised directly by one callable body."""

    def __init__(self) -> None:
        """Initialize the _DirectRaiseVisitor instance."""
        self.names: set[str] = set()

    def visit_Raise(self, node: ast.Raise) -> None:
        name = _raised_exception_name(node.exc)
        if name is not None:
            self.names.add(name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        del node

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        del node

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        del node

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node


def _raised_exception_name(expression: ast.expr | None) -> str | None:
    if isinstance(expression, ast.Call):
        expression = expression.func
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return expression.attr
    return None


def _direct_raises(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    visitor = _DirectRaiseVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.names


def _sections(docstring: str) -> dict[str, list[str]]:
    lines = inspect.cleandoc(docstring).splitlines()
    sections: dict[str, list[str]] = {}
    index = 0
    while index + 1 < len(lines):
        title = lines[index].strip()
        if title and SECTION_UNDERLINE.fullmatch(lines[index + 1].strip()):
            body_start = index + 2
            body_end = body_start
            while body_end + 1 < len(lines):
                if lines[body_end].strip() and SECTION_UNDERLINE.fullmatch(
                    lines[body_end + 1].strip()
                ):
                    break
                body_end += 1
            sections[title] = lines[body_start:body_end]
            index = body_end
        else:
            index += 1
    return sections


def _section_entries(lines: list[str]) -> set[str]:
    entries: set[str] = set()
    for line in lines:
        if not line or line[0].isspace():
            continue
        declaration = line.split(":", maxsplit=1)[0]
        entries.update(
            part.strip().lstrip("*").rsplit(".", maxsplit=1)[-1]
            for part in declaration.split(",")
        )
    return entries


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _is_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        candidate = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(candidate, ast.Name) and candidate.id == "dataclass":
            return True
        if isinstance(candidate, ast.Attribute) and candidate.attr == "dataclass":
            return True
    return False


def _is_class_var(annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.Name):
        return annotation.id == "ClassVar"
    if isinstance(annotation, ast.Subscript):
        return _is_class_var(annotation.value)
    if isinstance(annotation, ast.Attribute):
        return annotation.attr == "ClassVar"
    return False


def _dataclass_fields(node: ast.ClassDef) -> set[str]:
    fields: set[str] = set()
    for statement in node.body:
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and _is_public(statement.target.id)
            and not _is_class_var(statement.annotation)
        ):
            fields.add(statement.target.id)
    return fields


def _definition_issues(
    path: Path,
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ValidationIssue]:
    if not _is_public(node.name):
        return []
    docstring = ast.get_docstring(node, clean=True)
    if docstring is None:
        return []

    issues: list[ValidationIssue] = []
    summary = docstring.splitlines()[0].strip()
    if PLACEHOLDER_SUMMARY.match(summary):
        issues.append(
            ValidationIssue(
                path,
                node.lineno,
                "PDQ001",
                "replace the generated summary with explicit domain intent",
            )
        )

    if any(
        PLACEHOLDER_DESCRIPTION.fullmatch(line.strip())
        for line in docstring.splitlines()
    ):
        issues.append(
            ValidationIssue(
                path,
                node.lineno,
                "PDQ002",
                "replace placeholder value/result prose with meaning or constraints",
            )
        )

    sections = _sections(docstring)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raised = _direct_raises(node)
        documented = _section_entries(sections.get("Raises", []))
        missing = sorted(raised - documented)
        if missing:
            issues.append(
                ValidationIssue(
                    path,
                    node.lineno,
                    "PDQ003",
                    "document directly raised exceptions: " + ", ".join(missing),
                )
            )

    if isinstance(node, ast.ClassDef) and _is_dataclass(node):
        fields = _dataclass_fields(node)
        documented = _section_entries(sections.get("Attributes", []))
        missing = sorted(fields - documented)
        if missing:
            issues.append(
                ValidationIssue(
                    path,
                    node.lineno,
                    "PDQ004",
                    "document public dataclass attributes: " + ", ".join(missing),
                )
            )
    return issues


def validate_file(path: Path) -> list[ValidationIssue]:
    """Validate professional docstring rules in one Python source file.

    Parameters
    ----------
    path : Path
        The Python source file to parse and inspect.

    Returns
    -------
    list[ValidationIssue]
        The violations in deterministic source order.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    issues: list[ValidationIssue] = []

    def visit_container(body: list[ast.stmt]) -> None:
        for statement in body:
            if isinstance(
                statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                issues.extend(_definition_issues(path, statement))
                if isinstance(statement, ast.ClassDef):
                    visit_container(statement.body)

    visit_container(tree.body)
    return issues


def _python_files(paths: Sequence[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        candidates = [path] if path.is_file() else path.rglob("*.py")
        files.update(
            candidate
            for candidate in candidates
            if candidate.suffix == ".py"
            and not EXCLUDED_PARTS.intersection(candidate.parts)
        )
    return sorted(files)


def main(argv: Sequence[str] | None = None) -> int:
    """Run semantic Python-docstring validation.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Optional command-line arguments; defaults to the current process arguments.

    Returns
    -------
    int
        Zero when every checked docstring meets the policy, otherwise one.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=("src", "scripts"), type=Path)
    arguments = parser.parse_args(argv)
    files = _python_files(arguments.paths)
    issues = [issue for path in files for issue in validate_file(path)]
    for issue in issues:
        print(f"{issue.path}:{issue.line}: {issue.code}: {issue.message}")
    if issues:
        print(f"Python docstring quality failed: {len(issues)} violation(s).")
        return 1
    print(f"Python docstring quality valid: {len(files)} source files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
