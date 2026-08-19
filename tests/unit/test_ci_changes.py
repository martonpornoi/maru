from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from scripts.ci_changes import (
    ChangedFile,
    classify_changes,
    parse_name_status,
    select_targeted_integration_tests,
)


def _change(path: str, status: str = "M") -> ChangedFile:
    return ChangedFile(PurePosixPath(path), status)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (("docs/quality/testing-strategy.md",), (True, False, False, "none")),
        (("frontends/staff-console/src/main.tsx",), (False, True, False, "none")),
        (("src/maru/catalog/api.py",), (True, False, True, "targeted")),
        (("src/maru/catalog/models.py",), (True, False, True, "full")),
        (("src/maru/catalog/migrations/0002_x.py",), (True, False, True, "full")),
        (("src/maru/authorization/policy.py",), (True, False, True, "full")),
        (("pyproject.toml",), (True, False, True, "full")),
        ((".github/workflows/ci.yml",), (False, False, False, "full")),
    ],
)
def test_classifier_routes_changes_to_the_smallest_safe_path(
    changes: tuple[str, ...], expected: tuple[bool, bool, bool, str]
) -> None:
    plan = classify_changes(tuple(_change(path) for path in changes))

    assert (
        plan.documentation,
        plan.frontend,
        plan.python,
        plan.integration,
    ) == expected


def test_classifier_flags_protected_and_mass_deletions() -> None:
    protected = classify_changes((_change("src/maru/core/views.py", "D"),))
    mass = classify_changes(
        tuple(_change(f"notes/old-{index}.md", "D") for index in range(25))
    )
    ordinary = classify_changes((_change("notes/old.md", "D"),))

    assert protected.destructive
    assert mass.destructive
    assert not ordinary.destructive


def test_name_status_parser_uses_the_destination_of_a_rename() -> None:
    changes = parse_name_status("R100\told.py\tsrc/maru/core/new.py\nD\told.md\n")

    assert changes == (
        _change("src/maru/core/new.py", "R"),
        _change("old.md", "D"),
    )


def test_targeted_tests_include_direct_module_imports_and_smoke(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    integration = repository_root / "tests" / "integration"
    integration.mkdir(parents=True)
    catalog = integration / "test_catalog_flow.py"
    catalog.write_text("from maru.catalog import api\n", encoding="utf-8")
    direct = integration / "test_direct.py"
    direct.write_text("def test_direct(): pass\n", encoding="utf-8")
    health = integration / "test_health_readiness.py"
    health.write_text("def test_health(): pass\n", encoding="utf-8")
    api_docs = integration / "test_api_documentation.py"
    api_docs.write_text("def test_docs(): pass\n", encoding="utf-8")
    unrelated = integration / "test_workforce.py"
    unrelated.write_text("from maru.workforce import api\n", encoding="utf-8")

    selected = select_targeted_integration_tests(
        (
            _change("src/maru/catalog/api.py"),
            _change("tests/integration/test_direct.py"),
        ),
        integration,
    )

    assert selected == tuple(sorted((api_docs, catalog, direct, health)))
    assert unrelated not in selected
