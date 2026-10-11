from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest
from scripts import try_maru


def test_preview_discards_inherited_database_and_application_settings(monkeypatch):
    for name in (
        "MARU_DATABASE_URL",
        "MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE",
        "DJANGO_SETTINGS_MODULE",
        "PGSERVICE",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "PYTHONPATH",
    ):
        monkeypatch.setenv(name, "foreign-value")
    monkeypatch.setenv("PATH", "kept-path")
    first = try_maru.child_environment()
    second = try_maru.child_environment()
    assert first["PATH"] == "kept-path"
    assert first["DJANGO_SETTINGS_MODULE"] == "maru.settings.local"
    assert first["PYTHONPATH"] == str(try_maru.ROOT / "src")
    assert "foreign-value" not in first.values()
    assert "MARU_DATABASE_URL" not in first
    assert first["MARU_SECRET_KEY"] != second["MARU_SECRET_KEY"]


def test_preflight_missing_docker_allocates_nothing(monkeypatch):
    monkeypatch.setattr(try_maru.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="Install Docker"):
        try_maru.preflight(8765)


def test_preflight_busy_port_reports_recovery(monkeypatch):
    monkeypatch.setattr(try_maru.shutil, "which", lambda _: "docker")
    monkeypatch.setenv("DOCKER_HOST", "npipe://local-docker")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(try_maru.subprocess, "run", Mock())
    listener = Mock()
    listener.__enter__ = Mock(return_value=listener)
    listener.__exit__ = Mock(return_value=False)
    listener.bind.side_effect = OSError("busy")
    monkeypatch.setattr(try_maru.socket, "socket", lambda: listener)
    with pytest.raises(RuntimeError, match="Choose --port"):
        try_maru.preflight(8765)


def test_database_uses_loopback_random_port_and_no_existing_volume(monkeypatch):
    preview = try_maru.Preview("docker", 8765)
    command = Mock(
        side_effect=["owned-id", "", "ready", '{"5432/tcp":[{"HostPort":"54399"}]}']
    )
    monkeypatch.setattr(preview, "docker_command", command)
    preview.start_database()
    create = command.call_args_list[0].args
    assert "127.0.0.1::5432" in create
    assert "--volume" not in create
    assert "--mount" not in create
    assert f"{try_maru.LABEL}={preview.token}" in create
    assert "POSTGRES_PASSWORD" in create
    assert "POSTGRES_PASSWORD" not in preview.environment
    assert "@127.0.0.1:54399/maru" in preview.environment["MARU_DATABASE_URL"]
    assert preview.container == "owned-id"


