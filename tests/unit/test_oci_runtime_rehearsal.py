from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import TYPE_CHECKING

import pytest
from scripts import rehearse_oci_runtime as rehearsal

if TYPE_CHECKING:
    from pathlib import Path


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    def run(
        self,
        arguments,
        *,
        stage,
        timeout_seconds,
        input_text=None,
        allow_failure=False,
    ):
        _ = stage, timeout_seconds, allow_failure
        command = tuple(arguments)
        self.calls.append((command, input_text))
        if command[:3] == ("docker", "container", "inspect"):
            return rehearsal.CommandResult(1, "", "absent")
        return rehearsal.CommandResult(0, "container-id\n", "")


class DockerStateRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.resources: dict[str, dict[str, dict[str, str]]] = {
            "container": {},
            "network": {},
            "volume": {},
        }
        self.running: set[str] = set()
        self.fail_inventory_for: set[str] = set()
        self.preserve_on_remove: set[str] = set()

    def add(
        self,
        resource_type: str,
        name: str,
        *,
        labels: dict[str, str],
        running: bool = False,
    ) -> None:
        self.resources[resource_type][name] = labels
        if running:
            self.running.add(name)

    @staticmethod
    def _filters(command: tuple[str, ...]) -> list[tuple[str, str]]:
        filters: list[tuple[str, str]] = []
        for index, value in enumerate(command[:-1]):
            if value != "--filter" or not command[index + 1].startswith("label="):
                continue
            key, _separator, expected = command[index + 1][6:].partition("=")
            filters.append((key, expected))
        return filters

    def _listed_names(
        self,
        resource_type: str,
        command: tuple[str, ...],
    ) -> list[str]:
        if resource_type in self.fail_inventory_for:
            raise rehearsal.RehearsalError("command_failed", "test")
        names = set(self.resources[resource_type])
        if resource_type == "container" and "--all" not in command:
            names &= self.running
        for key, expected in self._filters(command):
            names = {
                name
                for name in names
                if self.resources[resource_type][name].get(key) == expected
            }
        return sorted(names)

    def run(  # noqa: PLR0911 - stateful Docker fake mirrors CLI command families
        self,
        arguments,
        *,
        stage,
        timeout_seconds,
        input_text=None,
        allow_failure=False,
    ):
        _ = stage, timeout_seconds, input_text, allow_failure
        command = tuple(arguments)
        self.calls.append(command)
        if command[0] != "docker":
            return rehearsal.CommandResult(0, "", "")
        if command[1] in self.resources and command[2] == "ls":
            names = self._listed_names(command[1], command)
            return rehearsal.CommandResult(0, "\n".join(names), "")
        if command[1] in self.resources and command[2] == "inspect":
            name = command[-1]
            labels = self.resources[command[1]][name]
            return rehearsal.CommandResult(0, json.dumps(labels), "")
        if command[1] == "stop":
            self.running.discard(command[-1])
            return rehearsal.CommandResult(0, command[-1], "")
        if command[1] == "rm":
            name = command[-1]
            if name not in self.preserve_on_remove:
                self.resources["container"].pop(name, None)
                self.running.discard(name)
            return rehearsal.CommandResult(0, name, "")
        if command[1] in {"network", "volume"} and command[2] == "rm":
            name = command[-1]
            if name not in self.preserve_on_remove:
                self.resources[command[1]].pop(name, None)
            return rehearsal.CommandResult(0, name, "")
        return rehearsal.CommandResult(0, "", "")


def _configuration(tmp_path: Path) -> rehearsal.RehearsalConfiguration:
    return rehearsal.RehearsalConfiguration(
        application_image=rehearsal.DEFAULT_APPLICATION_IMAGE,
        source_revision=rehearsal.DEFAULT_SOURCE_REVISION,
        run_id="0123456789ab",
        evidence_path=tmp_path / ".local-ci" / "evidence.json",
        retain_resources=False,
        retain_on_failure=False,
    )


def _owned_labels(run_id: str = "0123456789ab") -> dict[str, str]:
    return {
        rehearsal.RESOURCE_LABEL: "1",
        rehearsal.RUN_LABEL: run_id,
    }


