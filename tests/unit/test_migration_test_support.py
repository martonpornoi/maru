"""Unit contracts for historical-migration test cleanup."""

from unittest.mock import Mock, call, patch

import pytest

from tests.support.migrations import (
    flush_then_restore_current_migration_graph,
    identity_migration_targets,
    registration_migration_targets,
    workforce_migration_targets,
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


@pytest.mark.parametrize(
    ("target", "forward_plan", "expected_applications"),
    [
        (
            ("identity", "0018_invitation_retention_v8"),
            (("identity", "0018_invitation_retention_v8"),),
            ("applications", "0004_programme_calls_and_proposals"),
        ),
        (
            ("identity", "0020_programme_proposal_person_guard"),
            (("identity", "0020_programme_proposal_person_guard"),),
            ("applications", "0006_programme_populated_downgrade_fence"),
        ),
    ],
)
def test_identity_history_selects_a_compatible_applications_leaf(
    target: tuple[str, str],
    forward_plan: tuple[tuple[str, str], ...],
    expected_applications: tuple[str, str],
) -> None:
    executor = Mock()
    executor.loader.graph.leaf_nodes.return_value = (
        ("applications", "0006_programme_populated_downgrade_fence"),
        ("identity", "0020_programme_proposal_person_guard"),
        ("other", "0002_current"),
    )
    executor.loader.graph.forwards_plan.return_value = forward_plan

    assert identity_migration_targets(executor, target) == (
        expected_applications,
        target,
        ("other", "0002_current"),
    )
    executor.loader.graph.forwards_plan.assert_called_once_with(target)


@pytest.mark.parametrize(
    ("target", "forward_plan", "expected_applications"),
    [
        (
            ("workforce", "0007_structure_write_integrity"),
            (("workforce", "0007_structure_write_integrity"),),
            ("applications", None),
        ),
        (
            ("workforce", "0008_department_fk_contract_successor"),
            (
                ("workforce", "0007_structure_write_integrity"),
                ("workforce", "0008_department_fk_contract_successor"),
            ),
            ("applications", "0003_integrity_function_execute_boundary"),
        ),
    ],
)
def test_workforce_history_removes_later_programme_call_schema(
    target: tuple[str, str],
    forward_plan: tuple[tuple[str, str], ...],
    expected_applications: tuple[str, str | None],
) -> None:
    executor = Mock()
    executor.loader.graph.forwards_plan.return_value = forward_plan

    assert workforce_migration_targets(
        executor,
        ("authorization", "0010_retired_department_authority_guards"),
        target,
    ) == (
        expected_applications,
        ("authorization", "0010_retired_department_authority_guards"),
        target,
    )
    executor.loader.graph.forwards_plan.assert_called_once_with(target)


def test_current_workforce_and_non_workforce_targets_are_unchanged() -> None:
    executor = Mock()
    current = ("workforce", "0016_programme_call_department_fk_contract")
    executor.loader.graph.forwards_plan.return_value = (current,)

    assert workforce_migration_targets(executor, current) == (current,)
    executor.loader.graph.forwards_plan.assert_called_once_with(current)

    executor.reset_mock()
    authorization = ("authorization", "0010_retired_department_authority_guards")
    assert workforce_migration_targets(executor, authorization) == (authorization,)
    executor.loader.graph.forwards_plan.assert_not_called()


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
