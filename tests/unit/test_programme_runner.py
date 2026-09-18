"""Mocked owned-process orchestration; never native or complete-journey evidence."""

import io
import json
import ssl
import subprocess
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_runner as runner
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_setup_scenarios import _document

RUN = "1234567890abcdef1234567890abcdef"


def test_deferred_policy_precedes_every_resource(monkeypatch):
    monkeypatch.setattr(
        runner,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("postgresql_deferred")),
    )
    resources = [Mock() for _ in range(4)]
    monkeypatch.setattr(runner.socket, "socket", resources[0])
    monkeypatch.setattr(runner, "generate_fixture_material", resources[1])
    monkeypatch.setattr(runner, "isolated_programme_database", resources[2])
    monkeypatch.setattr(runner.subprocess, "Popen", resources[3])
    with (
        pytest.raises(ProgrammeRehearsalEnvironmentError, match="postgresql_deferred"),
        runner.isolated_programme_application(),
    ):
        pytest.fail("A deferred fixture must never yield.")
    for resource in resources:
        resource.assert_not_called()


@pytest.mark.parametrize("timeouts", [0, 1, 2])
def test_shutdown_closes_keepalive_before_bounded_owned_process_fallback(timeouts):
    process = Mock()
    process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 5)] * timeouts + [
        0
    ]
    runner._stop_owned_process(process)
    assert process.mock_calls[0] == (("stdin.close", (), {}))
    assert process.wait.call_count == timeouts + 1
    assert process.terminate.call_count == (timeouts >= 1)
    assert process.kill.call_count == (timeouts == 2)
    process.stdout.close.assert_called_once_with()
    assert all(call.kwargs == {"timeout": 5} for call in process.wait.call_args_list)


@pytest.mark.parametrize(
    ("marker", "exited"), [("ready\n", None), ("foreign\n", None), ("ready\n", 0)]
)
def test_readiness_requires_exact_marker_and_live_process(monkeypatch, marker, exited):
    monkeypatch.setattr(runner, "remaining_lease", lambda _deadline: 20.0)
    process = Mock(stdout=io.StringIO(marker))
    process.poll.return_value = exited
    if marker == "ready\n" and exited is None:
        runner._await_ready(process, expected="ready", deadline=300.0)
    else:
        with pytest.raises(runner.ProgrammeHttpsError, match="server_start_failed"):
            runner._await_ready(process, expected="ready", deadline=300.0)


@pytest.mark.parametrize(
    "body",
    [
        {"status": "ok", "dependencies": {"database": "ok"}},
        {"status": "unavailable", "dependencies": {"database": "ok"}},
        {"status": "ok", "dependencies": {"database": "unavailable"}},
        {"status": "ok", "dependencies": {}},
        [],
        None,
    ],
)
def test_health_verifies_leaf_and_all_dependencies_without_proxy_or_redirect(
    monkeypatch, body, tmp_path
):
    context = Mock()
    context_factory = Mock(return_value=context)
    monkeypatch.setattr(runner.ssl, "SSLContext", context_factory)
    monkeypatch.setattr(runner, "remaining_lease", lambda _deadline: 10.0)
    response = Mock(status=200)
    response.read.return_value = json.dumps(body).encode()
    response_context = Mock()
    response_context.__enter__ = Mock(return_value=response)
    response_context.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response_context
    factory = Mock(return_value=opener)
    monkeypatch.setattr(runner.urllib.request, "build_opener", factory)
    certificate = tmp_path / "certificate.pem"
    if body == {"status": "ok", "dependencies": {"database": "ok"}}:
        runner._verify_https_health(
            "https://127.0.0.1:55443", certificate, deadline=300.0
        )
    else:
        with pytest.raises(runner.ProgrammeHttpsError, match="health_unavailable"):
            runner._verify_https_health(
                "https://127.0.0.1:55443", certificate, deadline=300.0
            )
    context_factory.assert_called_once_with(ssl.PROTOCOL_TLS_CLIENT)
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    context.load_verify_locations.assert_called_once_with(cafile=str(certificate))
    handlers = factory.call_args.args
    assert handlers[0].proxies == {}
    assert handlers[1]._context is context
    assert isinstance(handlers[2], runner._NoRedirect)
    with pytest.raises(runner.ProgrammeHttpsError, match="redirect_refused"):
        handlers[2].redirect_request(None, None, 302, "", {}, "https://foreign.invalid")
    opener.open.assert_called_once_with(
        "https://127.0.0.1:55443/health/ready", timeout=10.0
    )
    response.read.assert_called_once_with(16_385)