def test_command_runner_preserves_binary_stdin_without_newline_translation() -> None:
    runner = rehearsal.CommandRunner()
    result = runner.run(
        (
            sys.executable,
            "-c",
            "import sys; print(sys.stdin.buffer.read().hex())",
        ),
        stage="test",
        timeout_seconds=30,
        input_text=b"a\nb\n",
    )

    assert result.stdout.strip() == "610a620a"


@pytest.mark.parametrize(
    "reference",
    [
        "ghcr.io/martonpornoi/maru:latest",
        "ghcr.io/martonpornoi/maru@sha256:short",
        "ghcr.io/martonpornoi/maru @sha256:" + ("a" * 64),
        "ghcr.io/martonpornoi/maru@sha256:" + ("A" * 64),
    ],
)
def test_requires_digest_pinned_application_images(reference: str) -> None:
    with pytest.raises(ValueError, match="sha256"):
        rehearsal.validate_image_reference(reference)


def test_pins_reviewed_application_postgresql_and_source_identity() -> None:
    assert rehearsal.validate_image_reference(rehearsal.DEFAULT_APPLICATION_IMAGE)
    assert rehearsal.validate_image_reference(rehearsal.POSTGRES_IMAGE)
    assert rehearsal.POSTGRES_IMAGE.startswith("postgres:17.11-alpine@sha256:")
    assert rehearsal.validate_source_revision(rehearsal.DEFAULT_SOURCE_REVISION)


def test_provisioning_sql_matches_release_source_contract() -> None:
    path = (
        rehearsal.REPOSITORY_ROOT
        / "docs"
        / "operations"
        / "postgresql-runtime-role-provisioning.sql.example"
    )
    sql_text = path.read_text(encoding="utf-8")

    assert rehearsal.provisioning_sql_is_exact(sql_text)
    assert hashlib.sha256(sql_text.encode()).hexdigest() == (
        rehearsal.EXPECTED_PROVISIONING_SQL_SHA256
    )


def test_resource_names_are_isolated_and_cleanup_safe() -> None:
    resources = rehearsal.ResourceSet.for_run("0123456789ab")

    assert resources.prefix == "maru-oci-0123456789ab"
    assert resources.network.endswith("-network")
    assert resources.postgres.endswith("-postgres")
    assert resources.web.endswith("-web")
    assert len(set(resources.volumes)) == 4
    with pytest.raises(ValueError, match="twelve"):
        rehearsal.ResourceSet.for_run("production")


@pytest.mark.parametrize("collision_kind", ["job_name", "unexpected_label"])
def test_resource_creation_refuses_complete_namespace_collisions(
    tmp_path: Path,
    collision_kind: str,
) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    if collision_kind == "job_name":
        name = f"{workflow.resources.prefix}-job-99"
        labels = {"foreign": "1"}
    else:
        name = "maru-oci-unexpected"
        labels = _owned_labels()
    runner.add("container", name, labels=labels)

    with pytest.raises(rehearsal.RehearsalError, match="resource_name_collision"):
        workflow.create_isolated_resources()

    assert not any(command[1:3] == ("network", "create") for command in runner.calls)


def test_pgpass_is_private_network_only_and_rejects_parser_escapes() -> None:
    line = rehearsal.pgpass_line(username="maru_runtime", password="safe-token")

    assert line == "postgres:5432:maru:maru_runtime:safe-token\n"
    with pytest.raises(ValueError, match="reserved"):
        rehearsal.pgpass_line(username="maru:runtime", password="safe-token")
    with pytest.raises(ValueError, match="reserved"):
        rehearsal.pgpass_line(username="maru_runtime", password="unsafe:token")


def test_documented_stage_order_stops_writers_before_activation() -> None:
    assert rehearsal.STAGE_ORDER.index("observe_exact_pre_activation_fence") < (
        rehearsal.STAGE_ORDER.index("activate_exact_provenance")
    )
    assert rehearsal.STAGE_ORDER.index("activate_exact_provenance") < (
        rehearsal.STAGE_ORDER.index("observe_exact_runtime_readiness")
    )
    assert rehearsal.STAGE_ORDER[-2:] == (
        "replay_migrations_and_bootstrap",
        "final_readiness",
    )


def test_json_parser_returns_top_level_count_only_object() -> None:
    payload = {"status": "ready", "counts": {"blockers": 0}}
    output = "bounded warning\n" + json.dumps(payload, indent=2) + "\n"

    assert rehearsal.parse_last_json_object(output) == payload


