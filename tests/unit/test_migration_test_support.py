"""Unit contracts for historical-migration test cleanup."""

from unittest.mock import Mock, call, patch

import pytest

from tests.support.migrations import (
    flush_then_restore_current_migration_graph,
    registration_migration_targets,
)


@pytest.mark.parametrize(
    ("target", "forward_plan", "expected_workforce"),
    [
        (
            ("registration", "0038_governed_registration_commerce"),
            (("registration", "0038_governed_registration_commerce"),),
            ("workforce", "0007_structure_write_integrity"),
        ),
        (
            ("registration", "0039_profile_audiences_and_platform_starter"),
            (("registration", "0039_profile_audiences_and_platform_starter"),),
            ("workforce", "0009_reconcile_fictional_structure_template"),
        ),
        (
            ("registration", "0040_optional_profile_value_clear"),
            (
                ("registration", "0039_profile_audiences_and_platform_starter"),
                ("registration", "0040_optional_profile_value_clear"),
            ),
            ("workforce", "0009_reconcile_fictional_structure_template"),
        ),
    ],
)
def test_registration_history_selects_a_compatible_workforce_leaf(
    target: tuple[str, str],
    forward_plan: tuple[tuple[str, str], ...],
    expected_workforce: tuple[str, str],
) -> None:
    executor = Mock()
    executor.loader.graph.leaf_nodes.return_value = (
        ("other", "0002_current"),
        ("registration", "0040_optional_profile_value_clear"),
        ("workforce", "0009_reconcile_fictional_structure_template"),
    )
    executor.loader.graph.forwards_plan.return_value = forward_plan

    assert registration_migration_targets(executor, target) == (
        ("other", "0002_current"),
        target,
        expected_workforce,
    )
    executor.loader.graph.forwards_plan.assert_called_once_with(target)


def test_historical_data_is_flushed_before_current_leaves_are_restored() -> None:
    events: list[str] = []
    executor = object()

    def record_flush(*_args: object, **_kwargs: object) -> None:
        events.append("flush")

    def record_restore() -> object:
        events.append("restore")
        return executor

    with (
        patch("tests.support.migrations.connection") as connection,
        patch("tests.support.migrations.call_command") as call_command,
        patch("tests.support.migrations.restore_current_migration_graph") as restore,
    ):
        connection.alias = "default"
        call_command.side_effect = record_flush
        restore.side_effect = record_restore

        result = flush_then_restore_current_migration_graph()

    assert result is executor
    assert events == ["flush", "restore"]
    assert call_command.call_args == call(
        "flush",
        verbosity=0,
        interactive=False,
        database="default",
        reset_sequences=False,
        allow_cascade=True,
        inhibit_post_migrate=True,
    )


def test_restore_is_still_attempted_when_historical_flush_fails() -> None:
    flush_error = RuntimeError("synthetic historical flush failure")
    restore = Mock()

    with (
        patch("tests.support.migrations.connection"),
        patch(
            "tests.support.migrations.call_command",
            side_effect=flush_error,
        ),
        patch(
            "tests.support.migrations.restore_current_migration_graph",
            restore,
        ),
        pytest.raises(RuntimeError, match="synthetic historical flush failure"),
    ):
        flush_then_restore_current_migration_graph()

    restore.assert_called_once_with()
