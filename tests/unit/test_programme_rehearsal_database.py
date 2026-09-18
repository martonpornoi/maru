"""Mocked Docker transport tests, never native expiry, role or database proof."""

import copy
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_database as database
from tests.rehearsals import programme_runtime_environment as environment

RUN_ID = "1234567890abcdef1234567890abcdef"
CONTAINER_ID = "a" * 64
OWNER = "b" * 32


class DockerDouble:
    def __init__(self):
        self.calls = []
        self.created = False
        self.start_error = None
        self.returned_id = CONTAINER_ID
        self.endpoint = "npipe:////./pipe/dockerDesktopLinuxEngine"
        self.ready = True
        self.remove = True
        self.value = {
            "id": CONTAINER_ID,
            "name": f"/maru-programme-{RUN_ID}",
            "image": database.POSTGRES_IMAGE,
            "labels": {database.LABEL: RUN_ID, database.OWNER_LABEL: OWNER},
            "ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55432"}]},
        }

    def inspect(self, name):
        self.calls.append(("inspect", name))
        return copy.deepcopy(self.value) if self.created else None

    def call(self, *args, **kwargs):
        self.calls.append(args)
        if args[0] == "context":
            return SimpleNamespace(stdout=self.endpoint, returncode=0)
        if args[0] == "run":
            assert "synthetic-password" not in args
            assert kwargs["environment"]["POSTGRES_PASSWORD"] == "synthetic-password"
            self.created = True
            if self.start_error:
                raise self.start_error
            return SimpleNamespace(stdout=self.returned_id, returncode=0)
        if args[0] == "exec":
            return SimpleNamespace(stdout="", returncode=0 if self.ready else 1)
        assert args == ("container", "rm", "--force", CONTAINER_ID)
        if self.remove:
            self.created = False
        return SimpleNamespace(stdout="", returncode=0 if self.remove else 1)


@pytest.fixture
def docker(monkeypatch):
    value = DockerDouble()
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(database, "_Docker", lambda: value)
    monkeypatch.setattr(
        database.secrets, "token_urlsafe", lambda _size: "synthetic-password"
    )
    monkeypatch.setattr(database.secrets, "token_hex", lambda _size: OWNER)
    monkeypatch.setattr(
        database,
        "require_programme_rehearsal_request",
        lambda: environment.ProgrammeRehearsalRequest(RUN_ID, 1800),
    )
    return value


def removals(docker):
    return [call for call in docker.calls if call[:2] == ("container", "rm")]


def test_policy_denial_happens_before_docker_discovery(monkeypatch):
    monkeypatch.setattr(
        environment.ci_development_policy,
        "postgresql_policy_mode",
        Mock(return_value="deferred"),
    )
    factory = Mock(side_effect=AssertionError("Docker must not be discovered"))
    monkeypatch.setattr(database, "_Docker", factory)
    with (
        pytest.raises(environment.ProgrammeRehearsalEnvironmentError, match="deferred"),
        database.isolated_programme_database(),
    ):
        pytest.fail("Deferred execution was admitted")
    factory.assert_not_called()


def test_exact_owned_loopback_start_and_cleanup_without_password_arguments(docker):
    with database.isolated_programme_database() as lease:
        assert lease.container_id == CONTAINER_ID
        assert lease.port == 55432
        assert lease.database_name == f"maru_programme_{RUN_ID}"
        assert lease.admin_password == "synthetic-password"
        assert "synthetic-password" not in repr(lease)
        assert docker.created
    assert not docker.created
    assert removals(docker) == [("container", "rm", "--force", CONTAINER_ID)]
    start = next(call for call in docker.calls if call[0] == "run")
    assert "--rm" in start
    assert start[start.index("--pull") + 1] == "never"
    assert "127.0.0.1::5432" in start
    assert f"{database.OWNER_LABEL}={OWNER}" in start
    assert "POSTGRES_PASSWORD" in start
    assert "MARU_FIXTURE_LEASE_SECONDS=1800" in start
    assert database.POSTGRES_IMAGE in start
    assert any("type=tmpfs" in argument for argument in start)
    assert "--volume" not in start