def test_evidence_rejects_credentials_urls_and_actor_identity() -> None:
    assert rehearsal.evidence_is_sanitized(
        {"status": "ready", "counts": {"accounts": 1}},
        ("secret-one", "secret-two"),
    )
    assert not rehearsal.evidence_is_sanitized(
        {"value": "secret-one"},
        ("secret-one",),
    )
    assert not rehearsal.evidence_is_sanitized(
        {"value": "postgresql://maru_runtime@postgres/maru"},
        (),
    )
    assert not rehearsal.evidence_is_sanitized(
        {"value": "oci.runtime.rehearsal.admin@maru.invalid"},
        (),
    )


def test_app_job_uses_genuine_login_without_password_in_argv_or_environment(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    workflow._app_job(
        stage="test",
        command=("python", "src/manage.py", "check"),
        credential="runtime",
        exact=True,
    )

    arguments, input_text = runner.calls[-1]
    serialized = " ".join(arguments)
    assert input_text is None
    assert "postgresql://maru_runtime@postgres:5432/maru" in serialized
    assert "PGPASSFILE=/run/secrets/value" in serialized
    assert "MARU_RUNTIME_DATABASE_ROLE=maru_runtime" in serialized
    assert "MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE=true" in serialized
    assert "--cap-drop ALL" in serialized
    assert "--rm" not in arguments
    assert "--read-only" in arguments
    assert f"{rehearsal.RESOURCE_LABEL}=1" in arguments
    assert f"{rehearsal.RUN_LABEL}=0123456789ab" in arguments
    assert all(secret not in serialized for secret in workflow._secrets.values())


def test_web_and_database_have_no_host_port(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    workflow._start_web(
        stage="test",
        credential="runtime",
        exact=True,
        runtime_role_configured=True,
    )

    run_arguments = next(
        arguments
        for arguments, _input in runner.calls
        if arguments[:2] == ("docker", "run")
    )
    assert "--publish" not in run_arguments
    assert "5432" not in run_arguments
    assert "--network" in run_arguments


def test_http_probe_uses_only_container_loopback(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    runner_response = {
        "http_status": 200,
        "body": {"status": "ok"},
    }

    def respond(*_args, **_kwargs):
        return rehearsal.CommandResult(0, json.dumps(runner_response), "")

    runner.run = respond  # type: ignore[method-assign]
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    assert workflow._http("/health/live") == (200, {"status": "ok"})
    assert workflow._http("https://example.invalid/") is None
    assert "http://127.0.0.1:8000" in rehearsal.HTTP_PROBE_SOURCE


def test_health_contract_accepts_only_one_named_unavailable_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = rehearsal.OciRuntimeRehearsal(_configuration(tmp_path))
    responses = iter(
        [
            {"status": "ok"},
            {
                "status": "unavailable",
                "dependencies": {
                    **dict.fromkeys(
                        rehearsal.COMPATIBILITY_READY_DEPENDENCIES,
                        "ok",
                    ),
                    "logistics": "unavailable",
                },
            },
        ]
    )
    monkeypatch.setattr(workflow, "_wait_http", lambda **_kwargs: next(responses))

    evidence = workflow._health_evidence(
        stage="test",
        ready_status=503,
        expected_dependencies=rehearsal.COMPATIBILITY_READY_DEPENDENCIES,
        unavailable_dependency="logistics",
    )

    assert evidence["ready_http"] == 503
    assert evidence["dependencies"] == {
        **dict.fromkeys(rehearsal.COMPATIBILITY_READY_DEPENDENCIES, "ok"),
        "logistics": "unavailable",
    }


def test_health_contract_accepts_complete_ready_dependency_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = rehearsal.OciRuntimeRehearsal(_configuration(tmp_path))
    responses = iter(
        [
            {"status": "ok"},
            {
                "status": "ok",
                "dependencies": dict.fromkeys(
                    rehearsal.EXACT_READY_DEPENDENCIES,
                    "ok",
                ),
            },
        ]
    )
    monkeypatch.setattr(workflow, "_wait_http", lambda **_kwargs: next(responses))

    evidence = workflow._health_evidence(
        stage="test",
        ready_status=200,
        expected_dependencies=rehearsal.EXACT_READY_DEPENDENCIES,
    )

    assert evidence["ready_status"] == "ok"
    assert evidence["dependencies"] == dict.fromkeys(
        rehearsal.EXACT_READY_DEPENDENCIES,
        "ok",
    )


@pytest.mark.parametrize(
    ("live", "ready"),
    [
        (
            {"status": "starting"},
            {
                "status": "ok",
                "dependencies": dict.fromkeys(
                    rehearsal.COMPATIBILITY_READY_DEPENDENCIES,
                    "ok",
                ),
            },
        ),
        (
            {"status": "ok", "detail": "unexpected"},
            {
                "status": "ok",
                "dependencies": dict.fromkeys(
                    rehearsal.COMPATIBILITY_READY_DEPENDENCIES,
                    "ok",
                ),
            },
        ),
        (
            {"status": "ok"},
            {
                "status": "ok",
                "dependencies": {
                    key: "ok"
                    for key in rehearsal.COMPATIBILITY_READY_DEPENDENCIES
                    if key != "logistics"
                },
            },
        ),
        (
            {"status": "ok"},
            {
                "status": "ok",
                "dependencies": {
                    **dict.fromkeys(
                        rehearsal.COMPATIBILITY_READY_DEPENDENCIES,
                        "ok",
                    ),
                    "unexpected": "ok",
                },
            },
        ),
        (
            {"status": "ok"},
            {
                "status": "ok",
                "dependencies": dict.fromkeys(
                    rehearsal.COMPATIBILITY_READY_DEPENDENCIES,
                    "ok",
                ),
                "detail": "unexpected",
            },
        ),
    ],
)
def test_health_contract_rejects_incomplete_or_expanded_public_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    live: dict[str, object],
    ready: dict[str, object],
) -> None:
    workflow = rehearsal.OciRuntimeRehearsal(_configuration(tmp_path))
    responses = iter([live, ready])
    monkeypatch.setattr(workflow, "_wait_http", lambda **_kwargs: next(responses))

    with pytest.raises(rehearsal.RehearsalError, match="health_contract_invalid"):
        workflow._health_evidence(
            stage="test",
            ready_status=200,
            expected_dependencies=rehearsal.COMPATIBILITY_READY_DEPENDENCIES,
        )


@pytest.mark.parametrize(
    ("activation_status", "unresolved_gate", "accepted"),
    [
        ("blocked", None, True),
        ("ready", None, False),
        ("blocked", "runtime_database_role", False),
    ],
)
def test_activation_requires_irreversible_fully_resolved_postflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    activation_status: str,
    unresolved_gate: str | None,
    accepted: bool,
) -> None:
    workflow = rehearsal.OciRuntimeRehearsal(_configuration(tmp_path))
    gates = dict.fromkeys(rehearsal.REQUIRED_PRODUCTION_GATES, "resolved")
    if unresolved_gate is not None:
        gates[unresolved_gate] = "unresolved"
    outputs = iter(
        [
            {"status": "activated"},
            {"status": "already_active"},
            {
                "status": "ready",
                "activation_status": activation_status,
                "production_status": "ready",
                "blocker_total": 0,
                "known_production_gates": gates,
            },
        ]
    )
    monkeypatch.setattr(
        workflow,
        "_running_labeled_containers",
        lambda _stage: [workflow.resources.postgres],
    )
    monkeypatch.setattr(
        workflow,
        "_app_job",
        lambda **_kwargs: json.dumps(next(outputs)),
    )

    if accepted:
        workflow.activate_exact_provenance()
        assert workflow.evidence["stages"][-1]["status"] == "passed"
    else:
        with pytest.raises(
            rehearsal.RehearsalError,
            match="activation_contract_invalid",
        ):
            workflow.activate_exact_provenance()


def test_configuration_keeps_evidence_below_ignored_local_directory() -> None:
    arguments = argparse.Namespace(
        app_image=rehearsal.DEFAULT_APPLICATION_IMAGE,
        expected_source_revision=rehearsal.DEFAULT_SOURCE_REVISION,
        run_id="0123456789ab",
        evidence=None,
        retain_resources=False,
        retain_on_failure=False,
        command_timeout_seconds=600,
        health_timeout_seconds=120,
        cleanup_retained=None,
    )

    configuration = rehearsal.configuration_from_arguments(arguments)

    assert configuration.evidence_path == (
        rehearsal.REPOSITORY_ROOT
        / ".local-ci"
        / "oci-runtime-rehearsal"
        / "0123456789ab.json"
    )


def test_bootstrap_helper_is_static_secret_free_evaluator_input() -> None:
    source = rehearsal.BOOTSTRAP_HELPER.read_text(encoding="utf-8")

    assert "password=None" in source
    assert "MARU_SYNTHETIC_OCI_REHEARSAL" in source
    assert "seed_demo_data" not in source
    assert "DEMO_ACCOUNT_PASSWORD" not in source
    assert len(hashlib.sha256(source.encode()).hexdigest()) == 64


def test_cleanup_parser_requires_exact_run_id() -> None:
    parser = rehearsal._argument_parser()

    arguments = parser.parse_args(["--cleanup-retained", "0123456789ab"])

    assert arguments.cleanup_retained == "0123456789ab"
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--run-id",
                "0123456789ab",
                "--cleanup-retained",
                "0123456789ab",
            ]
        )


