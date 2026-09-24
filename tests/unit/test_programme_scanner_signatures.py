"""Explicit signature refresh and exact resource ownership, without networking."""

import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_scanner_signatures as signatures

RUN = "a" * 32
OWNER = "b" * 32
NAME = "maru-programme-signatures-" + RUN
IMAGE = "clamav/clamav@sha256:" + "c" * 64


def volume():
    return {
        "Name": NAME,
        "Driver": "local",
        "Scope": "local",
        "Options": None,
        "Labels": {signatures._RUN: RUN, signatures._OWNER: OWNER},
    }


def scope(docker):
    return signatures.refreshed_signatures(
        docker,
        image=IMAGE,
        run_id=RUN,
        owner=OWNER,
        deadline=time.monotonic() + 300,
    )


def test_absent_opt_in_never_contacts_docker(monkeypatch):
    monkeypatch.delenv("MARU_PROGRAMME_SCANNER_REFRESH", raising=False)
    docker = Mock()
    with scope(docker) as result:
        assert result is None
    assert not docker.mock_calls


@pytest.mark.parametrize(
    "choice", ["yes", "true", "production", " isolated", "ISOLATED"]
)
def test_invalid_opt_in_refuses_before_resources(monkeypatch, choice):
    monkeypatch.setenv("MARU_PROGRAMME_SCANNER_REFRESH", choice)
    docker = Mock()
    with (
        pytest.raises(signatures.ScannerSignatureError, match="opt_in_invalid"),
        scope(docker),
    ):
        pytest.fail("Invalid refresh must not yield.")
    assert not docker.mock_calls


@pytest.mark.parametrize("key", ["Name", "Driver", "Scope", "Options", "Labels"])
def test_volume_never_adopts_foreign_or_host_mount_options(key):
    value = volume()
    value[key] = {"device": "/private"} if key == "Options" else "foreign"
    with pytest.raises(signatures.ScannerSignatureError, match="ownership_changed"):
        signatures._owned_volume(value, name=NAME, run_id=RUN, owner=OWNER)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_SCANNER_REFRESH", "isolated")
    state = SimpleNamespace(volume=None, updater=None, calls=[], fail=False)
    docker = Mock()

    def call(*args, **kwargs):
        state.calls.append((args, kwargs))
        if args[:2] == ("volume", "inspect"):
            return SimpleNamespace(
                returncode=int(state.volume is None),
                stdout=json.dumps([state.volume]),
                stderr="no such volume",
            )
        if args[:2] == ("volume", "create"):
            state.volume = volume()
        elif args[:2] == ("volume", "rm"):
            state.volume = None
        elif args[:2] == ("container", "rm"):
            state.updater = None
        elif args[0] == "run" and state.fail:
            state.updater = {
                "id": "d" * 64,
                "name": "/" + NAME + "-updater",
                "image": IMAGE,
                "labels": {signatures._RUN: RUN, signatures._OWNER: OWNER},
            }
            raise RuntimeError("uncertain updater completion")
        return SimpleNamespace(returncode=0, stdout=NAME, stderr="")

    docker.call.side_effect = call
    docker.inspect.side_effect = lambda _name: state.updater
    state.docker = docker
    return state


def test_refresh_has_only_public_volume_bounded_updater_and_exact_cleanup(world):
    with scope(world.docker) as result:
        assert result == NAME
        assert world.volume is not None
        args, kwargs = next(item for item in world.calls if item[0][0] == "run")
        assert (
            args[args.index("--mount") + 1]
            == f"type=volume,source={NAME},target=/var/lib/clamav"
        )
        for key, value in (
            ("--user", "clamav"),
            ("--network", "bridge"),
            ("--pull", "never"),
            ("--cap-drop", "ALL"),
        ):
            assert args[args.index(key) + 1] == value
        assert "--publish" not in args
        assert "--read-only" in args
        assert IMAGE in args
        assert args[-1] == "timeout 180 freshclam --stdout >/dev/null 2>&1"
        assert kwargs["timeout"] <= 190
        assert world.updater is None
    assert world.volume is None
    assert ("volume", "rm", NAME) in [args for args, _kwargs in world.calls]


def test_uncertain_update_cleans_only_verified_updater_before_its_volume(world):
    world.fail = True
    with pytest.raises(RuntimeError, match="uncertain"), scope(world.docker):
        pytest.fail("Uncertain update must not yield.")
    removed = [
        args for args, _kwargs in world.calls if len(args) > 1 and args[1] == "rm"
    ]
    assert removed == [("container", "rm", "--force", "d" * 64), ("volume", "rm", NAME)]
    assert world.volume is world.updater is None


def test_preexisting_volume_is_never_adopted_or_removed(world):
    world.volume = volume()
    with (
        pytest.raises(signatures.ScannerSignatureError, match="already_exist"),
        scope(world.docker),
    ):
        pytest.fail("Existing resources must not be adopted.")
    assert world.volume is not None
    assert all(args[:2] == ("volume", "inspect") for args, _kwargs in world.calls)


def test_changed_volume_ownership_prevents_cleanup(world):
    with (
        pytest.raises(signatures.ScannerSignatureError, match="ownership_changed"),
        scope(world.docker),
    ):
        world.volume["Labels"][signatures._OWNER] = "foreign"
    assert world.volume is not None
    assert not any(args[:2] == ("volume", "rm") for args, _kwargs in world.calls)
