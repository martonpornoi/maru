from __future__ import annotations

import argparse
import base64
import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from scripts import rehearse_oci_static_delivery as rehearsal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str | bytes | None]] = []
        self.config_digest = hashlib.sha256(
            rehearsal.EDGE_CONFIG_PATH.read_bytes()
        ).hexdigest()
        self.config_source = rehearsal.EDGE_CONFIG_PATH.read_text(encoding="utf-8")

    def run(
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        timeout_seconds: int,
        input_text: str | bytes | None = None,
        allow_failure: bool = False,
    ) -> rehearsal.CommandResult:
        _ = stage, timeout_seconds, allow_failure
        command = tuple(arguments)
        self.calls.append((command, input_text))
        if command[:2] == ("docker", "port"):
            return rehearsal.CommandResult(0, "127.0.0.1:49152\n", "")
        if command[:2] == ("docker", "exec") and "sha256sum" in command:
            return rehearsal.CommandResult(
                0,
                f"{self.config_digest}  /etc/nginx/conf.d/default.conf\n",
                "",
            )
        if command[:2] == ("docker", "exec") and "-T" in command:
            return rehearsal.CommandResult(0, self.config_source, "")
        if command[:2] == ("docker", "run") and any(
            "sha256sum /config/default.conf" in value for value in command
        ):
            return rehearsal.CommandResult(
                0,
                f"{self.config_digest}  /config/default.conf\n",
                "",
            )
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

    def run(  # noqa: PLR0911 - stateful fake mirrors Docker CLI families
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        timeout_seconds: int,
        input_text: str | None = None,
        allow_failure: bool = False,
    ) -> rehearsal.CommandResult:
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


def _configuration(tmp_path: Path) -> rehearsal.StaticDeliveryConfiguration:
    return rehearsal.StaticDeliveryConfiguration(
        application_image=rehearsal.DEFAULT_APPLICATION_IMAGE,
        source_revision=rehearsal.DEFAULT_SOURCE_REVISION,
        edge_image=rehearsal.DEFAULT_EDGE_IMAGE,
        run_id="0123456789ab",
        evidence_path=tmp_path / ".local-ci" / "evidence.json",
        edge_config_path=rehearsal.EDGE_CONFIG_PATH,
        retain_resources=False,
        retain_on_failure=False,
    )


def _owned_labels(run_id: str = "0123456789ab") -> dict[str, str]:
    return {
        rehearsal.RESOURCE_LABEL: "1",
        rehearsal.RUN_LABEL: run_id,
    }


def _valid_manifest_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "files": [
            {"path": "core/brand.css", "sha256": "a" * 64, "size": 12},
            {"path": "core/brand/favicon.ico", "sha256": "b" * 64, "size": 24},
        ],
    }


def _private_headers() -> dict[str, str]:
    return {
        "cache-control": "private, no-store, max-age=0",
        "pragma": "no-cache",
        "x-robots-tag": "noindex, nofollow, noarchive",
        "cross-origin-opener-policy": "same-origin",
    }


def _static_headers(content_type: str = "text/css") -> dict[str, str]:
    return {
        "cache-control": "public, max-age=0, must-revalidate",
        "content-type": content_type,
        "etag": '"candidate-etag"',
        "x-content-type-options": "nosniff",
    }


def _seed_complete_run(
    runner: DockerStateRunner,
    workflow: rehearsal.OciStaticDeliveryRehearsal,
) -> str:
    job = workflow._next_job_name()
    for container in (
        job,
        workflow.resources.edge,
        workflow.resources.web,
        workflow.resources.postgres,
    ):
        runner.add("container", container, labels=_owned_labels(), running=True)
    for network in workflow.resources.networks:
        runner.add("network", network, labels=_owned_labels())
    for volume in workflow.resources.volumes:
        runner.add("volume", volume, labels=_owned_labels())
    return job


def _is_remove(command: tuple[str, ...]) -> bool:
    return command[1] == "rm" or command[1:3] in {
        ("network", "rm"),
        ("volume", "rm"),
    }


def test_pins_exact_candidate_edge_postgresql_and_source_identity() -> None:
    assert rehearsal.DEFAULT_APPLICATION_IMAGE == (
        "ghcr.io/martonpornoi/maru@"
        "sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445"
    )
    assert rehearsal.DEFAULT_SOURCE_REVISION == (
        "be0b21db9ba2d2a956bd192a1d66c537d702c4c4"
    )
    assert rehearsal.DEFAULT_EDGE_IMAGE == (
        "ghcr.io/nginx/nginx-unprivileged:1.30.4-alpine3.24-slim@"
        "sha256:3b569ded54fe09ab73dbdb409f403631d55c0bb231e4adc10b7c974beb0dc7be"
    )
    assert rehearsal.POSTGRES_IMAGE.startswith("postgres:17.11-alpine@sha256:")
    for image in (
        rehearsal.DEFAULT_APPLICATION_IMAGE,
        rehearsal.DEFAULT_EDGE_IMAGE,
        rehearsal.POSTGRES_IMAGE,
    ):
        assert rehearsal.validate_image_reference(image) == image
    assert rehearsal.validate_source_revision(rehearsal.DEFAULT_SOURCE_REVISION)


def test_requested_digest_check_fails_closed() -> None:
    reference = "example.invalid/image@sha256:" + ("a" * 64)
    valid = {"RepoDigests": ["example.invalid/image@sha256:" + ("a" * 64)]}
    rehearsal.OciStaticDeliveryRehearsal._require_requested_digest(
        valid,
        reference,
        stage="test",
    )
    with pytest.raises(rehearsal.RehearsalError, match="image_digest_mismatch"):
        rehearsal.OciStaticDeliveryRehearsal._require_requested_digest(
            {"RepoDigests": ["example.invalid/image@sha256:" + ("b" * 64)]},
            reference,
            stage="test",
        )