def test_expiry_supervisor_uses_fast_shutdown_then_bounded_child_kill():
    assert 'sleep "$MARU_FIXTURE_LEASE_SECONDS"' in database._LEASE_COMMAND
    assert 'kill -INT "$server_pid"' in database._LEASE_COMMAND
    assert "sleep 10" in database._LEASE_COMMAND
    assert 'kill -KILL "$server_pid"' in database._LEASE_COMMAND
    assert 'wait "$server_pid"' in database._LEASE_COMMAND
    assert "kill -TERM 1" not in database._LEASE_COMMAND


def test_existing_name_is_never_adopted_or_removed(docker):
    docker.created = True
    with (
        pytest.raises(database.ProgrammeDatabaseError, match="existing_container"),
        database.isolated_programme_database(),
    ):
        pytest.fail("Existing database admitted")
    assert not removals(docker)
    assert not any(call[0] == "run" for call in docker.calls)


def test_uncertain_startup_cleans_only_its_unique_ownership_nonce(docker):
    docker.start_error = database.ProgrammeDatabaseError("docker_operation_unavailable")
    with (
        pytest.raises(database.ProgrammeDatabaseError, match="operation_unavailable"),
        database.isolated_programme_database(),
    ):
        pytest.fail("Failed startup admitted")
    assert removals(docker)
    assert not docker.created


def test_uncertain_start_cannot_remove_concurrent_same_run_different_owner(docker):
    docker.start_error = database.ProgrammeDatabaseError("docker_operation_unavailable")
    docker.value["labels"][database.OWNER_LABEL] = "c" * 32
    with (
        pytest.raises(database.ProgrammeDatabaseError, match="ownership_mismatch"),
        database.isolated_programme_database(),
    ):
        pytest.fail("Foreign resource admitted")
    assert not removals(docker)
    assert docker.created


def test_bad_start_response_still_cleans_exact_owned_resource(docker):
    docker.returned_id = "private-invalid-output"
    with (
        pytest.raises(database.ProgrammeDatabaseError) as caught,
        database.isolated_programme_database(),
    ):
        pytest.fail("Invalid response admitted")
    assert str(caught.value) == "invalid_container_identity"
    assert removals(docker)


@pytest.mark.parametrize(
    "change",
    [
        {"id": "c" * 64},
        {"id": "short"},
        {"name": "/other"},
        {"labels": {}},
        {"labels": {database.LABEL: "foreign", database.OWNER_LABEL: OWNER}},
        {"image": "postgres:latest"},
    ],
)
def test_changed_identity_is_not_removed_even_during_failure(change, docker):
    docker.value.update(change)
    with (
        pytest.raises(database.ProgrammeDatabaseError, match="ownership_mismatch"),
        database.isolated_programme_database(),
    ):
        pytest.fail("Changed resource admitted")
    assert not removals(docker)


def test_body_failure_still_cleans_exact_container(docker):
    with (
        pytest.raises(ValueError, match="synthetic journey failure"),
        database.isolated_programme_database(),
    ):
        raise ValueError("synthetic journey failure")
    assert removals(docker)


def test_expired_auto_removed_container_needs_no_second_delete(docker):
    with database.isolated_programme_database():
        docker.created = False
    assert not removals(docker)


def test_failed_cleanup_is_reported_not_silently_passed(docker):
    docker.remove = False
    with (
        pytest.raises(database.ProgrammeDatabaseError, match="cleanup_incomplete"),
        database.isolated_programme_database(),
    ):
        pass


@pytest.mark.parametrize(
    "endpoint", ["ssh://remote", "tcp://127.0.0.1:2375", "", "unix:relative"]
)
def test_nonlocal_or_ambiguous_daemon_is_refused(endpoint, docker):
    docker.endpoint = endpoint
    with (
        pytest.raises(database.ProgrammeDatabaseError, match="nonlocal_docker"),
        database.isolated_programme_database(),
    ):
        pytest.fail("Unsupported daemon admitted")
    assert not any(call[0] == "run" for call in docker.calls)