@pytest.fixture
def launch_seams(monkeypatch, tmp_path):
    events = []
    request = SimpleNamespace(run_id=RUN, lease_seconds=600)
    monkeypatch.setattr(runner, "require_programme_rehearsal_request", lambda: request)
    monkeypatch.setattr(runner.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(runner, "remaining_lease", lambda _deadline: 50.0)
    reservation = Mock()
    reservation.getsockname.return_value = ("127.0.0.1", 55443)
    reservation.__enter__ = Mock(return_value=reservation)
    reservation.__exit__ = Mock(return_value=False)
    reservation.close.side_effect = lambda: events.append("port-release")
    monkeypatch.setattr(runner.socket, "socket", Mock(return_value=reservation))
    material = SimpleNamespace(
        secret_key="synthetic-secret",
        runtime_configuration={"PUBLIC_CONFIG": "public"},
        worker_environment=lambda: {"PRIVATE_KEY": "worker-only"},
    )
    monkeypatch.setattr(runner, "generate_fixture_material", lambda **_kwargs: material)

    @contextmanager
    def database():
        events.append("database-start")
        try:
            yield "owned-lease"
        finally:
            events.append("database-stop")

    @contextmanager
    def directory(**_kwargs):
        events.append("directory-start")
        try:
            yield str(tmp_path)
        finally:
            events.append("directory-stop")

    monkeypatch.setattr(runner, "isolated_programme_database", database)
    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", directory)
    monkeypatch.setattr(runner, "create_loopback_certificate", Mock(return_value="sha"))
    provision = Mock(return_value=SimpleNamespace(database_url="synthetic-runtime-uri"))
    monkeypatch.setattr(runner, "provision_programme_runtime", provision)
    monkeypatch.setattr(
        runner, "_child_environment", Mock(return_value={"BASE": "clean"})
    )
    monkeypatch.setattr(runner, "_verify_lease", Mock())
    worker = Mock(side_effect=lambda *_args, **_kwargs: events.append("worker"))
    monkeypatch.setattr(runner, "_child", worker)
    process = Mock()

    def start(*_args, **_kwargs):
        events.append("server-start")
        return process

    popen = Mock(side_effect=start)
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner, "_await_ready", Mock())
    health = Mock(side_effect=lambda *_args, **_kwargs: events.append("health"))
    monkeypatch.setattr(runner, "_verify_https_health", health)
    monkeypatch.setattr(
        runner,
        "_stop_owned_process",
        Mock(side_effect=lambda _process: events.append("server-stop")),
    )
    return SimpleNamespace(
        events=events,
        popen=popen,
        worker=worker,
        provision=provision,
        health=health,
        process=process,
        material=material,
    )


