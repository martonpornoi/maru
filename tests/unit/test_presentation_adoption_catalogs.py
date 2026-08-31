"""Repository contracts for adoption-governed presentation catalogs."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from maru.events.adoption import (
    SHELL_DESTINATION_KIND_CATALOG,
    STAFF_CONSOLE_DESTINATION_CATALOG,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_STAFF_CONSOLE_MODEL = (
    _REPOSITORY_ROOT / "frontends" / "staff-console" / "src" / "model.ts"
)
_NAVIGATION_SOURCE = _REPOSITORY_ROOT / "src" / "maru" / "core" / "navigation.py"
_STAFF_DESTINATION_DECLARATION = re.compile(
    r"export const staffConsoleDestinations = \[(?P<body>.*?)\] as const;",
    flags=re.DOTALL,
)
_TYPESCRIPT_STRING_LITERAL = re.compile(r'"(?P<value>[^"]+)"')


def _typescript_staff_console_destinations() -> tuple[str, ...]:
    source = _STAFF_CONSOLE_MODEL.read_text(encoding="utf-8")
    declaration = _STAFF_DESTINATION_DECLARATION.search(source)
    assert declaration is not None, (
        "model.ts must retain one literal staffConsoleDestinations declaration"
    )
    return tuple(
        match.group("value")
        for match in _TYPESCRIPT_STRING_LITERAL.finditer(declaration.group("body"))
    )


def _call_name(call: ast.Call) -> str:
    return call.func.id if isinstance(call.func, ast.Name) else ""


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next(
        (keyword.value for keyword in call.keywords if keyword.arg == name),
        None,
    )


def _enclosing_function_name(
    node: ast.AST,
    *,
    parents: dict[ast.AST, ast.AST],
) -> str:
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return parent.name
        parent = parents.get(parent)
    return ""


def _literal_navigation_profile_destinations() -> frozenset[str]:
    source = _NAVIGATION_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_NAVIGATION_SOURCE))
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    destinations: set[str] = set()
    dynamic_navigation_values: list[tuple[str, str]] = []
    dynamic_workspace_codes: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node)
        if call_name == "NavigationItem":
            value = _keyword(node, "profile_destination_kind")
            if value is None:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                destinations.add(value.value)
                continue
            dynamic_navigation_values.append(
                (
                    _enclosing_function_name(node, parents=parents),
                    ast.unparse(value),
                )
            )
        elif call_name == "_workspace_item":
            value = _keyword(node, "code")
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                destinations.add(value.value)
            else:
                dynamic_workspace_codes.append(
                    "<missing>" if value is None else ast.unparse(value)
                )

    assert dynamic_navigation_values == [("_workspace_item", "code")], (
        "profile-scoped NavigationItem destinations must remain literal, except for "
        "the _workspace_item helper's literal call-site code"
    )
    assert not dynamic_workspace_codes, (
        "every _workspace_item call must provide a literal governed code"
    )
    return frozenset(destinations)


def test_staff_console_typescript_and_python_destination_catalogs_match() -> None:
    """Fail CI when either language recognizes a destination the other does not."""
    destinations = _typescript_staff_console_destinations()

    assert len(destinations) == len(set(destinations))
    assert frozenset(destinations) == STAFF_CONSOLE_DESTINATION_CATALOG


def test_navigation_literals_are_registered_shell_destination_kinds() -> None:
    """Require every emitted literal presentation kind to be registered."""
    assert _literal_navigation_profile_destinations() <= SHELL_DESTINATION_KIND_CATALOG
