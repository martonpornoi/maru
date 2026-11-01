from __future__ import annotations

import argparse
import json
import subprocess
from copy import deepcopy
from unittest.mock import Mock

import pytest
from scripts import rehearse_workforce_browser as rehearsal
from scripts import try_maru


def test_explicit_database_image_is_used_without_changing_default(monkeypatch):
    preview = try_maru.Preview("docker", 8766, image=rehearsal.IMAGE)
    command = Mock(
        side_effect=["owned-id", "", "ready", '{"5432/tcp":[{"HostPort":"54399"}]}']
    )
    monkeypatch.setattr(preview, "docker_command", command)
    preview.start_database()
    assert command.call_args_list[0].args[-1] == rehearsal.IMAGE
    assert try_maru.Preview("docker", 8766).image == try_maru.IMAGE


def test_private_directory_cannot_escape_or_reuse_existing_data(tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, "ROOT", tmp_path)
    existing = tmp_path / ".tools" / "preserved"
    existing.mkdir(parents=True)
    marker = existing / "account.private.json"
    marker.write_text("preserved", encoding="utf-8")
    with pytest.raises(FileExistsError):
        rehearsal._directory(existing, create=True)
    for outside in (tmp_path, tmp_path / ".tools", tmp_path / "unrelated"):
        with pytest.raises(RuntimeError, match="new private run"):
            rehearsal._directory(outside, create=True)
    assert marker.read_text(encoding="utf-8") == "preserved"


def test_new_keys_do_not_put_delivery_secret_in_web_environment():
    environment = {}
    first = rehearsal._keys(environment)
    second = rehearsal._keys({})
    assert first != second
    assert rehearsal.PRIVATE_KEY not in environment
    assert "PRIVATE KEY" not in str(environment)
    private_ring = json.loads(first)
    assert list(private_ring) == [
        environment["MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID"]
    ]
    assert (
        json.loads(environment["MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON"])[
            "jurisdiction_code"
        ]
        == "SYNTHETIC"
    )


def test_worker_receives_private_key_only_in_its_own_child(monkeypatch, tmp_path):
    environment = {"MARU_DATABASE_URL": "owned-runtime"}
    run = Mock()
    monkeypatch.setattr(rehearsal, "_run", run)
    rehearsal._worker(tmp_path, environment, "private-ring")
    child = run.call_args.args[1]
    assert child[rehearsal.PRIVATE_KEY] == "private-ring"
    assert child["MARU_WORKFORCE_REHEARSAL_PROCESS"] == "worker"
    assert environment == {"MARU_DATABASE_URL": "owned-runtime"}


def test_private_process_output_is_not_released_on_failure(
    monkeypatch, tmp_path, capsys
):
    def fail(*args, **kwargs):
        kwargs["stdout"].write("secret-connection-string")
        return subprocess.CompletedProcess(args[0], 1)

    monkeypatch.setattr(rehearsal.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="subprocess failed") as caught:
        rehearsal._run(tmp_path, {}, "-m", "scripts.workforce_rehearsal_runtime")
    assert "secret-connection-string" not in str(caught.value)
    assert "secret-connection-string" not in str(capsys.readouterr())
    assert (tmp_path / "process.private.log").read_text(
        encoding="utf-8"
    ) == "secret-connection-string"


@pytest.mark.parametrize("running", [False, True])
def test_check_mode_never_creates_resources_and_refuses_overlap(
    monkeypatch, tmp_path, running
):
    preview = Mock()
    preview.docker_command.return_value = "other-id" if running else ""
    monkeypatch.setattr(rehearsal, "preflight", lambda _: "docker")
    monkeypatch.setattr(rehearsal, "Preview", lambda *_a, **_k: preview)
    args = argparse.Namespace(port=8766, check=True, directory=tmp_path / "not-created")
    if running:
        with pytest.raises(RuntimeError, match="nothing was stopped"):
            rehearsal._start(args)
    else:
        assert rehearsal._start(args) == 0
    preview.start_database.assert_not_called()
    preview.close.assert_not_called()
    assert not args.directory.exists()


def _identity():
    return {
        "Id": "owned-id",
        "Name": "/maru-preview-owned-token",
        "Image": "sha256:actual-image",
        "Config": {"Labels": {try_maru.LABEL: "owned-token"}, "Image": rehearsal.IMAGE},
        "State": {"Running": True},
        "NetworkSettings": {
            "Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "54399"}]}
        },
    }


@pytest.mark.parametrize(
    "alter",
    [
        "id",
        "name",
        "label",
        "image",
        "stopped",
        "public",
        "port",
        "extra_port",
        "owner_login",
    ],
)
def test_inspector_refuses_changed_resource_or_runtime_boundary(alter):
    info = deepcopy(_identity())
    environment = {
        "MARU_DATABASE_URL": "postgresql://maru_runtime:private@127.0.0.1:54399/maru"
    }
    if alter == "id":
        info["Id"] = "foreign"
    elif alter == "name":
        info["Name"] = "/foreign"
    elif alter == "label":
        info["Config"]["Labels"][try_maru.LABEL] = "foreign"
    elif alter == "image":
        info["Config"]["Image"] = "unpinned:latest"
    elif alter == "stopped":
        info["State"]["Running"] = False
    elif alter == "public":
        info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] = "0.0.0.0"  # noqa: S104 -- deliberate unsafe binding rejection
    elif alter == "port":
        info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"] = "54398"
    elif alter == "extra_port":
        info["NetworkSettings"]["Ports"]["9999/tcp"] = []
    else:
        environment["MARU_DATABASE_URL"] = environment["MARU_DATABASE_URL"].replace(
            "maru_runtime", "maru_migration"
        )
    preview = Mock(container="owned-id", token="owned-token", port=8766)
    preview.docker_command.return_value = json.dumps([info])
    with pytest.raises(RuntimeError, match="exact owned database"):
        rehearsal._verify_resource(preview, environment)
    preview.close.assert_not_called()


def test_exact_resource_returns_only_nonsecret_identity():
    preview = Mock(container="owned-id", token="owned-token", port=8766)
    preview.docker_command.return_value = json.dumps([_identity()])
    result = rehearsal._verify_resource(
        preview,
        {"MARU_DATABASE_URL": "postgresql://maru_runtime:private@127.0.0.1:54399/maru"},
    )
    assert result["container"] == "owned-id"
    assert "private" not in str(result)
