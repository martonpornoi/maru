"""Mocked real-scanner lifecycle and pure health parsing, never native scan evidence."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_scanner as scanner
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)

RUN = "1234567890abcdef1234567890abcdef"
OWNER = "b" * 32
CONTAINER = "c" * 64
NETWORK = "d" * 64
NAME = f"maru-programme-scanner-{RUN}"
REQUEST = SimpleNamespace(run_id=RUN, lease_seconds=600)


def network(*, containers=()):
    return {
        "Id": NETWORK,
        "Name": NAME + "-network",
        "Driver": "bridge",
        "Internal": True,
        "Scope": "local",
        "Labels": {scanner._LABEL: RUN, scanner._OWNER: OWNER},
        "Containers": {identifier: {} for identifier in containers},
    }


def container():
    return {
        "id": CONTAINER,
        "name": "/" + NAME,
        "image": scanner.SCANNER_IMAGE,
        "labels": {scanner._LABEL: RUN, scanner._OWNER: OWNER},
        "ports": {
            "3310/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55310"}],
            "7357/tcp": None,
        },
    }


def test_deferred_policy_precedes_any_docker_or_socket(monkeypatch):
    monkeypatch.setattr(
        scanner,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("postgresql_deferred")),
    )
    docker = Mock()
    socket = Mock()
    monkeypatch.setattr(scanner, "_Docker", docker)
    monkeypatch.setattr(scanner.socket, "create_connection", socket)
    with (
        pytest.raises(ProgrammeRehearsalEnvironmentError, match="postgresql_deferred"),
        scanner.isolated_programme_scanner(deadline=700.0),
    ):
        pytest.fail("A deferred scanner must not start.")
    docker.assert_not_called()
    socket.assert_not_called()


@pytest.mark.parametrize("change", ["id", "name", "image", "labels", "nonce"])
def test_container_cleanup_never_adopts_foreign_identity(change):
    value = container()
    if change == "nonce":
        value["labels"][scanner._OWNER] = "foreign"
    else:
        value[change] = None
    with pytest.raises(scanner.ProgrammeScannerError, match="ownership_mismatch"):
        scanner._owned_container(
            value, name=NAME, request=REQUEST, owner=OWNER, identifier=CONTAINER
        )


@pytest.mark.parametrize(
    "change", ["Id", "Name", "Labels", "Internal", "Driver", "Scope", "Containers"]
)
def test_network_cleanup_requires_exact_empty_owned_internal_bridge(change):
    value = network()
    value[change] = None if change != "Containers" else {"foreign": {}}
    with pytest.raises(scanner.ProgrammeScannerError, match="ownership_mismatch"):
        scanner._owned_network(
            value,
            name=NAME + "-network",
            request=REQUEST,
            owner=OWNER,
            identifier=NETWORK,
        )


@pytest.mark.parametrize(
    "change", ["wildcard", "milter", "extra", "privileged", "missing", "multiple"]
)
def test_port_scope_rejects_extra_or_non_loopback_publication(change):
    value = container()
    if change == "wildcard":
        value["ports"]["3310/tcp"][0]["HostIp"] = "0.0.0.0"  # noqa: S104 - refusal
    elif change == "milter":
        value["ports"]["7357/tcp"] = [{"HostIp": "127.0.0.1", "HostPort": "55311"}]
    elif change == "extra":
        value["ports"]["9999/tcp"] = None
    elif change == "privileged":
        value["ports"]["3310/tcp"][0]["HostPort"] = "443"
    elif change == "missing":
        value["ports"] = {}
    else:
        value["ports"]["3310/tcp"] *= 2
    with pytest.raises(scanner.ProgrammeScannerError, match="port_scope_changed"):
        scanner._port(value)


def test_version_requires_exact_engine_and_recent_real_timestamp():
    now = datetime.now(UTC)
    value = f"ClamAV 1.5.4/28000/{now.strftime('%a %b %d %H:%M:%S %Y')}\0".encode()
    engine, signatures, observed = scanner._version(value)
    assert engine == "1.5.4"
    assert signatures == 28000
    assert observed == now.replace(microsecond=0)
    for invalid in (b"OK\0", value.replace(b"1.5.4", b"1.5.3"), value + b"extra"):
        with pytest.raises(scanner.ProgrammeScannerError, match="version_unavailable"):
            scanner._version(invalid)
    for stale in (
        b"ClamAV 1.5.4/1/Wed Jan 01 00:00:00 2020\0",
        b"ClamAV 1.5.4/1/Thu Jan 01 00:00:00 2099\0",
    ):
        with pytest.raises(scanner.ProgrammeScannerError, match="signatures_stale"):
            scanner._version(stale)


def test_health_reply_is_bounded_complete_and_uses_only_loopback(monkeypatch):
    connection = Mock()
    connection.recv.side_effect = [b"PO", b"NG\0", b""]
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    create = Mock(return_value=connection)
    monkeypatch.setattr(scanner.socket, "create_connection", create)
    monkeypatch.setattr(scanner.time, "monotonic", lambda: 100.0)
    assert scanner._reply(55310, b"zPING\0", deadline=700.0) == b"PONG\0"
    create.assert_called_once_with(("127.0.0.1", 55310), timeout=5.0)
    connection.sendall.assert_called_once_with(b"zPING\0")
    connection.__exit__.assert_called_once()
    connection.recv.side_effect = [b"x" * 1025]
    with pytest.raises(scanner.ProgrammeScannerError, match="health_unavailable"):
        scanner._reply(55310, b"zPING\0", deadline=700.0)
    with pytest.raises(scanner.ProgrammeScannerError, match="command_invalid"):
        scanner._reply(55310, b"zSHUTDOWN\0", deadline=700.0)


@pytest.fixture
def docker_world(monkeypatch):
    monkeypatch.setattr(scanner, "require_programme_rehearsal_request", lambda: REQUEST)
    monkeypatch.setattr(scanner.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(scanner.secrets, "token_hex", lambda _count: OWNER)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    world = SimpleNamespace(
        network=None, container=None, calls=[], version="29.0.0", fail_run=False
    )
    docker = Mock()

    def inspect(_name):
        return world.container

    def call(*arguments, **kwargs):
        world.calls.append((arguments, kwargs))
        output = ""
        if arguments[0] == "context":
            output = "npipe:////./pipe/docker_engine"
        elif arguments[0] == "version":
            output = world.version
        elif arguments[:2] == ("network", "inspect"):
            if world.network is None:
                return SimpleNamespace(
                    returncode=1, stdout="", stderr="network not found"
                )
            output = json.dumps([world.network])
        elif arguments[:2] == ("network", "create"):
            world.network = network()
            output = NETWORK
        elif arguments[0] == "run":
            world.container = container()
            world.network["Containers"] = {CONTAINER: {}}
            if world.fail_run:
                raise RuntimeError("uncertain create result")
            output = CONTAINER
        elif arguments[:2] == ("container", "rm"):
            world.container = None
            world.network["Containers"] = {}
        elif arguments[:2] == ("network", "rm"):
            world.network = None
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    docker.inspect.side_effect = inspect
    docker.call.side_effect = call
    monkeypatch.setattr(scanner, "_Docker", Mock(return_value=docker))
    monkeypatch.setattr(
        scanner, "_ready", Mock(return_value=("1.5.4", 28000, datetime.now(UTC)))
    )
    world.docker = docker
    return world


def test_owned_daemon_uses_pinned_image_restricted_resources_and_ordered_cleanup(
    docker_world,
):
    world = docker_world
    with scanner.isolated_programme_scanner(deadline=700.0) as lease:
        assert lease.container_id == CONTAINER
        assert lease.network_id == NETWORK
        assert (
            lease.runtime_environment()["MARU_PROGRAMME_FILE_SCANNER_HOST"]
            == "127.0.0.1"
        )
        arguments, kwargs = next(call for call in world.calls if call[0][0] == "run")
        for flag, value in (
            ("--pull", "never"),
            ("--publish", "127.0.0.1::3310"),
            ("--network", NETWORK),
            ("--user", "clamav"),
            ("--memory", "4g"),
            ("--cap-drop", "ALL"),
            ("--log-driver", "none"),
        ):
            assert arguments[arguments.index(flag) + 1] == value
        assert scanner.SCANNER_IMAGE in arguments
        assert "--read-only" in arguments
        assert "--volume" not in arguments
        assert "--mount" not in arguments
        assert kwargs["timeout"] == 120
    removals = [args for args, _ in world.calls if len(args) > 1 and args[1] == "rm"]
    assert removals == [
        ("container", "rm", "--force", CONTAINER),
        ("network", "rm", NETWORK),
    ]
    assert world.network is None
    assert world.container is None


def test_uncertain_container_start_cleans_only_nonce_verified_resources(docker_world):
    docker_world.fail_run = True
    with (
        pytest.raises(RuntimeError, match="uncertain create result"),
        scanner.isolated_programme_scanner(deadline=700.0),
    ):
        pytest.fail("An uncertain scanner must not yield.")
    assert docker_world.network is None
    assert docker_world.container is None


def test_old_docker_refuses_before_any_resource_creation(docker_world):
    docker_world.version = "27.5.0"
    with (
        pytest.raises(scanner.ProgrammeScannerError, match="version_unsupported"),
        scanner.isolated_programme_scanner(deadline=700.0),
    ):
        pytest.fail("An unsafe loopback publication must not start.")
    assert all(args[0] not in {"run", "network"} for args, _ in docker_world.calls)