def test_retention_refuses_foreign_exact_name_before_stopping(
    tmp_path: Path,
) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    runner.add(
        "container",
        workflow.resources.web,
        labels=_owned_labels("ffffffffffff"),
        running=True,
    )

    with pytest.raises(rehearsal.RehearsalError, match="cleanup_label_mismatch"):
        workflow.stop_for_retention()

    assert not any(command[1] in {"stop", "rm"} for command in runner.calls)


def test_fresh_retention_discovers_and_stops_running_job(tmp_path: Path) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    job_name = f"{workflow.resources.prefix}-job-42"
    runner.add(
        "container",
        job_name,
        labels=_owned_labels(),
        running=True,
    )

    workflow.stop_for_retention()

    assert job_name in runner.resources["container"]
    assert job_name not in runner.running
    assert ("docker", "stop", "--time", "30", job_name) in runner.calls


def test_fresh_cleanup_discovers_and_removes_retained_job(tmp_path: Path) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    job_name = f"{workflow.resources.prefix}-job-42"
    runner.add("container", job_name, labels=_owned_labels())

    workflow.cleanup()

    assert job_name not in runner.resources["container"]
    assert ("docker", "rm", "--force", job_name) in runner.calls


def test_cleanup_inventory_failure_never_means_absent(tmp_path: Path) -> None:
    runner = DockerStateRunner()
    runner.fail_inventory_for.add("container")
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    with pytest.raises(rehearsal.RehearsalError, match="command_failed"):
        workflow.cleanup()

    assert not any(command[1] == "rm" for command in runner.calls)


