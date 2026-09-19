"""Mocked owned-process orchestration; never native or complete-journey evidence."""

import io
import json
import ssl
import subprocess
from contextlib import contextmanager
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_runner as runner
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_change_scenario import _result as _change_result
from tests.unit.test_programme_change_scenario import _sources as _change_sources
from tests.unit.test_programme_items_scenario import _result as _items_result
from tests.unit.test_programme_physical_scenario import _result as _physical_result
from tests.unit.test_programme_planning_scenario import _result as _planning_result
from tests.unit.test_programme_proposal_scenario import _result, _setup
from tests.unit.test_programme_release_scenario import _result as _release_result
from tests.unit.test_programme_review_scenario import _result as _review_result
from tests.unit.test_programme_setup_scenarios import _document
from tests.unit.test_programme_staffing_scenario import _result as _staffing_result

RUN = "1234567890abcdef1234567890abcdef"


@pytest.mark.parametrize(
    "failure", [None, "nonzero", "timeout", "oversize", "source", "operation"]
)
def test_continuity_child_has_closed_input_original_lease_and_no_signing_key(
    launch_seams, monkeypatch, failure
):
    from tests.rehearsals.programme_continuity_transition import (  # noqa: PLC0415
        ProgrammeContinuityTransition,
    )

    sources = _change_sources()
    changed = _change_result(sources)
    expected = ProgrammeContinuityTransition(
        "withdraw",
        sources[0].organization_id,
        sources[0].edition_id,
        changed.release_id,
        None,
        3,
    )
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(asdict(expected), default=str)
        )
    )
    monkeypatch.setattr(runner.subprocess, "run", run)
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("fixed child", 50)
    elif failure == "oversize":
        run.return_value.stdout = "x" * 16_385
    elif failure == "source":
        changed = replace(changed, edition_id=_setup().edition_id)
    operation = "activate" if failure == "operation" else "withdraw"
    with runner.isolated_programme_application() as original:
        fixture = replace(original, scenario=sources[0])
        if failure:
            with pytest.raises((runner.ProgrammeHttpsError, ValueError, RuntimeError)):
                fixture.prepare_continuity_transition(
                    sources[1:], changed, operation=operation
                )
        else:
            assert (
                fixture.prepare_continuity_transition(
                    sources[1:], changed, operation=operation
                )
                == expected
            )
    if failure in {"source", "operation"}:
        run.assert_not_called()
    else:
        options = run.call_args.kwargs
        assert options["timeout"] == 50.0
        assert options["stderr"] == subprocess.DEVNULL
        assert runner.SIGNING_ENV not in options["env"]
        document = json.loads(options["input"])
        assert set(document) == {"sources", "change", "operation"}
        assert document["change"]["release_id"] == str(changed.release_id)
        assert (
            run.call_args.args[0][-1]
            == "tests.rehearsals.programme_continuity_transition"
        )


@pytest.mark.parametrize("failure", [None, "nonzero", "timeout", "oversize", "source"])
def test_change_child_keeps_original_eight_sources_private_and_lease_bounded(
    launch_seams, monkeypatch, failure
):
    sources = _change_sources()
    expected = _change_result(sources)
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(asdict(expected), default=str)
        )
    )
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 50)
    elif failure == "oversize":
        run.return_value.stdout = "private" * 4096
    elif failure == "source":
        sources = (*sources[:-1], replace(sources[-1], edition_id=_setup().edition_id))
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as original:
        fixture = replace(original, scenario=sources[0])
        if failure is None:
            assert fixture.prepare_change(*sources[1:]) == expected
        elif failure == "source":
            with pytest.raises(RuntimeError, match="result_invalid"):
                fixture.prepare_change(*sources[1:])
            run.assert_not_called()
        else:
            with pytest.raises(
                runner.ProgrammeHttpsError, match="change_process_failed"
            ):
                fixture.prepare_change(*sources[1:])
    if failure != "source":
        assert run.call_args.args[0][-1] == "tests.rehearsals.programme_change_scenario"
        options = run.call_args.kwargs
        assert options["timeout"] == 50.0
        assert options["stderr"] == subprocess.DEVNULL
        assert sources[-1].reviewer.password not in repr(options["env"])
        assert json.loads(options["input"])["release"]["release_id"] == str(
            sources[-1].release_id
        )
        assert launch_seams.worker.call_count == 2


