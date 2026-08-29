from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest
from scripts.ci_changes import (
    ChangedFile,
    classify_changes,
    enforce_targeted_time_budget,
    parse_name_status,
    select_targeted_integration_tests,
)


def _change(path: str, status: str = "M") -> ChangedFile:
    return ChangedFile(PurePosixPath(path), status)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (("docs/quality/testing-strategy.md",), (True, False, False, "none")),
        (
            (".agents/skills/maru-pr-delivery/agents/openai.yaml",),
            (True, False, False, "none"),
        ),
        (("frontends/staff-console/src/main.tsx",), (False, True, False, "none")),
        (
            ("src/maru/core/static/staff-console/app.js",),
            (False, True, False, "none"),
        ),
        (
            ("src/maru/core/templates/core/home.html",),
            (True, False, True, "targeted"),
        ),
        (
            ("src/maru/workforce/static/workforce/organization_structure.css",),
            (True, False, True, "targeted"),
        ),
        (
            ("src/maru/templates/admin/base_site.html",),
            (True, False, True, "full"),
        ),
        (
            ("src/maru/static/global.css",),
            (True, False, True, "full"),
        ),
        (("src/maru/catalog/api.py",), (True, False, True, "targeted")),
        (("src/maru/catalog/models.py",), (True, False, True, "full")),
        (("src/maru/catalog/migrations/0002_x.py",), (True, False, True, "full")),
        (("src/maru/authorization/policy.py",), (True, False, True, "full")),
        (("pyproject.toml",), (True, False, True, "full")),
        ((".github/workflows/ci.yml",), (False, False, False, "full")),
        (("scripts/validate_docs.py",), (True, False, True, "full")),
        (("scripts/rehearse_oci_runtime.py",), (True, False, True, "full")),
        ((".githooks/pre-push",), (False, False, False, "full")),
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


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/quality/testing-strategy.md", False),
        ("LICENSE", True),
        ("README.md", True),
        ("THIRD_PARTY_NOTICES.md", True),
        ("pyproject.toml", True),
        ("frontends/staff-console/src/main.tsx", True),
        ("src/maru/catalog/api.py", True),
        ("tests/unit/test_catalog.py", False),
    ],
)
def test_classifier_marks_python_distribution_inputs(path: str, expected: bool) -> None:
    plan = classify_changes((_change(path),))

    assert plan.packaging is expected
    assert plan.github_outputs()["packaging"] == str(expected).lower()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("Dockerfile", True),
        ("pyproject.toml", True),
        ("uv.lock", True),
        ("frontends/staff-console/package.json", True),
        ("frontends/staff-console/pnpm-lock.yaml", True),
        (".github/workflows/ci.yml", True),
        (".github/actions-allowlist.json", False),
        ("docs/quality/testing-strategy.md", False),
        ("src/maru/catalog/api.py", False),
    ],
)
def test_classifier_marks_dependency_and_automation_security_inputs(
    path: str, expected: bool
) -> None:
    plan = classify_changes((_change(path),))

    assert plan.security is expected
    assert plan.github_outputs()["security"] == str(expected).lower()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("Dockerfile", False),
        ("pyproject.toml", True),
        ("uv.lock", True),
        ("frontends/staff-console/package.json", True),
        ("frontends/staff-console/pnpm-lock.yaml", True),
        (".github/workflows/ci.yml", True),
        (".github/workflows/release.yaml", True),
        (".github/workflows/README.md", False),
        (".github/actions-allowlist.json", False),
        ("docs/quality/testing-strategy.md", False),
        ("src/maru/catalog/api.py", False),
    ],
)
def test_classifier_marks_graph_visible_dependency_inputs(
    path: str, expected: bool
) -> None:
    plan = classify_changes((_change(path),))

    assert plan.dependency_review is expected
    assert plan.github_outputs()["dependency_review"] == str(expected).lower()


def test_classifier_flags_protected_and_mass_deletions() -> None:
    protected = classify_changes((_change("src/maru/core/views.py", "D"),))
    test_contract = classify_changes(
        (_change("tests/unit/test_ci_workflow_contract.py", "D"),)
    )
    deployment_contract = classify_changes((_change("Dockerfile", "D"),))
    frontend_source = classify_changes(
        (_change("frontends/staff-console/src/main.tsx", "D"),)
    )
    checkpoint = classify_changes(
        (_change("docs/checkpoints/2026-08-21-example.md", "D"),)
    )
    agent_skill = classify_changes(
        (_change(".agents/skills/maru-change-map/SKILL.md", "D"),)
    )
    requirements = classify_changes((_change("docs/product/requirements.md", "D"),))
    third_party_notices = classify_changes((_change("THIRD_PARTY_NOTICES.md", "D"),))
    mass = classify_changes(
        tuple(_change(f"notes/old-{index}.md", "D") for index in range(25))
    )
    ordinary = classify_changes((_change("notes/old.md", "D"),))

    assert protected.destructive
    assert protected.integration == "full"
    assert test_contract.destructive
    assert test_contract.integration == "full"
    assert deployment_contract.destructive
    assert deployment_contract.integration == "full"
    assert frontend_source.destructive
    assert frontend_source.integration == "full"
    assert checkpoint.destructive
    assert checkpoint.integration == "full"
    assert agent_skill.destructive
    assert agent_skill.integration == "full"
    assert requirements.destructive
    assert requirements.integration == "full"
    assert third_party_notices.destructive
    assert third_party_notices.integration == "full"
    assert mass.destructive
    assert mass.integration == "full"
    assert not ordinary.destructive