def test_standalone_cleanup_requires_an_existing_exact_run(tmp_path: Path) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    with pytest.raises(rehearsal.RehearsalError) as captured:
        workflow.cleanup(require_present=True)

    assert captured.value.code == "retained_run_not_found"
    assert not any(command[1] == "rm" for command in runner.calls)


def test_missing_standalone_cleanup_never_prints_removed_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def report_missing(
        _workflow: rehearsal.OciRuntimeRehearsal,
        *,
        require_present: bool = False,
    ) -> int:
        assert require_present
        raise rehearsal.RehearsalError("retained_run_not_found", "cleanup")

    monkeypatch.setattr(rehearsal.OciRuntimeRehearsal, "cleanup", report_missing)

    assert rehearsal.main(["--cleanup-retained", "0123456789ab"]) == 1

    output = capsys.readouterr().out
    assert "retained_run_not_found" in output
    assert "removed irreversibly" not in output


def test_cleanup_requires_empty_final_inventory(tmp_path: Path) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    job_name = f"{workflow.resources.prefix}-job-42"
    runner.add("container", job_name, labels=_owned_labels())
    runner.preserve_on_remove.add(job_name)

    with pytest.raises(rehearsal.RehearsalError, match="cleanup_incomplete"):
        workflow.cleanup()


def test_cleanup_refuses_unexpected_run_labeled_resource(tmp_path: Path) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciRuntimeRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    runner.add(
        "container",
        "maru-oci-unexpected",
        labels=_owned_labels(),
    )

    with pytest.raises(rehearsal.RehearsalError, match="cleanup_namespace_mismatch"):
        workflow.cleanup()

    assert not any(command[1] == "rm" for command in runner.calls)
