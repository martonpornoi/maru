"""Database-free inventory failure contracts, not native isolation acceptance."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import psycopg
import pytest

from tests.rehearsals import programme_excluded_state as inventory
from tests.rehearsals.programme_runtime_environment import ProgrammeRuntimeEnvironment

RUN = "1234567890abcdef1234567890abcdef"


def test_inventory_covers_all_excluded_owners_and_no_adopted_owner(monkeypatch):
    tables = inventory.excluded_tables()
    assert len(tables) == 97
    assert {table.split("_", 1)[0] for table in tables} == set(
        inventory.EXCLUDED_OWNERS
    )
    assert tuple(sorted(set(tables))) == tables
    monkeypatch.setattr(inventory, "MODULES", (*inventory.MODULES, "registration"))
    with pytest.raises(
        inventory.ProgrammeExcludedStateError, match="owner_was_adopted"
    ):
        inventory.excluded_tables()


@pytest.fixture
def native_seam(monkeypatch):
    runtime = ProgrammeRuntimeEnvironment(
        RUN, "maru_programme_" + RUN, 54321, 3600, "synthetic-private-uri"
    )
    monkeypatch.setattr(
        inventory,
        "require_programme_rehearsal_request",
        lambda: SimpleNamespace(run_id=RUN),
    )
    monkeypatch.setattr(inventory, "excluded_tables", lambda: ("registration_fixture",))
    connection = MagicMock()
    execute = connection.execute
    execute.side_effect = [
        Mock(),
        Mock(fetchone=lambda: (runtime.database_name, "maru_runtime", "maru_runtime")),
        Mock(fetchall=lambda: [("registration_fixture",)]),
        Mock(fetchone=lambda: (False, False)),
        Mock(fetchone=lambda: (False, False)),
        Mock(fetchone=lambda: (2, "a" * 64)),
    ]
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(inventory.psycopg, "connect", connect)
    return runtime, connection, connect


def test_snapshot_is_read_only_bounded_private_and_bound_to_actual_runtime(native_seam):
    runtime, connection, connect = native_seam
    result = inventory.capture_excluded_state(runtime)
    assert result.tables == (("registration_fixture", 2, "a" * 64),)
    assert "registration_fixture" not in repr(result)
    assert connection.execute.call_args_list[0].args == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
    )
    assert connection.execute.call_args_list[-1].args[1] == [10_001]
    assert connect.call_args.kwargs["connect_timeout"] == 5
    assert "statement_timeout=5000" in connect.call_args.kwargs["options"]


@pytest.mark.parametrize("fault", ["session", "inventory", "effect", "authority"])
def test_native_inventory_refuses_bad_identity_inventory_effect_or_authority(
    native_seam, fault
):
    runtime, connection, _connect = native_seam
    results = list(connection.execute.side_effect)
    index = {"session": 1, "inventory": 2, "effect": 3, "authority": 4}[fault]
    results[index] = Mock(fetchone=lambda: (True, False), fetchall=list)
    connection.execute.side_effect = results
    with pytest.raises(inventory.ProgrammeExcludedStateError):
        inventory.capture_excluded_state(runtime)


def test_wrong_fixture_never_connects_and_private_database_error_is_redacted(
    native_seam,
):
    runtime, connection, connect = native_seam
    with pytest.raises(inventory.ProgrammeExcludedStateError, match="wrong_fixture"):
        inventory.capture_excluded_state(replace(runtime, run_id="0" * 32))
    connect.assert_not_called()
    connection.execute.side_effect = psycopg.OperationalError(
        "private connection content"
    )
    with pytest.raises(
        inventory.ProgrammeExcludedStateError, match="unavailable"
    ) as error:
        inventory.capture_excluded_state(runtime)
    assert "private" not in str(error.value)


def test_fingerprint_overflow_refuses_instead_of_truncating(native_seam):
    _runtime, connection, _connect = native_seam
    connection.execute.side_effect = None
    connection.execute.return_value.fetchone.return_value = (10_001, "a" * 64)
    with pytest.raises(inventory.ProgrammeExcludedStateError, match="overflow"):
        inventory._fingerprint(connection, "registration_fixture")


@pytest.mark.parametrize("change", ["unchanged", "added", "edited", "removed"])
def test_comparison_retains_original_baseline_and_refuses_every_kind_of_change(
    native_seam, monkeypatch, change
):
    runtime, _connection, _connect = native_seam
    baseline = inventory.ExcludedStateSnapshot(RUN, (("registration_fixture", 2, "a"),))
    tables = {
        "unchanged": baseline.tables,
        "added": (("registration_fixture", 3, "b"),),
        "edited": (("registration_fixture", 2, "b"),),
        "removed": (("registration_fixture", 1, "b"),),
    }[change]
    capture = Mock(return_value=inventory.ExcludedStateSnapshot(RUN, tables))
    monkeypatch.setattr(inventory, "capture_excluded_state", capture)
    if change == "unchanged":
        inventory.verify_excluded_state(runtime, baseline)
    else:
        with pytest.raises(
            inventory.ProgrammeExcludedStateError, match="state_changed"
        ):
            inventory.verify_excluded_state(runtime, baseline)
    assert baseline.tables == (("registration_fixture", 2, "a"),)
    capture.reset_mock()
    with pytest.raises(inventory.ProgrammeExcludedStateError, match="missing_baseline"):
        inventory.verify_excluded_state(runtime, None)
    capture.assert_not_called()