def test_host_override_denied_before_any_docker_call(docker, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote")
    with (
        pytest.raises(database.ProgrammeDatabaseError, match="docker_host_override"),
        database.isolated_programme_database(),
    ):
        pytest.fail("Override admitted")
    assert not docker.calls


@pytest.mark.parametrize(
    "ports",
    [
        None,
        {},
        {"5432/tcp": []},
        {"5432/tcp": [{"HostIp": "remote", "HostPort": "55432"}]},
        {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "invalid"}]},
    ],
)
def test_bad_port_projection_fails_and_cleans_owned_container(ports, docker):
    docker.value["ports"] = ports
    with (
        pytest.raises(database.ProgrammeDatabaseError, match="invalid_database_port"),
        database.isolated_programme_database(),
    ):
        pytest.fail("Invalid binding admitted")
    assert removals(docker)


def test_startup_deadline_cleans_owned_container(docker, monkeypatch):
    docker.ready = False
    monkeypatch.setattr(
        database,
        "time",
        SimpleNamespace(monotonic=Mock(side_effect=[0, 0, 61]), sleep=Mock()),
    )
    with (
        pytest.raises(database.ProgrammeDatabaseError, match="startup_timeout"),
        database.isolated_programme_database(),
    ):
        pytest.fail("Unready database admitted")
    assert removals(docker)


@pytest.mark.parametrize(
    "error",
    [OSError("private-output"), subprocess.TimeoutExpired("private-command", 5)],
)
def test_transport_failures_do_not_disclose_raw_docker_details(error, monkeypatch):
    monkeypatch.setattr(database.shutil, "which", lambda _name: "verified-docker")
    monkeypatch.setattr(database.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(database.ProgrammeDatabaseError) as caught:
        database._Docker().call("version")
    assert str(caught.value) == "docker_operation_unavailable"
    assert "private" not in repr(caught.value)


def test_missing_executable_never_invokes_subprocess(monkeypatch):
    monkeypatch.setattr(database.shutil, "which", lambda _name: None)
    execute = Mock()
    monkeypatch.setattr(database.subprocess, "run", execute)
    with pytest.raises(database.ProgrammeDatabaseError, match="docker_unavailable"):
        database._Docker()
    execute.assert_not_called()


@pytest.mark.parametrize("output", ["not-json", "[]", "null"])
def test_inspection_rejects_malformed_transport_output(output, monkeypatch):
    monkeypatch.setattr(database.shutil, "which", lambda _name: "verified-docker")
    monkeypatch.setattr(
        database.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=0, stdout=output, stderr="")),
    )
    with pytest.raises(
        database.ProgrammeDatabaseError, match="invalid_container_inspection"
    ):
        database._Docker().inspect(CONTAINER_ID)


@pytest.mark.parametrize(
    "message",
    ["Error: No such container: synthetic", "Error: No such object: synthetic"],
)
def test_inspection_recognizes_already_removed_resource(message, monkeypatch):
    monkeypatch.setattr(database.shutil, "which", lambda _name: "verified-docker")
    monkeypatch.setattr(
        database.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr=message)),
    )
    assert database._Docker().inspect(CONTAINER_ID) is None


def test_daemon_failure_is_not_misreported_as_absent_container(monkeypatch):
    monkeypatch.setattr(database.shutil, "which", lambda _name: "verified-docker")
    monkeypatch.setattr(
        database.subprocess,
        "run",
        Mock(
            return_value=SimpleNamespace(
                returncode=1, stdout="", stderr="private-daemon-failure"
            )
        ),
    )
    with pytest.raises(
        database.ProgrammeDatabaseError, match="container_inspection_unavailable"
    ):
        database._Docker().inspect(CONTAINER_ID)