def test_stage_order_preserves_copy_auth_hardening_and_restart_boundaries() -> None:
    assert len(rehearsal.STAGE_ORDER) == len(set(rehearsal.STAGE_ORDER)) == 12
    assert rehearsal.STAGE_ORDER[:4] == (
        "verify_artifacts",
        "create_isolated_resources",
        "capture_image_static_manifest",
        "populate_static_volume",
    )
    assert rehearsal.STAGE_ORDER.index("initialize_application") < (
        rehearsal.STAGE_ORDER.index("start_delivery_topology")
    )
    assert rehearsal.STAGE_ORDER.index("verify_private_api_documentation") < (
        rehearsal.STAGE_ORDER.index("verify_runtime_hardening")
    )
    assert rehearsal.STAGE_ORDER[-2:] == (
        "exercise_restart_boundaries",
        "final_delivery_check",
    )


def test_resources_use_one_distinct_exact_labelled_namespace(tmp_path: Path) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    resources = workflow.resources
    all_names = {
        resources.postgres,
        resources.web,
        resources.edge,
        *resources.networks,
        *resources.volumes,
    }

    assert resources.prefix == "maru-static-0123456789ab"
    assert len(all_names) == 11
    assert all(name.startswith(resources.prefix + "-") for name in all_names)
    assert len(set(resources.networks)) == 3
    assert len(set(resources.volumes)) == 5
    assert workflow._labels() == (
        "--label",
        f"{rehearsal.RESOURCE_LABEL}=1",
        "--label",
        f"{rehearsal.RUN_LABEL}=0123456789ab",
    )


def test_required_asset_catalog_has_exactly_thirteen_correct_mime_contracts() -> None:
    expected = {
        "/static/core/brand/favicon.ico": {"image/x-icon", "image/vnd.microsoft.icon"},
        "/static/core/brand/apple-touch-icon.png": {"image/png"},
        "/static/core/brand/site.webmanifest": {"application/manifest+json"},
        "/static/core/brand.css": {"text/css"},
        "/static/core/brand/maru_rectangle_full_logo.png": {"image/png"},
        "/static/core/brand/android-chrome-192x192.png": {"image/png"},
        "/static/core/brand/android-chrome-512x512.png": {"image/png"},
        "/static/core/brand/maru_square_logo_no_text.png": {"image/png"},
        ("/static/drf_spectacular_sidecar/swagger-ui-dist/swagger-ui.css"): {
            "text/css"
        },
        ("/static/drf_spectacular_sidecar/swagger-ui-dist/swagger-ui-bundle.js"): {
            "application/javascript",
            "text/javascript",
        },
        (
            "/static/drf_spectacular_sidecar/swagger-ui-dist/"
            "swagger-ui-standalone-preset.js"
        ): {"application/javascript", "text/javascript"},
        ("/static/drf_spectacular_sidecar/swagger-ui-dist/favicon-32x32.png"): {
            "image/png"
        },
        ("/static/drf_spectacular_sidecar/redoc/bundles/redoc.standalone.js"): {
            "application/javascript",
            "text/javascript",
        },
    }

    assert len(rehearsal.REQUIRED_STATIC_ASSETS) == 13
    assert frozenset(expected) == rehearsal.REQUIRED_STATIC_ASSETS
    for path, mime_types in expected.items():
        suffix = path.rsplit(".", 1)[-1]
        assert rehearsal.EXPECTED_MIME_TYPES[f".{suffix}"] == frozenset(mime_types)


def test_redoc_local_logo_is_a_complete_transparent_gif_data_url() -> None:
    prefix, encoded = rehearsal.REDOC_LOCAL_LOGO_DATA_URL.split(b",", 1)

    assert prefix == b"data:image/gif;base64"
    decoded = base64.b64decode(encoded, validate=True)
    assert len(decoded) == 42
    assert decoded.startswith(b"GIF89a")
    assert b"\x21\xf9\x04\x01" in decoded
    assert decoded.endswith(b";")


def test_manifest_parser_accepts_only_canonical_regular_file_evidence() -> None:
    parsed = rehearsal.OciStaticDeliveryRehearsal._parse_static_manifest(
        _valid_manifest_payload(),
        stage="test",
    )

    assert list(parsed) == ["core/brand.css", "core/brand/favicon.ico"]
    assert parsed["core/brand.css"] == rehearsal.StaticFileEvidence(
        path="core/brand.css",
        size=12,
        sha256="a" * 64,
    )
    assert (
        len(rehearsal.OciStaticDeliveryRehearsal._static_manifest_digest(parsed)) == 64
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2, "files": []},
        {"schema_version": 1, "files": []},
        {
            "schema_version": 1,
            "files": [{"path": "/absolute.css", "sha256": "a" * 64, "size": 1}],
        },
        {
            "schema_version": 1,
            "files": [{"path": "../escape.css", "sha256": "a" * 64, "size": 1}],
        },
        {
            "schema_version": 1,
            "files": [{"path": "core\\bad.css", "sha256": "a" * 64, "size": 1}],
        },
        {
            "schema_version": 1,
            "files": [{"path": "core/bad.css", "sha256": "A" * 64, "size": 1}],
        },
        {
            "schema_version": 1,
            "files": [{"path": "core/bad.css", "sha256": "a" * 64, "size": True}],
        },
        {
            "schema_version": 1,
            "files": [
                {"path": "same.css", "sha256": "a" * 64, "size": 1},
                {"path": "same.css", "sha256": "a" * 64, "size": 1},
            ],
        },
        {
            "schema_version": 1,
            "files": [
                {"path": "z.css", "sha256": "a" * 64, "size": 1},
                {"path": "a.css", "sha256": "b" * 64, "size": 1},
            ],
        },
    ],
)
def test_manifest_parser_rejects_unsafe_or_noncanonical_payloads(
    payload: dict[str, object],
) -> None:
    with pytest.raises(rehearsal.RehearsalError, match="static_manifest"):
        rehearsal.OciStaticDeliveryRehearsal._parse_static_manifest(
            payload,
            stage="test",
        )


