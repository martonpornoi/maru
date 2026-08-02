"""Keep production Department writes behind the Page 9 command boundary."""

from __future__ import annotations

import ast
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_WRITERS = (
    Path("src/maru/workforce/bootstrap.py"),
    Path("src/maru/demo/operational_examples.py"),
    Path("src/maru/demo/fixture.py"),
)
_WRITE_METHODS = frozenset(
    {
        "bulk_create",
        "bulk_update",
        "create",
        "delete",
        "get_or_create",
        "update",
        "update_or_create",
    }
)


def _uses_department_manager(expression: ast.expr) -> bool:
    if isinstance(expression, ast.Call):
        return _uses_department_manager(expression.func)
    if isinstance(expression, ast.Attribute):
        return (
            expression.attr == "objects"
            and isinstance(expression.value, ast.Name)
            and expression.value.id == "Department"
        ) or _uses_department_manager(expression.value)
    return False


def test_production_bootstrap_and_demo_have_no_direct_department_writers() -> None:
    violations: list[str] = []
    for relative_path in _PRODUCTION_WRITERS:
        source = (_REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(relative_path))
        violations.extend(
            f"{relative_path.as_posix()}:{node.lineno}:{node.func.attr}"
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _WRITE_METHODS
                and _uses_department_manager(node.func.value)
            )
        )

    assert violations == []