def test_change_stage_requires_policy_and_prepared_setup(launch_seams, monkeypatch):
    run = Mock()
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as fixture:
        with pytest.raises(runner.ProgrammeHttpsError, match="dependencies_required"):
            fixture.prepare_change(*(None,) * 7)
        monkeypatch.setattr(
            runner,
            "require_programme_rehearsal_request",
            Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
        )
        with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
            fixture.prepare_change(*(None,) * 7)
    run.assert_not_called()


@pytest.mark.parametrize("failure", [None, "nonzero", "timeout", "oversize", "source"])
def test_release_child_retains_original_full_chain_private_pipe_and_lease(
    launch_seams, monkeypatch, failure
):
    setup = _setup()
    proposal = _result(setup)
    review = _review_result(setup, proposal)
    items = _items_result(setup, review)
    planning = _planning_result(setup, items)
    physical = _physical_result(setup, planning)
    staffing = _staffing_result(setup, planning)
    expected = _release_result(setup, planning)
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(asdict(expected), default=str)
        )
    )
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 50)
    elif failure == "oversize":
        run.return_value.stdout = "private" * 4096
    elif failure == "source":
        staffing = replace(staffing, edition_id=_setup().edition_id)
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as original:
        fixture = replace(original, scenario=setup)
        if failure is None:
            assert (
                fixture.prepare_release(
                    proposal, review, items, planning, physical, staffing
                )
                == expected
            )
        elif failure == "source":
            with pytest.raises(RuntimeError, match="result_invalid"):
                fixture.prepare_release(
                    proposal, review, items, planning, physical, staffing
                )
            run.assert_not_called()
        else:
            with pytest.raises(
                runner.ProgrammeHttpsError, match="release_process_failed"
            ):
                fixture.prepare_release(
                    proposal, review, items, planning, physical, staffing
                )
    if failure != "source":
        assert (
            run.call_args.args[0][-1] == "tests.rehearsals.programme_release_scenario"
        )
        options = run.call_args.kwargs
        assert options["timeout"] == 50.0
        assert options["stderr"] == subprocess.DEVNULL
        assert staffing.volunteer.password not in repr(options["env"])
        assert json.loads(options["input"])["staffing"]["candidate_id"] == str(
            planning.candidate_id
        )
        assert launch_seams.worker.call_count == 2


def test_release_stage_requires_policy_and_prepared_setup(launch_seams, monkeypatch):
    run = Mock()
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as fixture:
        with pytest.raises(runner.ProgrammeHttpsError, match="dependencies_required"):
            fixture.prepare_release(None, None, None, None, None, None)
        monkeypatch.setattr(
            runner,
            "require_programme_rehearsal_request",
            Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
        )
        with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
            fixture.prepare_release(None, None, None, None, None, None)
    run.assert_not_called()


@pytest.mark.parametrize("failure", [None, "nonzero", "timeout", "oversize", "source"])
def test_staffing_child_retains_exact_physical_chain_private_pipe_and_lease(
    launch_seams, monkeypatch, failure
):
    setup = _setup()
    proposal = _result(setup)
    review = _review_result(setup, proposal)
    items = _items_result(setup, review)
    planning = _planning_result(setup, items)
    physical = _physical_result(setup, planning)
    expected = _staffing_result(setup, planning)
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(asdict(expected), default=str)
        )
    )
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 50)
    elif failure == "oversize":
        run.return_value.stdout = "private" * 4096
    elif failure == "source":
        physical = replace(physical, edition_id=_setup().edition_id)
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as original:
        fixture = replace(original, scenario=setup)
        if failure is None:
            assert (
                fixture.prepare_staffing(proposal, review, items, planning, physical)
                == expected
            )
        elif failure == "source":
            with pytest.raises(RuntimeError, match="result_invalid"):
                fixture.prepare_staffing(proposal, review, items, planning, physical)
            run.assert_not_called()
        else:
            with pytest.raises(
                runner.ProgrammeHttpsError, match="staffing_process_failed"
            ):
                fixture.prepare_staffing(proposal, review, items, planning, physical)
    if failure != "source":
        assert (
            run.call_args.args[0][-1] == "tests.rehearsals.programme_staffing_scenario"
        )
        options = run.call_args.kwargs
        assert options["timeout"] == 50.0
        assert options["stderr"] == subprocess.DEVNULL
        assert physical.reviewer.password not in repr(options["env"])
        assert json.loads(options["input"])["physical"]["candidate_id"] == str(
            planning.candidate_id
        )
        assert launch_seams.worker.call_count == 2