def test_static_volume_requires_exact_manifest_equality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    manifest = workflow._parse_static_manifest(_valid_manifest_payload(), stage="test")
    workflow._image_manifest = manifest
    workflow._manifest_digest = workflow._static_manifest_digest(manifest)
    workflow.evidence["static_manifest"] = {}
    monkeypatch.setattr(workflow, "_static_manifest_job", lambda **_kwargs: manifest)

    workflow.populate_static_volume()

    assert workflow.evidence["static_manifest"] == {"image_volume_exact_match": True}
    drifted = dict(manifest)
    drifted["core/brand.css"] = replace(
        manifest["core/brand.css"],
        sha256="c" * 64,
    )
    monkeypatch.setattr(workflow, "_static_manifest_job", lambda **_kwargs: drifted)
    with pytest.raises(rehearsal.RehearsalError, match="static_volume_drift"):
        workflow.populate_static_volume()


def test_generated_demo_password_reaches_bootstrap_only_through_stdin(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    secret = workflow._secrets["demo_password"]

    workflow._app_job(
        stage="test",
        command=("python", "-c", rehearsal.DEMO_BOOTSTRAP_SOURCE),
        input_text=secret,
    )

    arguments, input_text = next(
        call for call in runner.calls if "--interactive" in call[0]
    )
    serialized = " ".join(arguments)
    assert input_text == secret
    assert secret not in serialized
    assert "--interactive" in arguments
    assert "password = sys.stdin.read()" in rehearsal.DEMO_BOOTSTRAP_SOURCE
    assert "DEMO_ACCOUNT_PASSWORD" not in rehearsal.DEMO_BOOTSTRAP_SOURCE
    assert "PGPASSFILE=/run/secrets/value" in arguments
    assert "postgresql://maru_static@postgres:5432/maru" in serialized


def test_secret_volume_content_is_never_an_argument_or_environment(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    secret = workflow._secrets["database"]

    workflow._create_secret_volume(
        volume=workflow.resources.postgres_secret_volume,
        content=secret,
        owner="0:0",
        stage="test",
    )

    arguments, input_text = next(
        call for call in runner.calls if "--interactive" in call[0]
    )
    assert input_text == secret
    assert secret not in " ".join(arguments)
    assert "--interactive" in arguments
    assert "--network" in arguments
    assert arguments[arguments.index("--network") + 1] == "none"


def test_edge_config_is_snapshotted_through_stdin_into_a_run_owned_volume(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    source = rehearsal.EDGE_CONFIG_PATH.read_text(encoding="utf-8")
    workflow._config_source = source
    workflow._config_digest = runner.config_digest
    workflow._config_bytes = source.encode("utf-8")

    workflow._create_config_volume(stage="test")

    arguments, input_text = next(
        call for call in runner.calls if "--interactive" in call[0]
    )
    assert input_text == source.encode("utf-8")
    assert source not in " ".join(arguments)
    assert any(workflow.resources.config_volume in value for value in arguments)
    assert any("volume-nocopy" in value for value in arguments)
    assert arguments[arguments.index("--network") + 1] == "none"
    assert arguments[arguments.index("--user") + 1] == "0:0"
    assert "--read-only" in arguments
    assert "no-new-privileges:true" in arguments
    validation = runner.calls[-1][0]
    assert any("readonly,volume-nocopy" in value for value in validation)
    assert any("sha256sum /config/default.conf" in value for value in validation)


def test_app_and_edge_are_hardened_and_only_edge_publishes_loopback(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    workflow._config_digest = runner.config_digest
    workflow._config_source = runner.config_source
    workflow._config_bytes = runner.config_source.encode("utf-8")

    workflow._start_web(stage="test")
    workflow._start_edge(stage="test")

    commands = [command for command, _input in runner.calls]
    web = next(command for command in commands if workflow.resources.web in command)
    edge = next(
        command
        for command in commands
        if command[:2] == ("docker", "create") and workflow.resources.edge in command
    )
    assert "--publish" not in web
    assert "--user" in web
    assert web[web.index("--user") + 1] == "10001:10001"
    assert "--read-only" in web
    assert "--cap-drop" in web
    assert web[web.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges:true" in web
    assert workflow.resources.backend_network in web
    assert any(
        command[:3] == ("docker", "network", "connect")
        and workflow.resources.proxy_network in command
        and workflow.resources.web in command
        for command in commands
    )
    assert "--publish" in edge
    assert edge[edge.index("--publish") + 1] == "127.0.0.1::8080"
    assert "--user" in edge
    assert edge[edge.index("--user") + 1] == "101:101"
    assert "--read-only" in edge
    assert "--cap-drop" in edge
    assert edge[edge.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges:true" in edge
    assert workflow.resources.ingress_network in edge
    assert any(
        command[:3] == ("docker", "network", "connect")
        and workflow.resources.proxy_network in command
        and workflow.resources.edge in command
        for command in commands
    )
    assert any("target=/srv/maru/static,readonly" in value for value in edge)
    assert any("target=/etc/nginx/conf.d,readonly" in value for value in edge)
    assert any(f"size={rehearsal.TMPFS_SIZE_BYTES}" in value for value in web)
    assert any(f"size={rehearsal.TMPFS_SIZE_BYTES}" in value for value in edge)
    assert all("docker.sock" not in value for value in edge)
    assert workflow._edge_origin == "http://127.0.0.1:49152"
    serialized = " ".join(" ".join(command) for command in commands)
    assert all(secret not in serialized for secret in workflow._secrets.values())


def test_container_hardening_validator_fails_closed() -> None:
    inspection: dict[str, object] = {
        "Config": {"User": "101:101"},
        "HostConfig": {
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "Privileged": False,
            "ReadonlyRootfs": True,
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": {
                rehearsal.TMPFS_PATH: (
                    "rw,noexec,nosuid,nodev,mode=0700,uid=101,gid=101,"
                    f"size={rehearsal.TMPFS_SIZE_BYTES}"
                )
            },
        },
    }
    rehearsal.OciStaticDeliveryRehearsal._require_hardened_container(
        inspection,
        expected_user=rehearsal.EXPECTED_EDGE_USER,
        stage="test",
    )
    invalid = json.loads(json.dumps(inspection))
    invalid["HostConfig"]["ReadonlyRootfs"] = False
    with pytest.raises(rehearsal.RehearsalError, match="container_hardening_invalid"):
        rehearsal.OciStaticDeliveryRehearsal._require_hardened_container(
            invalid,
            expected_user=rehearsal.EXPECTED_EDGE_USER,
            stage="test",
        )
    privileged = json.loads(json.dumps(inspection))
    privileged["HostConfig"]["Privileged"] = True
    with pytest.raises(rehearsal.RehearsalError, match="container_hardening_invalid"):
        rehearsal.OciStaticDeliveryRehearsal._require_hardened_container(
            privileged,
            expected_user=rehearsal.EXPECTED_EDGE_USER,
            stage="test",
        )
    capability_added = json.loads(json.dumps(inspection))
    capability_added["HostConfig"]["CapAdd"] = ["NET_ADMIN"]
    with pytest.raises(rehearsal.RehearsalError, match="container_hardening_invalid"):
        rehearsal.OciStaticDeliveryRehearsal._require_hardened_container(
            capability_added,
            expected_user=rehearsal.EXPECTED_EDGE_USER,
            stage="test",
        )
    unbounded = json.loads(json.dumps(inspection))
    unbounded["HostConfig"]["Tmpfs"][rehearsal.TMPFS_PATH] = (
        "rw,noexec,nosuid,nodev,mode=0700,uid=101,gid=101"
    )
    with pytest.raises(rehearsal.RehearsalError, match="container_tmpfs_invalid"):
        rehearsal.OciStaticDeliveryRehearsal._require_hardened_container(
            unbounded,
            expected_user=rehearsal.EXPECTED_EDGE_USER,
            stage="test",
        )


@pytest.mark.parametrize("requested_host_port", ["", "49152"])
def test_edge_binding_accepts_ephemeral_request_and_requires_allocated_loopback(
    requested_host_port: str,
) -> None:
    inspection: dict[str, object] = {
        "HostConfig": {
            "PortBindings": {
                "8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": requested_host_port}]
            }
        },
        "NetworkSettings": {
            "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49152"}]}
        },
    }

    rehearsal.OciStaticDeliveryRehearsal._require_edge_loopback_binding(
        inspection,
        host_port=49152,
        stage="test",
    )

    wrong_runtime = json.loads(json.dumps(inspection))
    wrong_runtime["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"] = "49153"
    with pytest.raises(rehearsal.RehearsalError, match="edge_port_binding_invalid"):
        rehearsal.OciStaticDeliveryRehearsal._require_edge_loopback_binding(
            wrong_runtime,
            host_port=49152,
            stage="test",
        )

    public_binding = json.loads(json.dumps(inspection))
    public_binding["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostIp"] = "0.0.0.0"  # noqa: S104 - intentional rejection case
    with pytest.raises(rehearsal.RehearsalError, match="edge_port_binding_invalid"):
        rehearsal.OciStaticDeliveryRehearsal._require_edge_loopback_binding(
            public_binding,
            host_port=49152,
            stage="test",
        )


