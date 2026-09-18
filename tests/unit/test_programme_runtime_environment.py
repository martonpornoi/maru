"""Pure startup-fence tests; never native runner, database or ownership proof."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_runtime_environment as runtime

RUN_ID = "1234567890abcdef1234567890abcdef"
DATABASE = f"maru_programme_{RUN_ID}"
URI = f"postgresql://maru_runtime:synthetic-secret@127.0.0.1:55432/{DATABASE}"


@pytest.fixture
def environment(monkeypatch):
    for key in runtime._LIBPQ_OVERRIDES:
        monkeypatch.delenv(key, raising=False)
    values = {
        "MARU_PROGRAMME_REHEARSAL": "isolated",
        "MARU_PROGRAMME_REHEARSAL_RUN_ID": RUN_ID,
        "MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS": "1800",
        "MARU_RUNTIME_DATABASE_ROLE": "maru_runtime",
        "MARU_DATABASE_URL": URI,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    policy = Mock(return_value="required")
    monkeypatch.setattr(runtime.ci_development_policy, "postgresql_policy_mode", policy)
    return policy


def test_valid_configuration_is_immutable_and_credential_is_not_in_repr(environment):
    result = runtime.require_programme_runtime_environment()
    assert result.run_id == RUN_ID
    assert result.database_name == DATABASE
    assert result.port == 55432
    assert result.lease_seconds == 1800
    assert result.database_url == URI
    assert "synthetic-secret" not in repr(result)
    assert "postgresql://" not in repr(result)
    environment.assert_called_once_with()
    with pytest.raises(FrozenInstanceError):
        result.lease_seconds = 7200


@pytest.mark.parametrize("mode", ["deferred", "unknown", None])
def test_policy_is_checked_before_any_environment_or_connection_input(
    mode, monkeypatch
):
    monkeypatch.setattr(
        runtime.ci_development_policy, "postgresql_policy_mode", Mock(return_value=mode)
    )
    environ = Mock()
    monkeypatch.setattr(runtime, "os", SimpleNamespace(environ=environ))
    with pytest.raises(runtime.ProgrammeRehearsalEnvironmentError, match="deferred"):
        runtime.require_programme_runtime_environment()
    assert not environ.mock_calls


@pytest.mark.parametrize("error", [OSError, ValueError, UnicodeError])
def test_bad_policy_is_non_disclosing_and_never_falls_back(error, monkeypatch):
    monkeypatch.setattr(
        runtime.ci_development_policy,
        "postgresql_policy_mode",
        Mock(side_effect=error("private-path-or-secret")),
    )
    with pytest.raises(runtime.ProgrammeRehearsalEnvironmentError) as caught:
        runtime.require_programme_runtime_environment()
    assert str(caught.value) == "policy_unavailable"
    assert "private" not in repr(caught.value)


@pytest.mark.parametrize("value", ["", "1", "true", "ISOLATED", " isolated"])
def test_opt_in_is_explicit_and_exact(value, environment, monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL", value)
    with pytest.raises(runtime.ProgrammeRehearsalEnvironmentError, match="opt_in"):
        runtime.require_programme_runtime_environment()


@pytest.mark.parametrize("value", ["", "0" * 32, "a" * 31, "g" * 32, RUN_ID.upper()])
def test_run_identity_is_nonempty_canonical_and_bounded(
    value, environment, monkeypatch
):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", value)
    with pytest.raises(
        runtime.ProgrammeRehearsalEnvironmentError, match="run_identity"
    ):
        runtime.require_programme_runtime_environment()


@pytest.mark.parametrize(
    "seconds", ["", "0", "59", "3601", "060", "60.0", "-60", " 60"]
)
def test_lease_requires_canonical_bounded_seconds(seconds, environment, monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", seconds)
    with pytest.raises(
        runtime.ProgrammeRehearsalEnvironmentError, match="invalid_lease"
    ):
        runtime.require_programme_runtime_environment()


@pytest.mark.parametrize("seconds", ["60", "3600"])
def test_lease_accepts_both_bounds(seconds, environment, monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", seconds)
    assert runtime.require_programme_runtime_environment().lease_seconds == int(seconds)


@pytest.mark.parametrize("key", runtime._LIBPQ_OVERRIDES)
def test_ambient_libpq_overrides_are_not_inherited(key, environment, monkeypatch):
    monkeypatch.setenv(key, "synthetic-private-value")
    with pytest.raises(runtime.ProgrammeRehearsalEnvironmentError) as caught:
        runtime.require_programme_runtime_environment()
    assert str(caught.value) == "ambient_database_override"
    assert "synthetic-private-value" not in repr(caught.value)


@pytest.mark.parametrize(
    "uri",
    [
        "",
        URI + "?host=remote.example.invalid",
        URI + "#fragment",
        URI + "/other",
        URI.replace(DATABASE, "maru"),
        URI.replace(DATABASE, "maru_programme_" + "f" * 32),
        URI.replace("127.0.0.1", "remote.example.invalid"),
        URI.replace("127.0.0.1", "localhost"),
        URI.replace("127.0.0.1", "0.0.0.0"),  # noqa: S104 - rejected input, no bind
        URI.replace("127.0.0.1", "[::1]"),
        URI.replace("55432", "0"),
        URI.replace("55432", "65536"),
        URI.replace("55432", "secret-not-a-port"),
        URI.replace(":55432", ""),
        URI.replace("postgresql:", "postgres:"),
        URI.replace("maru_runtime:", "postgres:"),
        URI.replace("synthetic-secret", ""),
        URI.replace("synthetic-secret", "password with spaces"),
        "\n" + URI,
        URI + "\n",
    ],
)
def test_connection_is_exact_run_loopback_runtime_only(uri, environment, monkeypatch):
    monkeypatch.setenv("MARU_DATABASE_URL", uri)
    with pytest.raises(runtime.ProgrammeRehearsalEnvironmentError) as caught:
        runtime.require_programme_runtime_environment()
    assert str(caught.value) == "invalid_database_scope"
    assert "secret" not in repr(caught.value)


@pytest.mark.parametrize("role", ["", "postgres", "maru_migration", "MARU_RUNTIME"])
def test_declared_runtime_role_must_agree(role, environment, monkeypatch):
    monkeypatch.setenv("MARU_RUNTIME_DATABASE_ROLE", role)
    with pytest.raises(
        runtime.ProgrammeRehearsalEnvironmentError, match="database_scope"
    ):
        runtime.require_programme_runtime_environment()