def test_staffing_stage_requires_policy_and_prepared_setup(launch_seams, monkeypatch):
    run = Mock()
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as fixture:
        with pytest.raises(runner.ProgrammeHttpsError, match="dependencies_required"):
            fixture.prepare_staffing(None, None, None, None, None)
        monkeypatch.setattr(
            runner,
            "require_programme_rehearsal_request",
            Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
        )
        with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
            fixture.prepare_staffing(None, None, None, None, None)
    run.assert_not_called()


@pytest.mark.parametrize("failure", [None, "nonzero", "timeout", "oversize", "source"])
def test_physical_child_validates_chain_and_keeps_original_private_lease(
    launch_seams, monkeypatch, failure
):
    setup = _setup()
    proposal = _result(setup)
    review = _review_result(setup, proposal)
    items = _items_result(setup, review)
    planning = _planning_result(setup, items)
    expected = _physical_result(setup, planning)
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(asdict(expected), default=str)
        )
    )
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 50)
    elif failure == "oversize":
        run.return_value.stdout = "private" * 4096
    elif failure == "source":
        planning = replace(planning, edition_id=_setup().edition_id)
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as original:
        fixture = replace(original, scenario=setup)
        if failure is None:
            assert (
                fixture.prepare_physical(proposal, review, items, planning) == expected
            )
        elif failure == "source":
            with pytest.raises(RuntimeError, match="result_invalid"):
                fixture.prepare_physical(proposal, review, items, planning)
            run.assert_not_called()
        else:
            with pytest.raises(
                runner.ProgrammeHttpsError, match="physical_process_failed"
            ):
                fixture.prepare_physical(proposal, review, items, planning)
    if failure != "source":
        assert (
            run.call_args.args[0][-1] == "tests.rehearsals.programme_physical_scenario"
        )
        options = run.call_args.kwargs
        assert options["timeout"] == 50.0
        assert options["stderr"] == subprocess.DEVNULL
        assert planning.planner.password not in repr(options["env"])
        assert json.loads(options["input"])["planning"]["candidate_id"] == str(
            planning.candidate_id
        )
        assert launch_seams.worker.call_count == 2


def test_physical_stage_requires_policy_and_prepared_setup(launch_seams, monkeypatch):
    run = Mock()
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as fixture:
        with pytest.raises(runner.ProgrammeHttpsError, match="dependencies_required"):
            fixture.prepare_physical(None, None, None, None)
        monkeypatch.setattr(
            runner,
            "require_programme_rehearsal_request",
            Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
        )
        with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
            fixture.prepare_physical(None, None, None, None)
    run.assert_not_called()


@pytest.mark.parametrize("failure", [None, "nonzero", "timeout", "oversize", "source"])
def test_planning_child_keeps_source_chain_and_original_lease_private(
    launch_seams, monkeypatch, failure
):
    setup = _setup()
    proposal = _result(setup)
    review = _review_result(setup, proposal)
    items = _items_result(setup, review)
    expected = _planning_result(setup, items)
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(asdict(expected), default=str)
        )
    )
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 50)
    elif failure == "oversize":
        run.return_value.stdout = "private" * 4096
    elif failure == "source":
        items = replace(items, edition_id=_setup().edition_id)
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as original:
        fixture = replace(original, scenario=setup)
        if failure is None:
            assert fixture.prepare_planning(proposal, review, items) == expected
        elif failure == "source":
            with pytest.raises(RuntimeError, match="result_invalid"):
                fixture.prepare_planning(proposal, review, items)
            run.assert_not_called()
        else:
            with pytest.raises(
                runner.ProgrammeHttpsError, match="planning_process_failed"
            ):
                fixture.prepare_planning(proposal, review, items)
    if failure != "source":
        assert run.call_args.args[0] == [
            runner.sys.executable,
            "-m",
            "tests.rehearsals.programme_planning_scenario",
        ]
        options = run.call_args.kwargs
        assert options["timeout"] == 50.0
        assert options["stderr"] == subprocess.DEVNULL
        assert "PRIVATE_KEY" not in options["env"]
        assert items.ceremony_host.password not in repr(options["env"])
        assert json.loads(options["input"])["items"]["ceremony"]["item_id"] == str(
            items.ceremony.item_id
        )
        assert launch_seams.worker.call_count == 2


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