def test_container_network_membership_parser_is_exact_and_fails_closed() -> None:
    inspection: dict[str, object] = {
        "NetworkSettings": {"Networks": {"database": {}, "proxy": {}}}
    }
    assert rehearsal.OciStaticDeliveryRehearsal._container_networks(
        inspection,
        stage="test",
    ) == frozenset({"database", "proxy"})

    malformed: dict[str, object] = {
        "NetworkSettings": {"Networks": {"database": "unexpected"}}
    }
    with pytest.raises(rehearsal.RehearsalError, match="container_inspection_invalid"):
        rehearsal.OciStaticDeliveryRehearsal._container_networks(
            malformed,
            stage="test",
        )


def test_exact_named_mount_validator_rejects_extra_or_writable_mounts() -> None:
    expected = {"/srv/maru/static": ("run-static", False)}
    mounts: list[dict[str, object]] = [
        {
            "Destination": "/srv/maru/static",
            "Type": "volume",
            "Name": "run-static",
            "RW": False,
        }
    ]
    rehearsal.OciStaticDeliveryRehearsal._require_exact_named_mounts(
        mounts,
        expected=expected,
        stage="test",
    )

    extra = [
        *mounts,
        {
            "Destination": "/credential",
            "Type": "bind",
            "Source": "C:/unexpected",
            "RW": True,
        },
    ]
    with pytest.raises(rehearsal.RehearsalError, match="mount_boundary_invalid"):
        rehearsal.OciStaticDeliveryRehearsal._require_exact_named_mounts(
            extra,
            expected=expected,
            stage="test",
        )

    writable = json.loads(json.dumps(mounts))
    writable[0]["RW"] = True
    with pytest.raises(rehearsal.RehearsalError, match="mount_boundary_invalid"):
        rehearsal.OciStaticDeliveryRehearsal._require_exact_named_mounts(
            writable,
            expected=expected,
            stage="test",
        )