def test_name_status_parser_preserves_both_sides_of_a_rename() -> None:
    changes = parse_name_status("R100\told.py\tsrc/maru/core/new.py\nD\told.md\n")

    assert changes == (
        _change("old.py", "D"),
        _change("src/maru/core/new.py", "R"),
        _change("old.md", "D"),
    )


def test_protected_rename_preserves_deletion_review_and_full_acceptance() -> None:
    changes = parse_name_status(
        "R100\t.github/workflows/ci.yml\tnotes/archived-ci.yml\n"
    )

    plan = classify_changes(changes)

    assert changes == (
        _change(".github/workflows/ci.yml", "D"),
        _change("notes/archived-ci.yml", "R"),
    )
    assert plan.destructive
    assert plan.deleted_count == 1
    assert plan.integration == "full"


def test_mass_renames_require_destructive_review_and_full_acceptance() -> None:
    changes = parse_name_status(
        "".join(
            f"R100\tnotes/old-{index}.md\tarchive/old-{index}.md\n"
            for index in range(25)
        )
    )

    plan = classify_changes(changes)

    assert plan.destructive
    assert plan.deleted_count == 25
    assert plan.integration == "full"


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


def test_targeted_plan_fails_over_to_full_when_measured_selection_is_too_slow(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    integration = repository_root / "tests" / "integration"
    integration.mkdir(parents=True)
    for relative_path in (
        "tests/integration/test_api_documentation.py",
        "tests/integration/test_catalog_flow.py",
        "tests/integration/test_health_readiness.py",
    ):
        path = repository_root / relative_path
        path.write_text("from maru.catalog import api\n", encoding="utf-8")
    timing_file = repository_root / "scripts" / "ci_integration_timings.json"
    timing_file.parent.mkdir()
    timing_file.write_text(
        json.dumps(
            {
                "tests/integration/test_api_documentation.py": 10.0,
                "tests/integration/test_catalog_flow.py": 1_790.0,
                "tests/integration/test_health_readiness.py": 10.0,
            }
        ),
        encoding="utf-8",
    )
    changes = (_change("src/maru/catalog/api.py"),)
    plan = classify_changes(changes)

    routed = enforce_targeted_time_budget(plan, changes, integration, timing_file)
    timing_file.write_text(
        json.dumps(
            {
                "tests/integration/test_api_documentation.py": 10.0,
                "tests/integration/test_catalog_flow.py": 20.0,
                "tests/integration/test_health_readiness.py": 10.0,
            }
        ),
        encoding="utf-8",
    )
    bounded = enforce_targeted_time_budget(plan, changes, integration, timing_file)
    timing_file.write_text(
        json.dumps(
            {
                "tests/integration/test_api_documentation.py": 10.0,
                "tests/integration/test_catalog_flow.py": float("nan"),
                "tests/integration/test_health_readiness.py": 10.0,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="finite and positive"):
        enforce_targeted_time_budget(plan, changes, integration, timing_file)
    timing_file.write_text(
        json.dumps(
            {
                "tests/integration/test_api_documentation.py": 10.0,
                "tests/integration/test_catalog_flow.py": True,
                "tests/integration/test_health_readiness.py": 10.0,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="string paths and numbers"):
        enforce_targeted_time_budget(plan, changes, integration, timing_file)
    missing_timings = enforce_targeted_time_budget(
        plan,
        changes,
        integration,
        repository_root / "missing.json",
    )

    assert plan.integration == "targeted"
    assert routed.integration == "full"
    assert bounded.integration == "targeted"
    assert missing_timings.integration == "full"


def test_targeted_plan_fails_over_when_a_selected_file_has_no_timing(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    integration = repository_root / "tests" / "integration"
    integration.mkdir(parents=True)
    selected_paths = (
        "tests/integration/test_api_documentation.py",
        "tests/integration/test_catalog_flow.py",
        "tests/integration/test_health_readiness.py",
    )
    for relative_path in selected_paths:
        path = repository_root / relative_path
        path.write_text("from maru.catalog import api\n", encoding="utf-8")
    timing_file = repository_root / "scripts" / "ci_integration_timings.json"
    timing_file.parent.mkdir()
    timing_file.write_text(
        json.dumps(dict.fromkeys(selected_paths[:-1], 10.0)),
        encoding="utf-8",
    )
    changes = (_change("src/maru/catalog/api.py"),)
    plan = classify_changes(changes)

    routed = enforce_targeted_time_budget(plan, changes, integration, timing_file)

    assert plan.integration == "targeted"
    assert routed.integration == "full"