def test_continuity_key_is_web_only_and_trust_is_independently_retained(
    launch_seams, monkeypatch
):
    setup = object()
    monkeypatch.setattr(runner, "_prepare_setup", Mock(return_value=setup))
    generate = Mock(
        return_value=SimpleNamespace(
            signing_policy="private-issuer-key",
            trust_policy=b"independent-public-trust",
        )
    )
    monkeypatch.setattr(runner, "generate_continuity_material", generate)
    with runner.isolated_programme_application(
        setup_mode="new_foundation", with_continuity=True
    ) as fixture:
        generate.assert_called_once_with(setup, deadline=700.0)
        assert fixture.continuity_trust_policy == b"independent-public-trust"
        assert "private-issuer-key" not in repr(fixture)
        assert runner.SIGNING_ENV not in fixture._application_environment
        assert runner.SIGNING_ENV not in fixture._worker_environment
    assert (
        launch_seams.popen.call_args.kwargs["env"][runner.SIGNING_ENV]
        == "private-issuer-key"
    )
    assert all(
        runner.SIGNING_ENV not in call.args[1]
        for call in launch_seams.worker.call_args_list
    )
    assert launch_seams.events[-3:] == [
        "server-stop",
        "directory-stop",
        "database-stop",
    ]


@pytest.mark.parametrize(("mode", "enabled"), [(None, True), ("new_foundation", 1)])
def test_invalid_continuity_option_opens_no_resource(launch_seams, mode, enabled):
    with (
        pytest.raises(runner.ProgrammeHttpsError, match="continuity_option"),
        runner.isolated_programme_application(setup_mode=mode, with_continuity=enabled),
    ):
        pytest.fail("Invalid configuration was admitted.")
    assert launch_seams.events == []


def test_continuity_generation_failure_starts_no_server_and_cleans_owned_resources(
    launch_seams, monkeypatch
):
    monkeypatch.setattr(runner, "_prepare_setup", Mock(return_value=object()))
    monkeypatch.setattr(
        runner,
        "generate_continuity_material",
        Mock(side_effect=runner.ProgrammeHttpsError("lease_insufficient")),
    )
    with (
        pytest.raises(runner.ProgrammeHttpsError, match="lease_insufficient"),
        runner.isolated_programme_application(
            setup_mode="new_foundation", with_continuity=True
        ),
    ):
        pytest.fail("Failed signing configuration was admitted.")
    launch_seams.popen.assert_not_called()
    assert launch_seams.events[-2:] == ["directory-stop", "database-stop"]


def test_optional_real_scanner_configuration_and_owned_teardown_order(
    launch_seams, monkeypatch
):
    lease = SimpleNamespace(
        runtime_environment=lambda: {"MARU_PROGRAMME_FILE_SCANNER": "clamav"}
    )

    @contextmanager
    def scanner(*, deadline):
        assert deadline == 700.0
        launch_seams.events.append("scanner-start")
        try:
            yield lease
        finally:
            launch_seams.events.append("scanner-stop")

    monkeypatch.setattr(runner, "isolated_programme_scanner", scanner)
    with runner.isolated_programme_application(with_scanner=True) as fixture:
        assert fixture.scanner is lease
        assert (
            launch_seams.popen.call_args.kwargs["env"]["MARU_PROGRAMME_FILE_SCANNER"]
            == "clamav"
        )
    assert launch_seams.events[-4:] == [
        "server-stop",
        "scanner-stop",
        "directory-stop",
        "database-stop",
    ]


