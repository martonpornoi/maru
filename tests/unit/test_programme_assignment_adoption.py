"""Frozen native preparation must change only one exact-profile branch."""

import hashlib
from importlib import import_module

import pytest

from maru.events import adoption

_MIGRATION = import_module(
    "maru.workforce.migrations.0029_programme_assignment_adoption"
)


def test_native_programme_source_changes_only_the_no_participation_profile_branch():
    previous = _MIGRATION.function_source(programme=False)
    projected = _MIGRATION.function_source(programme=True)
    assert hashlib.sha256(previous.encode()).hexdigest() == _MIGRATION._PREVIOUS_SOURCE
    assert (
        projected.replace(
            "ELSIF assignment_profile_code IN "
            "('workforce_only', 'programme_operations')",
            "ELSIF assignment_profile_code = 'workforce_only'",
        )
        == previous
    )
    assert "AND assignment_profile_version = 1" in projected
    assert "workforce assignment exact adoption profile is unsupported" in projected
    assert "cannot create Participation evidence" in projected
    assert "requires independent approval" in projected
    assert adoption.adoption_profile("programme_operations", 1) is None
    assert adoption.selectable_adoption_profile("programme_operations") is None


@pytest.mark.parametrize("programme", [False, True])
def test_changed_frozen_guard_never_becomes_a_new_accepted_baseline(
    monkeypatch, programme
):
    original = _MIGRATION._COMMANDS.FORWARD_SQL
    monkeypatch.setattr(
        _MIGRATION._COMMANDS,
        "FORWARD_SQL",
        original.replace("requires independent approval", "changed original guard"),
    )
    with pytest.raises(RuntimeError, match="Frozen assignment source changed"):
        _MIGRATION.function_source(programme=programme)


@pytest.mark.parametrize("used", [False, True])
def test_inherited_execution_fence_precedes_any_successor_replacement(
    monkeypatch, used
):
    trace = []
    apps, editor = object(), object()

    def fence(actual_apps, actual_editor):
        assert (actual_apps, actual_editor) == (apps, editor)
        trace.append("shared_fence")
        if used:
            raise RuntimeError("fix forward")

    def replace(actual_editor, *, programme):
        assert actual_editor is editor
        assert programme is False
        trace.append("replace")

    monkeypatch.setattr(
        _MIGRATION._FENCE, "refuse_used_starter_execution_downgrade", fence
    )
    monkeypatch.setattr(_MIGRATION, "_replace", replace)
    if used:
        with pytest.raises(RuntimeError, match="fix forward"):
            _MIGRATION.restore_assignment(apps, editor)
    else:
        _MIGRATION.restore_assignment(apps, editor)
    assert trace == (["shared_fence"] if used else ["shared_fence", "replace"])