def test_interrupted_creation_retains_exact_resource_name(monkeypatch):
    preview = try_maru.Preview("docker", 8765)
    monkeypatch.setattr(preview, "docker_command", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        preview.start_database()
    assert preview.container == f"maru-preview-{preview.token}"


def test_cleanup_refuses_foreign_label_and_never_removes_it(monkeypatch):
    preview = try_maru.Preview("docker", 8765)
    preview.container = "foreign-id"
    command = Mock(return_value="someone-else")
    monkeypatch.setattr(preview, "docker_command", command)
    with pytest.raises(RuntimeError, match="ownership mismatch"):
        preview.close()
    assert command.call_count == 1
    assert command.call_args.args[0] == "inspect"


def test_cleanup_stops_child_and_removes_only_owned_container_and_volume(monkeypatch):
    preview = try_maru.Preview("docker", 8765)
    preview.container = "owned-id"
    preview.server = Mock()
    preview.server.poll.return_value = None
    command = Mock(side_effect=[preview.token, "removed"])
    monkeypatch.setattr(preview, "docker_command", command)
    preview.close()
    preview.server.terminate.assert_called_once()
    assert command.call_args.args == ("rm", "--force", "--volumes", "owned-id")
    assert preview.container == ""
    preview.close()
    assert command.call_count == 2


def test_check_mode_never_creates_a_preview(monkeypatch):
    monkeypatch.setattr(try_maru.sys, "argv", ["try_maru", "--check"])
    monkeypatch.setattr(try_maru, "preflight", lambda _: "docker")
    constructor = Mock()
    monkeypatch.setattr(try_maru, "Preview", constructor)
    assert try_maru.main() == 0
    constructor.assert_not_called()


@pytest.mark.parametrize("failure", [RuntimeError("setup failed"), KeyboardInterrupt()])
def test_startup_failure_or_interrupt_still_cleans_owned_resources(
    monkeypatch, failure
):
    monkeypatch.setattr(try_maru.sys, "argv", ["try_maru"])
    monkeypatch.setattr(try_maru, "preflight", lambda _: "docker")
    preview = Mock()
    preview.manage.side_effect = failure
    monkeypatch.setattr(try_maru, "Preview", Mock(return_value=preview))
    assert try_maru.main() == (0 if isinstance(failure, KeyboardInterrupt) else 1)
    preview.close.assert_called_once()
    preview.start_server.assert_not_called()


def test_cleanup_failure_is_nonzero_even_after_successful_smoke(monkeypatch):
    monkeypatch.setattr(try_maru.sys, "argv", ["try_maru", "--smoke"])
    monkeypatch.setattr(try_maru, "preflight", lambda _: "docker")
    preview = Mock()
    preview.close.side_effect = subprocess.CalledProcessError(1, ["docker", "rm"])
    monkeypatch.setattr(try_maru, "Preview", Mock(return_value=preview))
    assert try_maru.main() == 1


def test_command_failure_does_not_print_its_secret_arguments(monkeypatch, capsys):
    monkeypatch.setattr(try_maru.sys, "argv", ["try_maru", "--check"])
    monkeypatch.setattr(
        try_maru,
        "preflight",
        Mock(side_effect=subprocess.CalledProcessError(1, ["private-url"])),
    )
    assert try_maru.main() == 1
    assert "private-url" not in capsys.readouterr().err


def test_preflight_refuses_remote_docker_before_allocating_resources(monkeypatch):
    monkeypatch.setattr(try_maru.shutil, "which", lambda _: "docker")
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.example.invalid:2376")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    run = Mock()
    monkeypatch.setattr(try_maru.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="local Docker context"):
        try_maru.preflight(8765)
    run.assert_not_called()


def test_browser_time_limit_cleans_up_normally(monkeypatch):
    monkeypatch.setattr(try_maru.sys, "argv", ["try_maru", "--minutes", "1"])
    monkeypatch.setattr(try_maru, "preflight", lambda _: "docker")
    preview = Mock()
    preview.server.wait.side_effect = subprocess.TimeoutExpired("runserver", 60)
    monkeypatch.setattr(try_maru, "Preview", Mock(return_value=preview))
    assert try_maru.main() == 0
    preview.server.wait.assert_called_once_with(timeout=60)
    preview.close.assert_called_once()


@pytest.mark.parametrize("port", ["0", "65536"])
def test_invalid_port_is_rejected_before_preflight(monkeypatch, port):
    monkeypatch.setattr(try_maru.sys, "argv", ["try_maru", "--port", port])
    preflight = Mock()
    monkeypatch.setattr(try_maru, "preflight", preflight)
    with pytest.raises(SystemExit) as error:
        try_maru.main()
    assert error.value.code == 2
    preflight.assert_not_called()


def test_cleanup_kills_only_owned_child_if_graceful_stop_times_out(monkeypatch):
    preview = try_maru.Preview("docker", 8765)
    preview.server = Mock()
    preview.server.poll.return_value = None
    preview.server.wait.side_effect = [subprocess.TimeoutExpired("runserver", 10), 0]
    command = Mock()
    monkeypatch.setattr(preview, "docker_command", command)
    preview.close()
    preview.server.kill.assert_called_once()
    command.assert_not_called()
