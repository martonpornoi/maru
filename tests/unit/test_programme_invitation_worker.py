"""Database-free worker ordering; no manufactured scheduler or native evidence."""

from types import SimpleNamespace
from unittest.mock import Mock

import django
import django.core.management
import django.db
import pytest

from maru.authorization import database_role_safety
from maru.identity import invitation_key_config
from tests.rehearsals import (
    programme_compatibility,
    programme_effects,
    programme_runtime,
    programme_runtime_privileges,
)
from tests.rehearsals import programme_invitation_worker as worker
from tests.rehearsals.programme_provisioning import ProgrammeProvisioningError
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)


@pytest.fixture
def cycle(monkeypatch):
    environment = SimpleNamespace(database_name="synthetic")
    boundary = Mock(return_value=environment)
    monkeypatch.setattr(worker, "require_programme_runtime_environment", boundary)
    monkeypatch.setenv(
        "DJANGO_SETTINGS_MODULE", "tests.rehearsals.programme_runtime_settings"
    )
    monkeypatch.setenv(worker.PRIVATE_KEYS_ENV, "synthetic-worker-only")
    monkeypatch.delenv(worker.ADMIN_PASSWORD_ENV, raising=False)
    monkeypatch.delenv("MARU_PROGRAMME_REHEARSAL_BOOTSTRAP", raising=False)
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    cursor.fetchone.return_value = ("synthetic", "maru_runtime", "maru_runtime")
    monkeypatch.setattr(
        django.db, "connection", SimpleNamespace(cursor=Mock(return_value=cursor))
    )
    ordered = Mock()
    mappings = (
        (django, "setup", "setup"),
        (programme_runtime, "_runtime_configuration_is_strict", "strict"),
        (
            programme_runtime_privileges,
            "install_isolated_candidate_privilege_contract",
            "privileges",
        ),
        (programme_effects, "install_isolated_candidate_handlers", "handlers"),
        (programme_compatibility, "check_isolated_candidate", "checks"),
        (
            programme_runtime_privileges,
            "require_candidate_reference_boundary",
            "references",
        ),
        (database_role_safety, "probe_runtime_database_role_safety", "probe"),
        (invitation_key_config, "worker_invitation_private_keyring", "private"),
        (invitation_key_config, "active_invitation_encryption_key", "public"),
        (django.core.management, "call_command", "command"),
        (programme_runtime, "_require_native_readiness", "readiness"),
    )
    for module, name, alias in mappings:
        command = Mock()
        monkeypatch.setattr(module, name, command)
        ordered.attach_mock(command, alias)
    ordered.strict.return_value = True
    ordered.checks.return_value = ("one", "two", "three")
    ordered.probe.return_value = SimpleNamespace(current_session_is_safe=True)
    ordered.private.return_value = SimpleNamespace(matches=Mock(return_value=True))
    return SimpleNamespace(
        environment=environment, boundary=boundary, cursor=cursor, ordered=ordered
    )


def test_real_command_dispatch_follows_checks_and_precedes_full_readiness(cycle):
    assert worker.run_invitation_worker_cycle() == ("one", "two", "three")
    assert [call[0] for call in cycle.ordered.mock_calls] == [
        "setup",
        "strict",
        "privileges",
        "handlers",
        "checks",
        "references",
        "probe",
        "private",
        "public",
        "command",
        "command",
        "command",
        "readiness",
    ]
    cycle.ordered.probe.assert_called_once_with(role_name="maru_runtime")
    cycle.ordered.references.assert_called_once_with(cycle.cursor)
    cycle.ordered.readiness.assert_called_once_with(cycle.environment)
    assert [call.args for call in cycle.ordered.command.call_args_list] == [
        ("platform_invitation_delivery",),
        ("expire_platform_account_invitations",),
        ("run_platform_invitation_retention",),
    ]
    for index, call in enumerate(cycle.ordered.command.call_args_list):
        expected = "delivery_limit" if index == 0 else "limit"
        assert set(call.kwargs) == {expected, "stdout", "stderr"}
        assert call.kwargs[expected] == 100
        assert call.kwargs["stdout"].getvalue() == ""
    # The orchestration reads identity; only actual owners record heartbeat data.
    cycle.cursor.execute.assert_called_once_with(
        "SELECT current_database(), session_user, current_user"
    )


def test_policy_refuses_before_django_or_worker_calls(cycle):
    cycle.boundary.side_effect = ProgrammeRehearsalEnvironmentError("deferred")
    with pytest.raises(ProgrammeRehearsalEnvironmentError):
        worker.run_invitation_worker_cycle()
    assert not cycle.ordered.mock_calls


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DJANGO_SETTINGS_MODULE", "maru.settings.test"),
        (worker.ADMIN_PASSWORD_ENV, ""),
        ("MARU_PROGRAMME_REHEARSAL_BOOTSTRAP", "foundation-v1"),
        (worker.PRIVATE_KEYS_ENV, ""),
    ],
)
def test_wrong_process_secret_or_settings_refuse_before_setup(
    cycle, monkeypatch, name, value
):
    monkeypatch.setenv(name, value)
    with pytest.raises(ProgrammeProvisioningError, match="environment_invalid"):
        worker.run_invitation_worker_cycle()
    assert not cycle.ordered.mock_calls


@pytest.mark.parametrize(
    "stage", ["strict", "checks", "identity", "references", "probe", "keys"]
)
def test_preflight_refusal_never_dispatches_workers(cycle, stage):
    if stage == "strict":
        cycle.ordered.strict.return_value = False
    elif stage == "checks":
        cycle.ordered.checks.side_effect = RuntimeError("unknown check")
    elif stage == "identity":
        cycle.cursor.fetchone.return_value = ("foreign", "postgres", "postgres")
    elif stage == "references":
        cycle.ordered.references.side_effect = RuntimeError("unsafe references")
    elif stage == "probe":
        cycle.ordered.probe.return_value.current_session_is_safe = False
    else:
        cycle.ordered.private.return_value.matches.return_value = False
    with pytest.raises(RuntimeError):
        worker.run_invitation_worker_cycle()
    cycle.ordered.command.assert_not_called()
    cycle.ordered.readiness.assert_not_called()


@pytest.mark.parametrize("failed_command", [0, 1, 2])
def test_worker_failure_does_not_manufacture_readiness(cycle, failed_command):
    cycle.ordered.command.side_effect = [None] * failed_command + [
        RuntimeError("failed")
    ]
    with pytest.raises(RuntimeError, match="failed"):
        worker.run_invitation_worker_cycle()
    assert cycle.ordered.command.call_count == failed_command + 1
    cycle.ordered.readiness.assert_not_called()


def test_unready_native_postcondition_cannot_return_success(cycle):
    cycle.ordered.readiness.side_effect = RuntimeError("not ready")
    with pytest.raises(RuntimeError, match="not ready"):
        worker.run_invitation_worker_cycle()
    assert cycle.ordered.command.call_count == 3