def test_nginx_config_separates_exact_static_and_dynamic_boundaries() -> None:
    source = rehearsal.EDGE_CONFIG_PATH.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == (
        rehearsal.EXPECTED_EDGE_CONFIG_SHA256
    )
    assert rehearsal.edge_config_is_safe(source)
    manifest_start = source.index("location = /static/core/brand/site.webmanifest {")
    static_start = source.index("location ^~ /static/ {")
    dynamic_start = source.index("location / {")
    static_source = source[manifest_start:dynamic_start]
    dynamic_source = source[dynamic_start:]
    redoc_start = source.index(f"location = {rehearsal.REDOC_BUNDLE_PATH} {{")
    redoc_end = source.index("location = /static {", redoc_start)
    redoc_source = source[redoc_start:redoc_end]

    assert "root /srv/maru;" in static_source
    assert "default_type application/manifest+json;" in static_source
    assert static_source.count("try_files $uri =404;") == 3
    assert static_source.count("limit_except GET") == 3
    assert (
        static_source.count(
            'add_header Cache-Control "public, max-age=0, must-revalidate" always;'
        )
        == 4
    )
    assert "X-Content-Type-Options nosniff always" in static_source
    assert "proxy_pass" not in static_source
    assert (
        "immutable"
        not in "\n".join(
            line for line in source.splitlines() if "Cache-Control" in line
        ).casefold()
    )
    assert source.index("location = /static {") < static_start
    assert source.count("proxy_pass ") == 1
    assert "proxy_pass http://maru-web:8000;" in dynamic_source
    assert "location ^~ /media/" in static_source
    assert 'add_header Cache-Control "no-store" always;' in static_source
    assert "proxy_cache off;" in dynamic_source
    assert (
        r'if ($request_uri ~* "^(?:/|%2f|%5c|\\x5c)+'
        r'static(?:/|%2f|%5c|\\x5c)") {' in dynamic_source
    )
    assert (
        r'if ($request_uri ~* "^(?:/|%2f|%5c|\\x5c)+'
        r'media(?:/|%2f|%5c|\\x5c)") {' in dynamic_source
    )
    assert (
        r'if ($request_uri ~* "^[^?]*(?:/|%2f|%5c|\\x5c)'
        r'(?:[.]|%2e){1,2}(?:/|%2f|%5c|\\x5c|[?]|$)") {' in dynamic_source
    )
    assert "sub_filter" not in dynamic_source
    assert "Accept-Encoding" not in dynamic_source
    assert "max_ranges 0;" in redoc_source
    assert "etag off;" in redoc_source
    assert "if_modified_since off;" in redoc_source
    assert "gzip off;" in redoc_source
    assert (
        'set $redoc_precondition "$request_method:$http_if_none_match";' in redoc_source
    )
    assert 'if ($redoc_precondition ~ "^(GET|HEAD):[*]$") {' in redoc_source
    assert "return 304;" in redoc_source
    assert "sub_filter_types application/javascript;" in redoc_source
    assert "sub_filter_once on;" in redoc_source
    assert "sub_filter_last_modified off;" in redoc_source
    assert (
        "sub_filter 'https://cdn.redoc.ly/redoc/logo-mini.svg' "
        "'data:image/gif;base64,"
        "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';" in redoc_source
    )
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in dynamic_source
    assert "proxy_set_header X-Forwarded-Host $http_host;" in dynamic_source
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in dynamic_source
    assert 'proxy_set_header X-Forwarded-Port "";' in dynamic_source
    assert 'proxy_set_header X-Forwarded-Prefix "";' in dynamic_source
    assert "$proxy_add_x_forwarded_for" not in dynamic_source
    cleared_forwarded = "proxy_set_header Forwarded " + json.dumps("") + ";"
    assert cleared_forwarded in dynamic_source


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("location = /static {", "location = /static-renamed {"),
        ("location ^~ /media/ {", "location ^~ /uploads/ {"),
        ("limit_except GET", "limit_except POST"),
        ('proxy_set_header Forwarded "";', ""),
        ("proxy_set_header X-Forwarded-Proto $scheme;", ""),
        ('proxy_set_header X-Forwarded-Port "";', ""),
        ('proxy_set_header X-Forwarded-Prefix "";', ""),
        (
            f"location = {rehearsal.REDOC_BUNDLE_PATH} {{",
            "location = /static/redoc.js {",
        ),
        ("max_ranges 0;", "max_ranges 1;"),
        ("if_modified_since off;", "if_modified_since exact;"),
        ("gzip off;", "gzip on;"),
        (
            'if ($redoc_precondition ~ "^(GET|HEAD):[*]$") {',
            'if ($redoc_precondition ~ "^GET:[*]$") {',
        ),
        (
            r'if ($request_uri ~* "^(?:/|%2f|%5c|\\x5c)+'
            r'static(?:/|%2f|%5c|\\x5c)") {',
            r'if ($request_uri ~* "^(?:/|%2f|%5c|\\x5c)+'
            r'assets(?:/|%2f|%5c|\\x5c)") {',
        ),
        (
            r'if ($request_uri ~* "^(?:/|%2f|%5c|\\x5c)+'
            r'media(?:/|%2f|%5c|\\x5c)") {',
            r'if ($request_uri ~* "^(?:/|%2f|%5c|\\x5c)+'
            r'uploads(?:/|%2f|%5c|\\x5c)") {',
        ),
        (
            r'if ($request_uri ~* "^[^?]*(?:/|%2f|%5c|\\x5c)'
            r'(?:[.]|%2e){1,2}(?:/|%2f|%5c|\\x5c|[?]|$)") {',
            r'if ($request_uri ~* "^[^?]*(?:/|%2f|%5c|\\x5c)'
            r'(?:[.]|%2e){3}(?:/|%2f|%5c|\\x5c|[?]|$)") {',
        ),
        ("sub_filter_last_modified off;", "sub_filter_last_modified on;"),
        (
            "https://cdn.redoc.ly/redoc/logo-mini.svg",
            "https://cdn.redoc.ly/redoc/other.svg",
        ),
    ],
)
def test_nginx_config_safety_pin_rejects_semantic_mutations(old: str, new: str) -> None:
    source = rehearsal.EDGE_CONFIG_PATH.read_text(encoding="utf-8")

    assert old in source
    assert not rehearsal.edge_config_is_safe(source.replace(old, new, 1))


def test_edge_namespace_escape_requires_compact_edge_owned_404() -> None:
    rehearsal.OciStaticDeliveryRehearsal._require_edge_owned_not_found(
        rehearsal.HttpResult(404, {}, b"edge denial"),
        stage="test",
    )

    invalid_results = (
        None,
        rehearsal.HttpResult(200, {}, b'{"status":"ok"}'),
        rehearsal.HttpResult(404, {"x-request-id": "synthetic"}, b"Django"),
        rehearsal.HttpResult(
            404,
            {},
            b"x" * (rehearsal.MAX_EDGE_DENIAL_BYTES + 1),
        ),
    )
    for result in invalid_results:
        with pytest.raises(
            rehearsal.RehearsalError,
            match="edge_namespace_escape_invalid",
        ):
            rehearsal.OciStaticDeliveryRehearsal._require_edge_owned_not_found(
                result,
                stage="test",
            )