@pytest.mark.parametrize("failure", [None, "nonzero", "timeout", "oversize", "json"])
def test_proposal_child_is_bounded_private_and_has_no_worker_key(
    launch_seams, monkeypatch, failure
):
    setup = _setup()
    expected = _result(setup)
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(asdict(expected), default=str)
        )
    )
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 50)
    elif failure == "oversize":
        run.return_value.stdout = "private" * 4096
    elif failure == "json":
        run.return_value.stdout = "private"
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as original:
        fixture = replace(original, scenario=setup, scanner=object())
        if failure is None:
            assert fixture.prepare_proposal() == expected
        else:
            with pytest.raises(
                runner.ProgrammeHttpsError, match="proposal_process_failed"
            ) as error:
                fixture.prepare_proposal()
            assert "private" not in str(error.value)
    assert run.call_args.args[0] == [
        runner.sys.executable,
        "-m",
        "tests.rehearsals.programme_proposal_scenario",
    ]
    options = run.call_args.kwargs
    assert json.loads(options["input"])["mode"] == setup.mode
    assert options["timeout"] == 50.0
    assert options["stderr"] == subprocess.DEVNULL
    assert "PRIVATE_KEY" not in options["env"]
    assert setup.intake_person.password not in repr(options["env"])
    assert launch_seams.worker.call_count == 2


def test_proposal_requires_policy_and_setup_scanner_dependencies(
    launch_seams, monkeypatch
):
    run = Mock()
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as fixture:
        with pytest.raises(runner.ProgrammeHttpsError, match="dependencies_required"):
            fixture.prepare_proposal()
        monkeypatch.setattr(
            runner,
            "require_programme_rehearsal_request",
            Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
        )
        with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
            fixture.prepare_proposal()
    run.assert_not_called()


@pytest.mark.parametrize("failure", [None, "nonzero", "timeout", "json", "source"])
def test_review_child_keeps_exact_proposal_private_and_deadline_bounded(
    launch_seams, monkeypatch, failure
):
    setup = _setup()
    proposal = _result(setup)
    expected = _review_result(setup, proposal)
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(asdict(expected), default=str)
        )
    )
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 50)
    elif failure == "json":
        run.return_value.stdout = "private"
    elif failure == "source":
        proposal = replace(proposal, edition_id=_result(_setup()).edition_id)
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as original:
        fixture = replace(original, scenario=setup)
        if failure is None:
            assert fixture.prepare_review(proposal) == expected
        elif failure == "source":
            with pytest.raises(RuntimeError, match="result_invalid"):
                fixture.prepare_review(proposal)
            run.assert_not_called()
        else:
            with pytest.raises(
                runner.ProgrammeHttpsError, match="review_process_failed"
            ):
                fixture.prepare_review(proposal)
    if failure != "source":
        options = run.call_args.kwargs
        assert options["timeout"] == 50.0
        assert options["stderr"] == subprocess.DEVNULL
        assert "PRIVATE_KEY" not in options["env"]
        assert proposal.lead.password not in repr(options["env"])
        assert json.loads(options["input"])["proposal"]["revision_id"] == str(
            proposal.revision_id
        )
        assert launch_seams.worker.call_count == 2


@pytest.mark.parametrize("failure", [None, "nonzero", "timeout", "oversize", "source"])
def test_items_child_retains_sources_secret_pipe_and_original_deadline(
    launch_seams, monkeypatch, failure
):
    setup = _setup()
    proposal = _result(setup)
    review = _review_result(setup, proposal)
    expected = _items_result(setup, review)
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0, stdout=json.dumps(asdict(expected), default=str)
        )
    )
    if failure == "nonzero":
        run.return_value.returncode = 2
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 50)
    elif failure == "oversize":
        run.return_value.stdout = "private" * 4096
    elif failure == "source":
        review = replace(review, proposal_id=_result(setup).proposal_id)
    monkeypatch.setattr(runner.subprocess, "run", run)
    with runner.isolated_programme_application() as original:
        fixture = replace(original, scenario=setup)
        if failure is None:
            assert fixture.prepare_items(proposal, review) == expected
        elif failure == "source":
            with pytest.raises(RuntimeError, match="result_invalid"):
                fixture.prepare_items(proposal, review)
            run.assert_not_called()
        else:
            with pytest.raises(
                runner.ProgrammeHttpsError, match="items_process_failed"
            ):
                fixture.prepare_items(proposal, review)
    if failure != "source":
        options = run.call_args.kwargs
        assert options["timeout"] == 50.0
        assert options["stderr"] == subprocess.DEVNULL
        assert "PRIVATE_KEY" not in options["env"]
        assert review.people[-1].password not in repr(options["env"])
        assert json.loads(options["input"])["review"]["item_id"] == str(review.item_id)
        assert launch_seams.worker.call_count == 2
