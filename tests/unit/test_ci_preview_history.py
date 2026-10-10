from pathlib import PurePosixPath

import pytest
from scripts.ci_changes import ChangedFile, classify_changes, parse_name_status


def _change(path: str, status: str = "M") -> ChangedFile:
    return ChangedFile(PurePosixPath(path), status)


@pytest.mark.parametrize("status", ["A", "M"])
def test_preview_retains_current_database_and_quality_checks(status: str) -> None:
    plan = classify_changes((_change("scripts/try_maru.py", status),))
    assert plan.history == "current"
    assert plan.integration == "full"
    assert plan.python
    assert plan.documentation
    assert plan.github_outputs()["history"] == "current"


@pytest.mark.parametrize(
    "path",
    [
        "scripts/new_tool.py",
        "scripts/try_maru_helper.py",
        "scripts/nested/try_maru.py",
        "scripts/ci_changes.py",
        "scripts/certify.ps1",
        "scripts/nightly_ci.py",
        "tests/conftest.py",
        "src/maru/settings/local.py",
        "src/maru/authorization/commands.py",
        ".github/workflows/full-ci.yml",
        "uv.lock",
    ],
)
def test_preview_cannot_downgrade_other_risk(path: str) -> None:
    plan = classify_changes((_change("scripts/try_maru.py"), _change(path)))
    assert plan.history == "all"
    assert plan.integration == "full"


def test_preview_cannot_downgrade_schema_history() -> None:
    plan = classify_changes(
        (_change("scripts/try_maru.py"), _change("src/maru/programme/models.py"))
    )
    assert plan.history == "affected"


def test_preview_deletion_and_rename_remain_destructive() -> None:
    for changes in (
        (_change("scripts/try_maru.py", "D"),),
        parse_name_status("R100\tscripts/old_tool.py\tscripts/try_maru.py"),
        parse_name_status("R100\tscripts/try_maru.py\tscripts/new_tool.py"),
    ):
        plan = classify_changes(changes)
        assert plan.destructive
        assert plan.history == "all"