@pytest.mark.parametrize(
    "cache_control",
    [
        "public, max-age=0, must-revalidate",
        "private, immutable",
    ],
)
def test_dynamic_response_rejects_static_or_immutable_cache_class(
    cache_control: str,
) -> None:
    result = rehearsal.HttpResult(200, {"cache-control": cache_control}, b"{}")

    with pytest.raises(
        rehearsal.RehearsalError, match="dynamic_cache_boundary_invalid"
    ):
        rehearsal.OciStaticDeliveryRehearsal._require_dynamic_cache_separation(
            result,
            stage="test",
        )


def test_static_response_requires_exact_bytes_mime_cache_nosniff_and_304(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    body = b":root { color: #071b3a; }"
    workflow._image_manifest = {
        "core/brand.css": rehearsal.StaticFileEvidence(
            path="core/brand.css",
            size=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
        )
    }
    result = rehearsal.HttpResult(200, _static_headers(), body)
    conditional_headers: list[Mapping[str, str] | None] = []
    monkeypatch.setattr(workflow, "_wait_for_status", lambda *_args, **_kwargs: result)

    def conditional_request(
        _path: str,
        *,
        headers: Mapping[str, str] | None = None,
        **_kwargs: object,
    ) -> rehearsal.HttpResult:
        conditional_headers.append(headers)
        return rehearsal.HttpResult(304, {}, b"")

    monkeypatch.setattr(workflow, "_request", conditional_request)

    workflow._verify_one_static_asset("/static/core/brand.css", stage="test")

    assert conditional_headers == [{"if-none-match": '"candidate-etag"'}]


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("body", "static_response_drift"),
        ("mime", "static_mime_invalid"),
        ("cache", "static_cache_boundary_invalid"),
        ("nosniff", "static_nosniff_missing"),
        ("validator", "static_validator_missing"),
    ],
)
def test_static_response_validation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    error_code: str,
) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    body = b"canonical"
    workflow._image_manifest = {
        "core/brand.css": rehearsal.StaticFileEvidence(
            path="core/brand.css",
            size=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
        )
    }
    headers = _static_headers()
    response_body = body
    if mutation == "body":
        response_body = b"different"
    elif mutation == "mime":
        headers["content-type"] = "application/octet-stream"
    elif mutation == "cache":
        headers["cache-control"] = "public, max-age=0"
    elif mutation == "nosniff":
        headers.pop("x-content-type-options")
    else:
        headers.pop("etag")
    result = rehearsal.HttpResult(200, headers, response_body)
    monkeypatch.setattr(workflow, "_wait_for_status", lambda *_args, **_kwargs: result)

    with pytest.raises(rehearsal.RehearsalError, match=error_code):
        workflow._verify_one_static_asset("/static/core/brand.css", stage="test")


def test_private_documentation_headers_are_exact_and_fail_closed() -> None:
    valid = rehearsal.HttpResult(200, _private_headers(), b"{}")
    rehearsal.OciStaticDeliveryRehearsal._require_private_documentation_headers(
        valid,
        stage="test",
    )
    for header in (
        "cache-control",
        "pragma",
        "x-robots-tag",
        "cross-origin-opener-policy",
    ):
        invalid_headers = _private_headers()
        invalid_headers.pop(header)
        with pytest.raises(
            rehearsal.RehearsalError,
            match="private_documentation_headers_invalid",
        ):
            rehearsal.OciStaticDeliveryRehearsal._require_private_documentation_headers(
                rehearsal.HttpResult(200, invalid_headers, b"{}"),
                stage="test",
            )


def test_redoc_edge_representation_is_exact_and_probes_cannot_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"prefix:" + rehearsal.REDOC_REMOTE_LOGO_URL + b":suffix"
    transformed = source.replace(
        rehearsal.REDOC_REMOTE_LOGO_URL,
        rehearsal.REDOC_LOCAL_LOGO_DATA_URL,
        1,
    )
    monkeypatch.setattr(rehearsal, "REDOC_BUNDLE_SOURCE_SIZE", len(source))
    monkeypatch.setattr(
        rehearsal,
        "REDOC_BUNDLE_SOURCE_SHA256",
        hashlib.sha256(source).hexdigest(),
    )
    monkeypatch.setattr(rehearsal, "REDOC_BUNDLE_EDGE_SIZE", len(transformed))
    monkeypatch.setattr(
        rehearsal,
        "REDOC_BUNDLE_EDGE_SHA256",
        hashlib.sha256(transformed).hexdigest(),
    )
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    relative_path = rehearsal.REDOC_BUNDLE_PATH.removeprefix("/static/")
    workflow._image_manifest = {
        relative_path: rehearsal.StaticFileEvidence(
            path=relative_path,
            size=len(source),
            sha256=hashlib.sha256(source).hexdigest(),
        )
    }
    headers = _static_headers("application/javascript")
    headers.pop("etag")
    result = rehearsal.HttpResult(200, headers, transformed)
    monkeypatch.setattr(workflow, "_wait_for_status", lambda *_a, **_k: result)
    probe_requests: list[tuple[str, Mapping[str, str] | None]] = []

    def range_request(
        _path: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        **_kwargs: object,
    ) -> rehearsal.HttpResult:
        probe_requests.append((method, headers))
        if headers == {"If-None-Match": "*"}:
            status = (
                rehearsal.HTTP_NOT_MODIFIED
                if method in {"GET", "HEAD"}
                else rehearsal.HTTP_FORBIDDEN
            )
            response_headers = (
                {
                    "cache-control": "public, max-age=0, must-revalidate",
                    "x-content-type-options": "nosniff",
                }
                if status == rehearsal.HTTP_NOT_MODIFIED
                else {}
            )
            return rehearsal.HttpResult(status, response_headers, b"")
        return result

    monkeypatch.setattr(workflow, "_request", range_request)

    workflow._verify_one_static_asset(rehearsal.REDOC_BUNDLE_PATH, stage="test")

    assert probe_requests == [
        ("GET", {"If-None-Match": "*"}),
        ("HEAD", {"If-None-Match": "*"}),
        ("POST", {"If-None-Match": "*"}),
        ("GET", {"If-None-Match": '"candidate-source"'}),
        ("GET", {"Range": "bytes=0-255"}),
        ("GET", {"If-Modified-Since": "Wed, 31 Dec 2099 23:59:59 GMT"}),
    ]
    entry = workflow._image_manifest[relative_path]
    with pytest.raises(
        rehearsal.RehearsalError,
        match="redoc_edge_transform_invalid",
    ):
        workflow._require_redoc_edge_representation(
            entry,
            rehearsal.HttpResult(200, headers, source),
            stage="test",
        )
    with pytest.raises(
        rehearsal.RehearsalError,
        match="redoc_edge_header_invalid",
    ):
        workflow._require_redoc_edge_representation(
            entry,
            rehearsal.HttpResult(200, {**headers, "etag": '"source"'}, transformed),
            stage="test",
        )