def test_runner_orders_actual_owners_and_keeps_private_material_out_of_server(
    launch_seams,
):
    seams = launch_seams
    with runner.isolated_programme_application() as fixture:
        assert fixture.url == "https://127.0.0.1:55443"
        assert fixture.deadline == 700.0
        assert "synthetic-secret" not in repr(fixture)
        assert "worker-only" not in repr(fixture)
        assert seams.events == [
            "database-start",
            "directory-start",
            "worker",
            "port-release",
            "server-start",
            "health",
        ]
        fixture.refresh_workers()
    assert seams.events[-3:] == ["server-stop", "directory-stop", "database-stop"]
    seams.provision.assert_called_once_with(
        "owned-lease",
        candidate_schema=True,
        candidate_writes=True,
        fixture_material=seams.material,
    )
    assert seams.worker.call_count == 2
    environment = seams.popen.call_args.kwargs["env"]
    assert environment[runner.DEADLINE_ENV] == "700.0"
    assert environment["PUBLIC_CONFIG"] == "public"
    assert "PRIVATE_KEY" not in environment
    assert seams.worker.call_args.args[1]["PRIVATE_KEY"] == "worker-only"
    assert seams.popen.call_args.kwargs["stdin"] == subprocess.PIPE
    assert seams.popen.call_args.kwargs["stderr"] == subprocess.DEVNULL


@pytest.mark.parametrize("failure", ["worker", "spawn", "health", "journey"])
def test_failure_disposes_only_acquired_owned_resources(launch_seams, failure):
    seams = launch_seams
    error = RuntimeError("synthetic failure")
    if failure == "worker":
        seams.worker.side_effect = error
    elif failure == "spawn":
        seams.popen.side_effect = OSError("synthetic private path")
    elif failure == "health":
        seams.health.side_effect = error

    def attempt():
        with runner.isolated_programme_application():
            if failure == "journey":
                raise error
            pytest.fail("An invalid fixture must not yield.")

    with pytest.raises(RuntimeError):
        attempt()
    assert seams.events[-2:] == ["directory-stop", "database-stop"]
    assert ("server-stop" in seams.events) == (failure in {"health", "journey"})


def test_setup_secret_travels_only_on_owned_child_stdin(monkeypatch):
    document = _document()
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(document)))
    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(runner, "remaining_lease", lambda _deadline: 40.0)
    material = SimpleNamespace(administrator_password="x" * 43)
    environment = {"PUBLIC": "only"}
    result = runner._prepare_setup(
        mode="new_foundation",
        material=material,
        environment=environment,
        deadline=700.0,
    )
    assert json.loads(json.dumps(asdict(result), default=str)) == document
    assert run.call_args.args[0] == [
        runner.sys.executable,
        "-m",
        "tests.rehearsals.programme_setup_scenarios",
    ]
    kwargs = run.call_args.kwargs
    assert json.loads(kwargs["input"]) == {
        "mode": "new_foundation",
        "administrator_password": "x" * 43,
    }
    assert kwargs["env"] == environment
    assert kwargs["timeout"] == 40.0
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert "x" * 43 not in repr(run.call_args.args)


@pytest.mark.parametrize(
    "failure", ["nonzero", "invalid_json", "oversize", "timeout", "os"]
)
def test_setup_failure_does_not_leak_child_output(monkeypatch, failure):
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="private"))
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "oversize":
        run.return_value.stdout = "private" * 4096
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 5)
    elif failure == "os":
        run.side_effect = OSError("private")
    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(runner, "remaining_lease", lambda _deadline: 40.0)
    with pytest.raises(
        runner.ProgrammeHttpsError, match="fixture_setup_process_failed"
    ) as error:
        runner._prepare_setup(
            mode="new_foundation",
            material=SimpleNamespace(administrator_password="x" * 43),
            environment={},
            deadline=700.0,
        )
    assert "private" not in str(error.value)


def test_requested_setup_runs_before_server_and_refreshes_real_workers(
    launch_seams, monkeypatch
):
    scenario = object()
    prepare = Mock(return_value=scenario)
    monkeypatch.setattr(runner, "_prepare_setup", prepare)
    with runner.isolated_programme_application(setup_mode="existing_series") as fixture:
        assert fixture.scenario is scenario
        assert launch_seams.worker.call_count == 2
        assert prepare.call_args.kwargs["mode"] == "existing_series"
        assert prepare.call_args.kwargs["deadline"] == fixture.deadline
        assert "PRIVATE_KEY" not in prepare.call_args.kwargs["environment"]