def test_private_documentation_requests_json_and_keeps_sidecars_same_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    workflow._edge_origin = "http://127.0.0.1:49152"
    schema_headers = {
        **_private_headers(),
        "content-type": "application/vnd.oai.openapi+json",
    }
    swagger = (
        b'<html><link href="/static/drf_spectacular_sidecar/swagger-ui-dist/'
        b'swagger-ui.css"><link href="/static/drf_spectacular_sidecar/'
        b'swagger-ui-dist/favicon-32x32.png"><script src="/static/'
        b'drf_spectacular_sidecar/swagger-ui-dist/swagger-ui-bundle.js"></script>'
        b'<script src="/static/drf_spectacular_sidecar/swagger-ui-dist/'
        b'swagger-ui-standalone-preset.js"></script>/api/v1/schema</html>'
    )
    redoc = (
        b'<html><script src="/static/drf_spectacular_sidecar/redoc/bundles/'
        b'redoc.standalone.js"></script>/api/v1/schema</html>'
    )
    schema_accept_headers: list[Mapping[str, str] | None] = []

    def wait_for_status(
        path: str,
        _expected: frozenset[int],
        *,
        stage: str,
        headers: Mapping[str, str] | None = None,
    ) -> rehearsal.HttpResult:
        _ = stage
        if path == "/api/v1/schema":
            schema_accept_headers.append(headers)
            status = 403 if len(schema_accept_headers) == 1 else 200
            body = b"{}" if status == 403 else b'{"openapi":"3.1.0"}'
            return rehearsal.HttpResult(status, schema_headers, body)
        if path == "/api/v1/docs/":
            return rehearsal.HttpResult(
                200,
                {**_private_headers(), "content-type": "text/html"},
                swagger,
            )
        return rehearsal.HttpResult(
            200,
            {**_private_headers(), "content-type": "text/html"},
            redoc,
        )

    def anonymous_request(path: str, **_kwargs: object) -> rehearsal.HttpResult:
        return rehearsal.HttpResult(
            302,
            {
                "cache-control": "private, no-store, max-age=0",
                "location": f"/accounts/login/?next={path}",
            },
            b"",
        )

    monkeypatch.setattr(workflow, "_wait_for_status", wait_for_status)
    monkeypatch.setattr(workflow, "_request", anonymous_request)
    monkeypatch.setattr(
        workflow,
        "_login_synthetic_administrator",
        lambda **_kwargs: set(rehearsal.LOGIN_ASSETS),
    )
    monkeypatch.setattr(workflow, "_verify_one_static_asset", lambda *_a, **_k: None)

    workflow.verify_private_api_documentation()

    assert schema_accept_headers == [
        {"Accept": "application/vnd.oai.openapi+json"},
        {"Accept": "application/vnd.oai.openapi+json"},
    ]
    assert workflow._documentation_references == set(rehearsal.DOCUMENTATION_ASSETS)
    assert (
        workflow.evidence["stages"][-1]["details"]["third_party_server_html_references"]
        == 0
    )
    assert (
        workflow.evidence["stages"][-1]["details"][
            "redoc_remote_logo_localized_at_edge"
        ]
        is True
    )
    assert workflow.evidence["stages"][-1]["details"]["redoc_source_bundle"] == {
        "sha256": rehearsal.REDOC_BUNDLE_SOURCE_SHA256,
        "size": rehearsal.REDOC_BUNDLE_SOURCE_SIZE,
    }
    assert workflow.evidence["stages"][-1]["details"]["redoc_edge_representation"] == {
        "sha256": rehearsal.REDOC_BUNDLE_EDGE_SHA256,
        "size": rehearsal.REDOC_BUNDLE_EDGE_SIZE,
    }


@pytest.mark.parametrize(
    "reference",
    [
        "https://cdn.jsdelivr.net/npm/swagger-ui.css",
        "//fonts.googleapis.com/css?family=Inter",
        "http://127.0.0.1:49999/static/other.js",
        "data:text/javascript,alert(1)",
    ],
)
def test_third_party_or_wrong_origin_references_are_rejected(
    tmp_path: Path,
    reference: str,
) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    workflow._edge_origin = "http://127.0.0.1:49152"

    with pytest.raises(rehearsal.RehearsalError, match="third_party_asset_reference"):
        workflow._same_origin_paths([reference], stage="test")


@pytest.mark.parametrize(
    "reference",
    [
        "/api/v1/generated-sidecar.js",
        "http://127.0.0.1:49152/private/generated-sidecar.css",
    ],
)
def test_documentation_rejects_same_origin_non_static_references(
    tmp_path: Path,
    reference: str,
) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    workflow._edge_origin = "http://127.0.0.1:49152"

    with pytest.raises(
        rehearsal.RehearsalError,
        match="documentation_non_static_asset_reference",
    ):
        workflow._documentation_static_paths([reference], stage="test")


def test_documentation_accepts_same_origin_static_reference_with_query(
    tmp_path: Path,
) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    workflow._edge_origin = "http://127.0.0.1:49152"

    assert workflow._documentation_static_paths(
        ["/static/sidecar.js?v=1"],
        stage="test",
    ) == {"/static/sidecar.js"}


def test_evidence_rejects_secrets_identity_cookies_private_html_and_urls(
    tmp_path: Path,
) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))

    assert workflow._evidence_is_sanitized({"status": "passed", "count": 13})
    forbidden = (
        workflow._secrets["database"],
        workflow._secrets["demo_password"],
        rehearsal.DEMO_ADMIN_EMAIL,
        "csrftoken=synthetic",
        "sessionid=synthetic",
        "Set-Cookie: private",
        "Authorization: secret",
        "<!doctype html><html></html>",
        "postgresql://maru_static@postgres/maru",
    )
    for value in forbidden:
        assert not workflow._evidence_is_sanitized({"value": value})
    with pytest.raises(rehearsal.RehearsalError, match="evidence_not_sanitized"):
        workflow._record("test", {"value": workflow._secrets["demo_password"]})


def _arguments(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "app_image": rehearsal.DEFAULT_APPLICATION_IMAGE,
        "expected_source_revision": rehearsal.DEFAULT_SOURCE_REVISION,
        "edge_image": rehearsal.DEFAULT_EDGE_IMAGE,
        "run_id": "0123456789ab",
        "evidence": None,
        "retain_resources": False,
        "retain_on_failure": False,
        "command_timeout_seconds": 600,
        "http_timeout_seconds": 120,
        "cleanup_retained": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_configuration_keeps_evidence_below_ignored_local_directory() -> None:
    configuration = rehearsal.configuration_from_arguments(_arguments())

    assert configuration.evidence_path == (
        rehearsal.REPOSITORY_ROOT
        / ".local-ci"
        / "oci-static-delivery"
        / "0123456789ab.json"
    )
    with pytest.raises(ValueError, match=r"below \.local-ci"):
        rehearsal.configuration_from_arguments(
            _arguments(evidence=rehearsal.REPOSITORY_ROOT / "unsafe.json")
        )
    with pytest.raises(ValueError, match="timeouts"):
        rehearsal.configuration_from_arguments(_arguments(http_timeout_seconds=1))


def test_evidence_writer_rechecks_path_and_writes_only_sanitized_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rehearsal, "REPOSITORY_ROOT", tmp_path)
    configuration = _configuration(tmp_path)
    workflow = rehearsal.OciStaticDeliveryRehearsal(configuration)

    workflow._write_evidence()

    written = json.loads(configuration.evidence_path.read_text(encoding="utf-8"))
    assert written["run_id"] == "0123456789ab"
    outside = replace(configuration, evidence_path=tmp_path / "outside.json")
    with pytest.raises(rehearsal.RehearsalError, match="evidence_path_invalid"):
        rehearsal.OciStaticDeliveryRehearsal(outside)._write_evidence()


def test_interrupt_runs_bounded_cleanup_and_returns_conventional_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = rehearsal.OciStaticDeliveryRehearsal(_configuration(tmp_path))
    cleanup_called = False

    def interrupt(_workflow: rehearsal.OciStaticDeliveryRehearsal) -> None:
        raise KeyboardInterrupt

    def cleanup(
        _workflow: rehearsal.OciStaticDeliveryRehearsal,
        *,
        require_present: bool = False,
    ) -> int:
        nonlocal cleanup_called
        _ = require_present
        cleanup_called = True
        return 0

    monkeypatch.setattr(
        rehearsal.OciStaticDeliveryRehearsal,
        "verify_artifacts",
        interrupt,
    )
    monkeypatch.setattr(rehearsal.OciStaticDeliveryRehearsal, "cleanup", cleanup)
    monkeypatch.setattr(
        rehearsal.OciStaticDeliveryRehearsal,
        "_write_evidence",
        lambda _workflow: None,
    )

    assert workflow.execute() == 130
    assert cleanup_called
    assert workflow.evidence["failure"] == {
        "code": "interrupted",
        "stage": "verify_artifacts",
        "details_disclosed": False,
    }


def test_cleanup_removes_only_complete_exact_label_verified_namespace(
    tmp_path: Path,
) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    _seed_complete_run(runner, workflow)

    removed = workflow.cleanup(require_present=True)

    assert removed == 12
    assert not any(runner.resources.values())


def test_cleanup_refuses_foreign_labels_before_any_removal(tmp_path: Path) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
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
        workflow.cleanup()

    assert not any(_is_remove(command) for command in runner.calls)


def test_cleanup_refuses_unexpected_owned_or_uninventoriable_resources(
    tmp_path: Path,
) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    runner.add("container", "maru-static-unexpected", labels=_owned_labels())

    with pytest.raises(rehearsal.RehearsalError, match="cleanup_namespace_mismatch"):
        workflow.cleanup()
    assert not any(_is_remove(command) for command in runner.calls)

    runner.resources["container"].clear()
    runner.calls.clear()
    runner.fail_inventory_for.add("container")
    with pytest.raises(rehearsal.RehearsalError, match="command_failed"):
        workflow.cleanup()
    assert not any(_is_remove(command) for command in runner.calls)


def test_cleanup_requires_zero_final_inventory(tmp_path: Path) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    job = _seed_complete_run(runner, workflow)
    runner.preserve_on_remove.add(job)

    with pytest.raises(rehearsal.RehearsalError, match="cleanup_incomplete"):
        workflow.cleanup()


def test_retention_stops_every_container_without_changing_inventory(
    tmp_path: Path,
) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )
    _seed_complete_run(runner, workflow)
    before = {
        resource_type: set(resources)
        for resource_type, resources in runner.resources.items()
    }

    workflow.stop_for_retention()

    assert not runner.running
    assert {
        resource_type: set(resources)
        for resource_type, resources in runner.resources.items()
    } == before
    assert not any(_is_remove(command) for command in runner.calls)


def test_standalone_cleanup_requires_an_existing_exact_run(tmp_path: Path) -> None:
    runner = DockerStateRunner()
    workflow = rehearsal.OciStaticDeliveryRehearsal(
        _configuration(tmp_path),
        runner=runner,  # type: ignore[arg-type]
    )

    with pytest.raises(rehearsal.RehearsalError) as captured:
        workflow.cleanup(require_present=True)

    assert captured.value.code == "retained_run_not_found"
    assert not any(_is_remove(command) for command in runner.calls)
