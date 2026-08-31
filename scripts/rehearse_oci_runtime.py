"""Rehearse Maru's immutable OCI runtime against isolated PostgreSQL 17.

This executable evaluator path is intentionally synthetic.  It proves image
identity, migration/runtime database-role separation, exact authority
activation, public health behavior, and ordinary restart persistence without
claiming production infrastructure or recovery certification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_HELPER = REPOSITORY_ROOT / "scripts" / "oci_runtime_bootstrap.py"
PROVISIONING_SQL_PATH = (
    "docs/operations/postgresql-runtime-role-provisioning.sql.example"
)
DEFAULT_APPLICATION_IMAGE: Final = (
    "ghcr.io/martonpornoi/maru@"
    "sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445"
)
DEFAULT_SOURCE_REVISION: Final = "be0b21db9ba2d2a956bd192a1d66c537d702c4c4"
POSTGRES_IMAGE: Final = (
    "postgres:17.11-alpine@"
    "sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
)
# This digest belongs to DEFAULT_SOURCE_REVISION's immutable release artifact,
# not to the evolving provisioning example in the current checkout. Change it
# only with a reviewed image/source pair for a later immutable release.
EXPECTED_PROVISIONING_SQL_SHA256: Final = (
    "709f644dbea546351e210fd58c6fe5ee6a502882b0b94058c049412533f7b49e"
)
ADMIN_ROLE: Final = "maru_rehearsal_admin"
MIGRATION_ROLE: Final = "maru_migration"
RUNTIME_ROLE: Final = "maru_runtime"
DATABASE_NAME: Final = "maru"
RESOURCE_LABEL: Final = "io.maru.oci-runtime-rehearsal"
RUN_LABEL: Final = "io.maru.oci-runtime-rehearsal-run"
IMAGE_PATTERN = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}\Z")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
RUN_ID_PATTERN = re.compile(r"[0-9a-f]{12}\Z")
COMPATIBILITY_READY_DEPENDENCIES: Final[frozenset[str]] = frozenset(
    {
        "applications_integrity",
        "catalog_integrity",
        "charities_integrity",
        "database",
        "logistics",
        "venues_integrity",
    }
)
EXACT_READY_DEPENDENCIES: Final[frozenset[str]] = COMPATIBILITY_READY_DEPENDENCIES | {
    "authority_provenance"
}
EXACT_PREACTIVATION_DEPENDENCIES: Final[frozenset[str]] = frozenset(
    {"authority_provenance", "database"}
)
DATABASE_FAILURE_DEPENDENCIES: Final[frozenset[str]] = frozenset({"database"})
REQUIRED_PRODUCTION_GATES: Final[frozenset[str]] = frozenset(
    {
        "activation_marker",
        "database_completeness_guards",
        "exact_lineage_policy_cutover",
        "postgresql_server_major",
        "provenance_write_downgrade_fence",
        "runtime_database_role",
    }
)
DEFAULT_COMMAND_TIMEOUT_SECONDS: Final = 600
DEFAULT_HEALTH_TIMEOUT_SECONDS: Final = 120
MINIMUM_COMMAND_TIMEOUT_SECONDS: Final = 30
MINIMUM_HEALTH_TIMEOUT_SECONDS: Final = 10
HTTP_OK: Final = 200
HTTP_SERVICE_UNAVAILABLE: Final = 503
HTTP_PROBE_SOURCE: Final = """
import json
import sys
import urllib.error
import urllib.request

try:
    with urllib.request.urlopen(
        "http://127.0.0.1:8000" + sys.argv[1], timeout=3
    ) as response:
        status = response.status
        body = response.read()
except urllib.error.HTTPError as error:
    status = error.code
    body = error.read()
except (OSError, TimeoutError, urllib.error.URLError):
    raise SystemExit(3) from None

try:
    payload = json.loads(body)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit(4) from None
if not isinstance(payload, dict):
    raise SystemExit(5)
print(json.dumps({"http_status": status, "body": payload}, sort_keys=True))
"""

STAGE_ORDER: Final = (
    "verify_artifacts",
    "create_isolated_resources",
    "migrate_as_owner",
    "observe_missing_runtime_role",
    "provision_runtime_role",
    "bootstrap_synthetic_actor",
    "reconcile_authority_provenance",
    "observe_compatibility_readiness",
    "observe_exact_pre_activation_fence",
    "activate_exact_provenance",
    "observe_exact_runtime_readiness",
    "restart_web",
    "observe_database_failure",
    "restart_database_and_web",
    "replay_migrations_and_bootstrap",
    "final_readiness",
)


class RehearsalError(RuntimeError):
    """Carry one bounded failure code without private command output."""

    def __init__(self, code: str, stage: str) -> None:
        """Initialize the bounded failure.

        Parameters
        ----------
        code : str
            Stable diagnostic category.
        stage : str
            Public workflow stage that could not complete.
        """
        super().__init__(code)
        self.code = code
        self.stage = stage


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured output from one bounded local subprocess.

    Attributes
    ----------
    returncode : int
        Process exit code.
    stdout : str
        Captured standard output retained only in memory.
    stderr : str
        Captured standard error retained only in memory.
    """

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class RehearsalConfiguration:
    """Validated public inputs for one isolated run.

    Attributes
    ----------
    application_image : str
        Digest-pinned Maru OCI image reference.
    source_revision : str
        Exact source revision declared by the image.
    run_id : str
        Twelve-character random namespace used by every resource.
    evidence_path : Path
        Ignored local path receiving the sanitized receipt.
    retain_resources : bool
        Whether successful synthetic resources remain stopped for inspection.
    retain_on_failure : bool
        Whether failed synthetic resources remain stopped for inspection.
    command_timeout_seconds : int
        Maximum duration for one Docker or Git command.
    health_timeout_seconds : int
        Maximum duration for one expected health transition.
    """

    application_image: str
    source_revision: str
    run_id: str
    evidence_path: Path
    retain_resources: bool
    retain_on_failure: bool
    command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS
    health_timeout_seconds: int = DEFAULT_HEALTH_TIMEOUT_SECONDS


@dataclass(slots=True)
class ResourceSet:
    """Exact Docker resource names owned by one run.

    Attributes
    ----------
    prefix : str
        Validated name prefix shared by the resources.
    network : str
        Internal Docker network.
    postgres : str
        PostgreSQL container.
    web : str
        Gunicorn container.
    data_volume : str
        Persistent PostgreSQL data volume.
    admin_secret_volume : str
        Cluster-administrator password volume.
    migration_secret_volume : str
        Migration-login pgpass volume.
    runtime_secret_volume : str
        Runtime-login pgpass volume.
    job_containers : list[str]
        Ephemeral one-shot containers, including any interrupted job.
    """

    prefix: str
    network: str
    postgres: str
    web: str
    data_volume: str
    admin_secret_volume: str
    migration_secret_volume: str
    runtime_secret_volume: str
    job_containers: list[str] = field(default_factory=list)

    @classmethod
    def for_run(cls, run_id: str) -> ResourceSet:
        """Build the complete exact resource namespace.

        Parameters
        ----------
        run_id : str
            Validated twelve-character run identifier.

        Returns
        -------
        ResourceSet
            Names derived only from the validated identifier.
        """
        validate_run_id(run_id)
        prefix = f"maru-oci-{run_id}"
        return cls(
            prefix=prefix,
            network=f"{prefix}-network",
            postgres=f"{prefix}-postgres",
            web=f"{prefix}-web",
            data_volume=f"{prefix}-data",
            admin_secret_volume=f"{prefix}-admin-secret",
            migration_secret_volume=f"{prefix}-migration-secret",
            runtime_secret_volume=f"{prefix}-runtime-secret",
        )

    @property
    def volumes(self) -> tuple[str, ...]:
        """Return all exact volume names in cleanup order.

        Returns
        -------
        tuple[str, ...]
            Persistent data followed by the three secret volumes.
        """
        return (
            self.data_volume,
            self.admin_secret_volume,
            self.migration_secret_volume,
            self.runtime_secret_volume,
        )


class CommandRunner:
    """Run commands without a shell and without surfacing captured output."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        timeout_seconds: int,
        input_text: str | bytes | None = None,
        allow_failure: bool = False,
    ) -> CommandResult:
        """Run one bounded subprocess.

        Parameters
        ----------
        arguments : Sequence[str]
            Exact argv vector; no shell interpretation occurs.
        stage : str
            Public stage used for a bounded error.
        timeout_seconds : int
            Positive process deadline.
        input_text : str | bytes | None, default=None
            Optional private standard input retained only in memory. Bytes are
            transmitted without platform newline translation.
        allow_failure : bool, default=False
            Whether a non-zero exit is returned to the caller.

        Returns
        -------
        CommandResult
            Captured in-memory result.

        Raises
        ------
        RehearsalError
            If the command times out, cannot start, or returns non-zero.
        """
        try:
            if isinstance(input_text, bytes):
                completed_binary = subprocess.run(  # noqa: S603 - explicit argv
                    list(arguments),
                    cwd=REPOSITORY_ROOT,
                    input=input_text,
                    text=False,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                returncode = completed_binary.returncode
                stdout = completed_binary.stdout.decode("utf-8", errors="replace")
                stderr = completed_binary.stderr.decode("utf-8", errors="replace")
            else:
                completed_text = subprocess.run(  # noqa: S603 - explicit argv
                    list(arguments),
                    cwd=REPOSITORY_ROOT,
                    input=input_text,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                returncode = completed_text.returncode
                stdout = completed_text.stdout
                stderr = completed_text.stderr
        except subprocess.TimeoutExpired as error:
            raise RehearsalError("command_timeout", stage) from error
        except OSError as error:
            raise RehearsalError("command_unavailable", stage) from error
        result = CommandResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )
        if result.returncode != 0 and not allow_failure:
            raise RehearsalError("command_failed", stage)
        return result


def validate_image_reference(reference: str) -> str:
    """Require one immutable digest-only OCI reference.

    Parameters
    ----------
    reference : str
        User-supplied application reference.

    Returns
    -------
    str
        The unchanged validated reference.

    Raises
    ------
    ValueError
        If the reference is mutable, malformed, or contains whitespace.
    """
    if IMAGE_PATTERN.fullmatch(reference) is None:
        raise ValueError("image reference must end in one lowercase sha256 digest")
    return reference


def validate_source_revision(revision: str) -> str:
    """Require one full lowercase Git commit identifier.

    Parameters
    ----------
    revision : str
        Source revision expected from the OCI label.

    Returns
    -------
    str
        The unchanged validated revision.

    Raises
    ------
    ValueError
        If the value is not a full lowercase SHA-1 identifier.
    """
    if COMMIT_PATTERN.fullmatch(revision) is None:
        raise ValueError("source revision must be a full lowercase commit SHA")
    return revision


def validate_run_id(run_id: str) -> str:
    """Require the narrow random identifier used by safe cleanup.

    Parameters
    ----------
    run_id : str
        Candidate resource namespace.

    Returns
    -------
    str
        The unchanged validated identifier.

    Raises
    ------
    ValueError
        If the value is not exactly twelve lowercase hexadecimal characters.
    """
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must be exactly twelve lowercase hex characters")
    return run_id


def pgpass_line(*, username: str, password: str) -> str:
    """Build one strict private-network pgpass record.

    Parameters
    ----------
    username : str
        Exact isolated PostgreSQL login role.
    password : str
        Generated credential containing no pgpass separators.

    Returns
    -------
    str
        One newline-terminated pgpass record.

    Raises
    ------
    ValueError
        If a field could change pgpass parsing.
    """
    if not username or any(character in username for character in ":\\\n\r"):
        raise ValueError("pgpass username contains a reserved character")
    if not password or any(character in password for character in ":\\\n\r"):
        raise ValueError("generated password contains a reserved character")
    return f"postgres:5432:{DATABASE_NAME}:{username}:{password}\n"


def provisioning_sql_is_exact(sql_text: str) -> bool:
    """Return whether source SQL contains the reviewed fail-closed sentinels.

    Parameters
    ----------
    sql_text : str
        Provisioning artifact read from the image's exact source revision.

    Returns
    -------
    bool
        ``True`` only when its digest and critical statements are exact.
    """
    digest = hashlib.sha256(sql_text.encode()).hexdigest()
    sentinels = (
        "BEGIN;",
        "CREATE ROLE maru_runtime",
        "ALTER DEFAULT PRIVILEGES FOR ROLE maru_migration",
        "REVOKE CREATE, TEMPORARY ON DATABASE maru FROM maru_runtime;",
        "COMMIT;",
    )
    return digest == EXPECTED_PROVISIONING_SQL_SHA256 and all(
        sentinel in sql_text for sentinel in sentinels
    )


def parse_last_json_object(output: str) -> dict[str, object]:
    """Parse the last complete JSON object from bounded command output.

    Parameters
    ----------
    output : str
        Captured output from a repository-owned count-only command.

    Returns
    -------
    dict[str, object]
        Last complete object.

    Raises
    ------
    ValueError
        If no complete object is present.
    """
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and not output[index + end :].strip():
            return value
    raise ValueError("command emitted no final JSON object")


def evidence_is_sanitized(payload: object, secrets_to_reject: Sequence[str]) -> bool:
    """Return whether serialized evidence contains no private value.

    Parameters
    ----------
    payload : object
        Candidate JSON-safe evidence structure.
    secrets_to_reject : Sequence[str]
        Generated credentials that must never appear.

    Returns
    -------
    bool
        ``True`` when no secret, database URL, or synthetic actor identifier is
        serialized.
    """
    serialized = json.dumps(payload, sort_keys=True)
    forbidden = (*secrets_to_reject, "postgresql://", "@maru.invalid")
    return all(value not in serialized for value in forbidden if value)


def _utc_now() -> str:
    """Return one second-precision UTC timestamp.

    Returns
    -------
    str
        ISO-8601 timestamp ending in ``Z``.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sql_literal(value: str) -> str:
    """Quote one generated PostgreSQL literal for standard input only.

    Parameters
    ----------
    value : str
        In-memory generated credential.

    Returns
    -------
    str
        SQL single-quoted literal.
    """
    return "'" + value.replace("'", "''") + "'"


class OciRuntimeRehearsal:
    """Orchestrate and record one exact-image synthetic runtime rehearsal."""

    def __init__(
        self,
        configuration: RehearsalConfiguration,
        *,
        runner: CommandRunner | None = None,
    ) -> None:
        """Initialize one isolated run.

        Parameters
        ----------
        configuration : RehearsalConfiguration
            Validated public inputs and retention policy.
        runner : CommandRunner | None, default=None
            Injectable subprocess boundary used by unit tests.

        Raises
        ------
        RehearsalError
            If generated credentials are unexpectedly not distinct.
        """
        self.configuration = configuration
        self.runner = runner or CommandRunner()
        self.resources = ResourceSet.for_run(configuration.run_id)
        self._job_index = 0
        self._secrets = {
            "admin": secrets.token_urlsafe(36),
            "migration": secrets.token_urlsafe(36),
            "runtime": secrets.token_urlsafe(36),
        }
        if len(set(self._secrets.values())) != len(self._secrets):
            raise RehearsalError("credential_generation_failed", "preflight")
        self._sql_text = ""
        self._bootstrap_source = ""
        self._build_identity: dict[str, object] = {}
        self.evidence: dict[str, object] = {
            "schema_version": 1,
            "run_id": configuration.run_id,
            "started_at": _utc_now(),
            "application": {
                "image": configuration.application_image,
                "source_revision": configuration.source_revision,
            },
            "postgresql": {"image": POSTGRES_IMAGE, "major": 17},
            "topology": {
                "network_internal": True,
                "database_host_port": False,
                "web_host_port": False,
                "health_probe": "container_loopback",
                "database_roles": {
                    "administrator": ADMIN_ROLE,
                    "migration_owner": MIGRATION_ROLE,
                    "runtime_login": RUNTIME_ROLE,
                },
                "external_delivery": False,
                "settings_profile": "synthetic_local",
            },
            "stages": [],
        }

    def _run(
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        input_text: str | None = None,
        allow_failure: bool = False,
    ) -> CommandResult:
        """Run one command with the configured deadline.

        Parameters
        ----------
        arguments : Sequence[str]
            Exact subprocess argv.
        stage : str
            Public workflow stage.
        input_text : str | None, default=None
            Optional private standard input.
        allow_failure : bool, default=False
            Whether a non-zero result is returned.

        Returns
        -------
        CommandResult
            In-memory command result.
        """
        return self.runner.run(
            arguments,
            stage=stage,
            timeout_seconds=self.configuration.command_timeout_seconds,
            input_text=input_text,
            allow_failure=allow_failure,
        )

    def _docker(
        self,
        *arguments: str,
        stage: str,
        input_text: str | None = None,
        allow_failure: bool = False,
    ) -> CommandResult:
        """Run one bounded Docker CLI command.

        Parameters
        ----------
        *arguments : str
            Docker arguments after the executable name.
        stage : str
            Public workflow stage.
        input_text : str | None, default=None
            Optional private standard input.
        allow_failure : bool, default=False
            Whether a non-zero result is returned.

        Returns
        -------
        CommandResult
            In-memory Docker result.
        """
        return self._run(
            ("docker", *arguments),
            stage=stage,
            input_text=input_text,
            allow_failure=allow_failure,
        )

    def _labels(self) -> tuple[str, ...]:
        """Return exact Docker label arguments for this run.

        Returns
        -------
        tuple[str, ...]
            Two repeated ``--label`` arguments.
        """
        return (
            "--label",
            f"{RESOURCE_LABEL}=1",
            "--label",
            f"{RUN_LABEL}={self.configuration.run_id}",
        )

    def _next_job_name(self) -> str:
        """Allocate and retain one deterministic one-shot container name.

        Returns
        -------
        str
            Exact name in this run's private namespace.
        """
        self._job_index += 1
        name = f"{self.resources.prefix}-job-{self._job_index:02d}"
        self.resources.job_containers.append(name)
        return name

    def _record(self, name: str, details: Mapping[str, object] | None = None) -> None:
        """Append one sanitized successful stage.

        Parameters
        ----------
        name : str
            Stable stage name.
        details : Mapping[str, object] | None, default=None
            Optional count-only or public evidence.

        Raises
        ------
        RehearsalError
            If a private value would enter evidence.
        """
        record: dict[str, object] = {"name": name, "status": "passed"}
        if details:
            record["details"] = dict(details)
        stages = self.evidence["stages"]
        if not isinstance(stages, list):
            raise RehearsalError("evidence_invalid", name)
        candidate = [*stages, record]
        if not evidence_is_sanitized(candidate, tuple(self._secrets.values())):
            raise RehearsalError("evidence_not_sanitized", name)
        stages.append(record)

    def _announce(self, stage: str) -> None:
        """Print one credential-free progress line.

        Parameters
        ----------
        stage : str
            Stable public stage name.
        """
        print(f"[synthetic-oci] {stage}")

    def verify_artifacts(self) -> None:
        """Verify tooling, immutable images, source revision, SQL, and helper.

        Raises
        ------
        RehearsalError
            If image identity, source identity, or an evaluator artifact differs.
        """
        stage = "verify_artifacts"
        self._announce(stage)
        validate_image_reference(self.configuration.application_image)
        validate_image_reference(POSTGRES_IMAGE)
        validate_source_revision(self.configuration.source_revision)
        self._docker("version", "--format", "{{.Server.Version}}", stage=stage)
        self._docker("pull", self.configuration.application_image, stage=stage)
        self._docker("pull", POSTGRES_IMAGE, stage=stage)

        image_result = self._docker(
            "image",
            "inspect",
            self.configuration.application_image,
            stage=stage,
        )
        inspected = json.loads(image_result.stdout)
        if not isinstance(inspected, list) or len(inspected) != 1:
            raise RehearsalError("image_identity_invalid", stage)
        image = inspected[0]
        if not isinstance(image, dict):
            raise RehearsalError("image_identity_invalid", stage)
        config = image.get("Config")
        repo_digests = image.get("RepoDigests")
        if not isinstance(config, dict) or not isinstance(repo_digests, list):
            raise RehearsalError("image_identity_invalid", stage)
        labels = config.get("Labels")
        if (
            not isinstance(labels, dict)
            or labels.get("org.opencontainers.image.revision")
            != self.configuration.source_revision
        ):
            raise RehearsalError("image_source_mismatch", stage)
        requested_digest = self.configuration.application_image.rsplit("@", 1)[1]
        if not any(
            str(value).endswith(f"@{requested_digest}") for value in repo_digests
        ):
            raise RehearsalError("image_digest_mismatch", stage)

        sql_result = self._run(
            (
                "git",
                "show",
                f"{self.configuration.source_revision}:{PROVISIONING_SQL_PATH}",
            ),
            stage=stage,
        )
        self._sql_text = sql_result.stdout
        if not provisioning_sql_is_exact(self._sql_text):
            raise RehearsalError("provisioning_sql_mismatch", stage)
        self._bootstrap_source = BOOTSTRAP_HELPER.read_text(encoding="utf-8")
        helper_sha256 = hashlib.sha256(self._bootstrap_source.encode()).hexdigest()
        self._record(
            stage,
            {
                "image_revision_verified": True,
                "image_digest_verified": True,
                "provisioning_sql_sha256": EXPECTED_PROVISIONING_SQL_SHA256,
                "bootstrap_helper_sha256": helper_sha256,
            },
        )

    def _resource_names(self, resource_type: str, *, stage: str) -> set[str]:
        """Read one complete Docker resource-name inventory fail closed.

        Parameters
        ----------
        resource_type : str
            One of ``container``, ``network``, or ``volume``.
        stage : str
            Public stage requesting the inventory.

        Returns
        -------
        set[str]
            Exact names reported by the Docker daemon.

        Raises
        ------
        RehearsalError
            If the resource type is unsupported or Docker cannot be queried.
        """
        commands = {
            "container": ("container", "ls", "--all", "--format", "{{.Names}}"),
            "network": ("network", "ls", "--format", "{{.Name}}"),
            "volume": ("volume", "ls", "--format", "{{.Name}}"),
        }
        command = commands.get(resource_type)
        if command is None:
            raise RehearsalError("resource_type_invalid", stage)
        result = self._docker(*command, stage=stage)
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _owned_resource_names(self, resource_type: str, *, stage: str) -> set[str]:
        """List every resource carrying both ownership labels for this run.

        Parameters
        ----------
        resource_type : str
            One of ``container``, ``network``, or ``volume``.
        stage : str
            Public retention or cleanup stage.

        Returns
        -------
        set[str]
            Exact daemon-reported names carrying both labels.

        Raises
        ------
        RehearsalError
            If the resource type is unsupported or Docker cannot be queried.
        """
        commands = {
            "container": ("container", "ls", "--all"),
            "network": ("network", "ls"),
            "volume": ("volume", "ls"),
        }
        command = commands.get(resource_type)
        if command is None:
            raise RehearsalError("resource_type_invalid", stage)
        name_format = "{{.Names}}" if resource_type == "container" else "{{.Name}}"
        result = self._docker(
            *command,
            "--filter",
            f"label={RESOURCE_LABEL}=1",
            "--filter",
            f"label={RUN_LABEL}={self.configuration.run_id}",
            "--format",
            name_format,
            stage=stage,
        )
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _resource_exists(self, resource_type: str, name: str, *, stage: str) -> bool:
        """Return whether an exact Docker resource name is confirmed present.

        Parameters
        ----------
        resource_type : str
            One of ``container``, ``network``, or ``volume``.
        name : str
            Exact resource name.
        stage : str
            Public stage requesting the inventory.

        Returns
        -------
        bool
            Whether a successful daemon inventory contains the exact name.
        """
        return name in self._resource_names(resource_type, stage=stage)

    def _create_secret_volume(
        self,
        *,
        volume: str,
        content: str,
        owner: str,
        stage: str,
    ) -> None:
        """Create one mode-0400 secret file without argv or environment leakage.

        Parameters
        ----------
        volume : str
            Exact labeled Docker volume.
        content : str
            Secret content sent only on standard input.
        owner : str
            Numeric container UID:GID owning the secret file.
        stage : str
            Public workflow stage.
        """
        self._docker("volume", "create", *self._labels(), volume, stage=stage)
        job_name = self._next_job_name()
        self._docker(
            "run",
            "--interactive",
            "--name",
            job_name,
            "--network",
            "none",
            *self._labels(),
            "--user",
            "0:0",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "CHOWN",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            f"type=volume,source={volume},target=/secret",
            "--entrypoint",
            "sh",
            POSTGRES_IMAGE,
            "-c",
            (
                "umask 077; cat > /secret/value; "
                f"chmod 0400 /secret/value; chown {owner} /secret/value"
            ),
            stage=stage,
            input_text=content,
        )

    def create_isolated_resources(self) -> None:
        """Create a private network, data volume, and three credential volumes.

        Raises
        ------
        RehearsalError
            If any exact resource name already exists.
        """
        stage = "create_isolated_resources"
        self._announce(stage)
        fixed_resources = (
            ("container", self.resources.postgres),
            ("container", self.resources.web),
            ("network", self.resources.network),
            *(("volume", volume) for volume in self.resources.volumes),
        )
        fixed_collision = any(
            self._resource_exists(kind, name, stage=stage)
            for kind, name in fixed_resources
        )
        job_collision = bool(self._job_container_names(stage=stage))
        labeled_collision = any(
            self._owned_resource_names(resource_type, stage=stage)
            for resource_type in ("container", "network", "volume")
        )
        if fixed_collision or job_collision or labeled_collision:
            raise RehearsalError("resource_name_collision", stage)

        self._docker(
            "network",
            "create",
            "--internal",
            *self._labels(),
            self.resources.network,
            stage=stage,
        )
        self._docker(
            "volume",
            "create",
            *self._labels(),
            self.resources.data_volume,
            stage=stage,
        )
        self._create_secret_volume(
            volume=self.resources.admin_secret_volume,
            content=self._secrets["admin"],
            owner="0:0",
            stage=stage,
        )
        self._create_secret_volume(
            volume=self.resources.migration_secret_volume,
            content=pgpass_line(
                username=MIGRATION_ROLE,
                password=self._secrets["migration"],
            ),
            owner="10001:10001",
            stage=stage,
        )
        self._create_secret_volume(
            volume=self.resources.runtime_secret_volume,
            content=pgpass_line(
                username=RUNTIME_ROLE,
                password=self._secrets["runtime"],
            ),
            owner="10001:10001",
            stage=stage,
        )
        self._record(
            stage,
            {
                "internal_network": True,
                "persistent_data_volume": True,
                "distinct_credentials": True,
                "credentials_in_argv_or_environment": False,
            },
        )

    def _wait_for_postgres(self, stage: str) -> None:
        """Wait for the exact PostgreSQL container to accept local connections.

        Parameters
        ----------
        stage : str
            Public workflow stage.

        Raises
        ------
        RehearsalError
            If PostgreSQL does not become ready by the health deadline.
        """
        deadline = time.monotonic() + self.configuration.health_timeout_seconds
        while time.monotonic() < deadline:
            result = self._docker(
                "exec",
                self.resources.postgres,
                "pg_isready",
                "--username",
                ADMIN_ROLE,
                "--dbname",
                "postgres",
                stage=stage,
                allow_failure=True,
            )
            if result.returncode == 0:
                return
            time.sleep(1)
        raise RehearsalError("postgres_health_timeout", stage)

    def _start_postgres(self, stage: str) -> None:
        """Create and start PostgreSQL without publishing a host port.

        Parameters
        ----------
        stage : str
            Public workflow stage.
        """
        self._docker(
            "run",
            "--detach",
            "--name",
            self.resources.postgres,
            "--network",
            self.resources.network,
            "--network-alias",
            "postgres",
            *self._labels(),
            "--mount",
            (
                f"type=volume,source={self.resources.data_volume},"
                "target=/var/lib/postgresql/data"
            ),
            "--mount",
            (
                f"type=volume,source={self.resources.admin_secret_volume},"
                "target=/run/secrets,readonly"
            ),
            "--env",
            f"POSTGRES_USER={ADMIN_ROLE}",
            "--env",
            "POSTGRES_DB=postgres",
            "--env",
            "POSTGRES_PASSWORD_FILE=/run/secrets/value",
            "--health-cmd",
            f"pg_isready -U {ADMIN_ROLE} -d postgres",
            "--health-interval",
            "2s",
            "--health-timeout",
            "3s",
            "--health-retries",
            "30",
            POSTGRES_IMAGE,
            stage=stage,
        )
        self._wait_for_postgres(stage)

    def _postgres_sql(self, sql_text: str, *, database: str, stage: str) -> str:
        """Execute administrator SQL from private standard input.

        Parameters
        ----------
        sql_text : str
            SQL text, possibly containing an in-memory generated credential.
        database : str
            Exact isolated database name.
        stage : str
            Public workflow stage.

        Returns
        -------
        str
            Captured output retained only in memory.
        """
        result = self._docker(
            "exec",
            "--interactive",
            self.resources.postgres,
            "psql",
            "--set",
            "ON_ERROR_STOP=1",
            "--username",
            ADMIN_ROLE,
            "--dbname",
            database,
            "--tuples-only",
            "--no-align",
            "--quiet",
            stage=stage,
            input_text=sql_text,
        )
        return result.stdout

    def _application_environment(
        self,
        *,
        username: str,
        exact: bool,
        runtime_role_configured: bool,
    ) -> tuple[str, ...]:
        """Build credential-free application environment arguments.

        Parameters
        ----------
        username : str
            Genuine PostgreSQL login encoded without a password.
        exact : bool
            Whether the external exact-provenance recovery fence is selected.
        runtime_role_configured : bool
            Whether the runtime-role name is supplied to Maru.

        Returns
        -------
        tuple[str, ...]
            Repeated Docker ``--env`` arguments containing no credential.
        """
        values = [
            "DJANGO_SETTINGS_MODULE=maru.settings.local",
            (
                "MARU_DATABASE_URL="
                f"postgresql://{username}@postgres:5432/{DATABASE_NAME}"
            ),
            "PGPASSFILE=/run/secrets/value",
            "MARU_SYNTHETIC_OCI_REHEARSAL=true",
            f"MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE={str(exact).lower()}",
        ]
        if runtime_role_configured:
            values.append(f"MARU_RUNTIME_DATABASE_ROLE={RUNTIME_ROLE}")
        arguments: list[str] = []
        for value in values:
            arguments.extend(("--env", value))
        return tuple(arguments)

    def _app_job(
        self,
        *,
        stage: str,
        command: Sequence[str],
        credential: str,
        exact: bool,
        input_text: str | None = None,
    ) -> str:
        """Run one read-only application container through a genuine login.

        Parameters
        ----------
        stage : str
            Public workflow stage.
        command : Sequence[str]
            Application command after the immutable image reference.
        credential : str
            ``migration`` or ``runtime`` secret-volume selector.
        exact : bool
            Whether the exact-provenance fence is selected.
        input_text : str | None, default=None
            Optional repository-owned helper streamed to Python.

        Returns
        -------
        str
            Captured command output retained only in memory.

        Raises
        ------
        RehearsalError
            If the credential selector is unknown or the command fails.
        """
        if credential == "migration":
            username = MIGRATION_ROLE
            volume = self.resources.migration_secret_volume
        elif credential == "runtime":
            username = RUNTIME_ROLE
            volume = self.resources.runtime_secret_volume
        else:
            raise RehearsalError("credential_selector_invalid", stage)
        name = self._next_job_name()
        interactive = ("--interactive",) if input_text is not None else ()
        result = self._docker(
            "run",
            *interactive,
            "--name",
            name,
            "--network",
            self.resources.network,
            *self._labels(),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,mode=0700,uid=10001,gid=10001",  # noqa: S108
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            f"type=volume,source={volume},target=/run/secrets,readonly",
            *self._application_environment(
                username=username,
                exact=exact,
                runtime_role_configured=True,
            ),
            self.configuration.application_image,
            *command,
            stage=stage,
            input_text=input_text,
        )
        return result.stdout

    def migrate_as_owner(self) -> None:
        """Start PostgreSQL, create the owner plane, and apply migrations."""
        stage = "migrate_as_owner"
        self._announce(stage)
        self._start_postgres(stage)
        migration_password = _sql_literal(self._secrets["migration"])
        bootstrap_sql = rf"""
DO $maru_migration_role$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_roles
         WHERE rolname = '{MIGRATION_ROLE}'
    ) THEN
        RAISE EXCEPTION 'migration role already exists';
    END IF;
    EXECUTE format(
        'CREATE ROLE %I LOGIN PASSWORD %L '
        'NOSUPERUSER NOCREATEDB NOCREATEROLE '
        'NOREPLICATION NOBYPASSRLS',
        '{MIGRATION_ROLE}',
        {migration_password}
    );
END
$maru_migration_role$;
SELECT format('CREATE DATABASE %I OWNER %I', '{DATABASE_NAME}', '{MIGRATION_ROLE}')
 WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{DATABASE_NAME}'
 )
\gexec
"""  # noqa: S608 - values are fixed or generated
        self._postgres_sql(bootstrap_sql, database="postgres", stage=stage)
        self._postgres_sql(
            f"ALTER SCHEMA public OWNER TO {MIGRATION_ROLE};\n",
            database=DATABASE_NAME,
            stage=stage,
        )
        commands = (
            ("python", "src/manage.py", "migrate", "--plan"),
            ("python", "src/manage.py", "migrate", "--noinput"),
            ("python", "src/manage.py", "check"),
            (
                "python",
                "src/manage.py",
                "makemigrations",
                "--check",
                "--dry-run",
            ),
        )
        for command in commands:
            self._app_job(
                stage=stage,
                command=command,
                credential="migration",
                exact=False,
            )
        self._record(stage, {"migration_owner": True, "migration_graph_applied": True})

    def _start_web(
        self,
        *,
        stage: str,
        credential: str,
        exact: bool,
        runtime_role_configured: bool,
    ) -> None:
        """Create one loopback-only Gunicorn container.

        Parameters
        ----------
        stage : str
            Public workflow stage.
        credential : str
            ``migration`` or ``runtime`` login selector.
        exact : bool
            Whether the exact-provenance fence is selected.
        runtime_role_configured : bool
            Whether Maru receives the named runtime role.

        Raises
        ------
        RehearsalError
            If the credential selector or loopback mapping is invalid.
        """
        if self._resource_exists("container", self.resources.web, stage=stage):
            self._remove_container(self.resources.web, stage=stage)
        if credential == "migration":
            username = MIGRATION_ROLE
            volume = self.resources.migration_secret_volume
        elif credential == "runtime":
            username = RUNTIME_ROLE
            volume = self.resources.runtime_secret_volume
        else:
            raise RehearsalError("credential_selector_invalid", stage)
        self._docker(
            "run",
            "--detach",
            "--name",
            self.resources.web,
            "--network",
            self.resources.network,
            *self._labels(),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,mode=0700,uid=10001,gid=10001",  # noqa: S108
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            f"type=volume,source={volume},target=/run/secrets,readonly",
            *self._application_environment(
                username=username,
                exact=exact,
                runtime_role_configured=runtime_role_configured,
            ),
            self.configuration.application_image,
            stage=stage,
        )

    def _http(self, path: str) -> tuple[int, dict[str, object]] | None:
        """Read one container-loopback endpoint without a host publication.

        Parameters
        ----------
        path : str
            Absolute application path beginning with ``/``.

        Returns
        -------
        tuple[int, dict[str, object]] | None
            Status and object, or ``None`` while the process is unreachable.
        """
        if path not in {"/health/live", "/health/ready", "/api/v1/meta/build"}:
            return None
        result = self._docker(
            "exec",
            self.resources.web,
            "python",
            "-c",
            HTTP_PROBE_SOURCE,
            path,
            stage="health_probe",
            allow_failure=True,
        )
        if result.returncode != 0:
            return None
        try:
            wrapper = parse_last_json_object(result.stdout)
        except ValueError:
            return None
        status = wrapper.get("http_status")
        payload = wrapper.get("body")
        if not isinstance(status, int) or not isinstance(payload, dict):
            return None
        return status, payload

    def _wait_http(
        self,
        *,
        path: str,
        expected_status: int,
        stage: str,
    ) -> dict[str, object]:
        """Wait for one exact local health response.

        Parameters
        ----------
        path : str
            Fixed health/build path.
        expected_status : int
            Required HTTP status.
        stage : str
            Public workflow stage.

        Returns
        -------
        dict[str, object]
            Parsed response object.

        Raises
        ------
        RehearsalError
            If the endpoint does not reach the expected status in time.
        """
        deadline = time.monotonic() + self.configuration.health_timeout_seconds
        while time.monotonic() < deadline:
            response = self._http(path)
            if response is not None and response[0] == expected_status:
                return response[1]
            time.sleep(1)
        raise RehearsalError("http_health_timeout", stage)

    def _health_evidence(
        self,
        *,
        stage: str,
        ready_status: int,
        expected_dependencies: frozenset[str],
        unavailable_dependency: str | None = None,
    ) -> dict[str, object]:
        """Validate liveness plus one minimized readiness state.

        Parameters
        ----------
        stage : str
            Public workflow stage.
        ready_status : int
            Expected readiness HTTP status.
        expected_dependencies : frozenset[str]
            Exact public dependency-key contract for this stage.
        unavailable_dependency : str | None, default=None
            Single dependency expected to fail closed.

        Returns
        -------
        dict[str, object]
            Sanitized status/dependency evidence.

        Raises
        ------
        RehearsalError
            If health output differs from the documented minimized contract.
        """
        live = self._wait_http(path="/health/live", expected_status=200, stage=stage)
        ready = self._wait_http(
            path="/health/ready",
            expected_status=ready_status,
            stage=stage,
        )
        dependencies = ready.get("dependencies")
        if (
            live != {"status": "ok"}
            or set(ready) != {"status", "dependencies"}
            or not isinstance(dependencies, dict)
            or set(dependencies) != expected_dependencies
        ):
            raise RehearsalError("health_contract_invalid", stage)
        expected_values = dict.fromkeys(expected_dependencies, "ok")
        if ready_status == HTTP_OK:
            if unavailable_dependency is not None or (
                ready.get("status") != "ok" or dependencies != expected_values
            ):
                raise RehearsalError("health_contract_invalid", stage)
        elif ready_status == HTTP_SERVICE_UNAVAILABLE:
            if unavailable_dependency not in expected_dependencies:
                raise RehearsalError("health_contract_invalid", stage)
            expected_values[unavailable_dependency] = "unavailable"
            if ready.get("status") != "unavailable" or dependencies != expected_values:
                raise RehearsalError("health_contract_invalid", stage)
        else:
            raise RehearsalError("health_contract_invalid", stage)
        return {
            "live_http": 200,
            "live_status": live.get("status"),
            "ready_http": ready_status,
            "ready_status": ready.get("status"),
            "dependencies": dependencies,
        }

    def _stop_web_and_require_unreachable(self, stage: str) -> None:
        """Stop Gunicorn and prove the former loopback endpoint is unreachable.

        Parameters
        ----------
        stage : str
            Public workflow stage.

        Raises
        ------
        RehearsalError
            If the stopped endpoint remains reachable.
        """
        self._docker("stop", "--time", "30", self.resources.web, stage=stage)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self._http("/health/live") is None:
                return
            time.sleep(0.5)
        raise RehearsalError("stopped_web_reachable", stage)

    def observe_missing_runtime_role(self) -> None:
        """Reproduce the fail-closed candidate state before role provisioning."""
        stage = "observe_missing_runtime_role"
        self._announce(stage)
        self._start_web(
            stage=stage,
            credential="migration",
            exact=False,
            runtime_role_configured=False,
        )
        health = self._health_evidence(
            stage=stage,
            ready_status=503,
            expected_dependencies=COMPATIBILITY_READY_DEPENDENCIES,
            unavailable_dependency="logistics",
        )
        self._stop_web_and_require_unreachable(stage)
        self._record(stage, health)

    def provision_runtime_role(self) -> None:
        """Apply the exact-source least-privilege artifact and credential."""
        stage = "provision_runtime_role"
        self._announce(stage)
        self._postgres_sql(self._sql_text, database=DATABASE_NAME, stage=stage)
        runtime_password = _sql_literal(self._secrets["runtime"])
        password_sql = f"""
DO $maru_runtime_password$
BEGIN
    EXECUTE format(
        'ALTER ROLE %I PASSWORD %L',
        '{RUNTIME_ROLE}',
        {runtime_password}
    );
END
$maru_runtime_password$;
"""
        self._postgres_sql(password_sql, database=DATABASE_NAME, stage=stage)
        self._record(
            stage,
            {
                "reviewed_sql_applied": True,
                "runtime_owns_objects": False,
                "impersonation_used": False,
            },
        )

    def bootstrap_synthetic_actor(self) -> dict[str, object]:
        """Stream the secret-free, idempotent bootstrap through runtime login.

        Returns
        -------
        dict[str, object]
            Count-only bootstrap result.

        Raises
        ------
        RehearsalError
            If helper output is not the exact first-run contract.
        """
        stage = "bootstrap_synthetic_actor"
        self._announce(stage)
        output = self._app_job(
            stage=stage,
            command=("python", "-"),
            credential="runtime",
            exact=False,
            input_text=self._bootstrap_source,
        )
        try:
            payload = parse_last_json_object(output)
        except ValueError as error:
            raise RehearsalError("bootstrap_output_invalid", stage) from error
        if (
            payload.get("status") != "created"
            or payload.get("login_enabled") is not False
            or payload.get("synthetic_only") is not True
        ):
            raise RehearsalError("bootstrap_contract_invalid", stage)
        self._record(stage, payload)
        return payload

    @staticmethod
    def _readiness_summary(payload: Mapping[str, object]) -> dict[str, object]:
        """Select only stable count/status fields from a readiness report.

        Parameters
        ----------
        payload : Mapping[str, object]
            Full privacy-minimized command report.

        Returns
        -------
        dict[str, object]
            Bounded evidence subset.
        """
        keys = (
            "status",
            "activation_status",
            "production_status",
            "blocker_total",
            "contract_version",
            "policy_version",
        )
        summary = {key: payload[key] for key in keys if key in payload}
        gates = payload.get("known_production_gates")
        if isinstance(gates, dict):
            summary["known_production_gates"] = dict(gates)
        return summary

    def reconcile_authority_provenance(self) -> None:
        """Run provable-only reconciliation twice and verify pre-cutover state.

        Raises
        ------
        RehearsalError
            If reconciliation is not idempotent or activation is not ready.
        """
        stage = "reconcile_authority_provenance"
        self._announce(stage)
        commands = (
            (
                "python",
                "src/manage.py",
                "backfill_provable_authority_provenance",
                "--no-fail",
            ),
            (
                "python",
                "src/manage.py",
                "backfill_provable_authority_provenance",
                "--apply",
                "--acknowledge-writers-stopped",
            ),
            (
                "python",
                "src/manage.py",
                "backfill_provable_authority_provenance",
                "--apply",
                "--acknowledge-writers-stopped",
            ),
        )
        reports = []
        for command in commands:
            output = self._app_job(
                stage=stage,
                command=command,
                credential="migration",
                exact=False,
            )
            try:
                reports.append(parse_last_json_object(output))
            except ValueError as error:
                raise RehearsalError("backfill_output_invalid", stage) from error
        readiness_output = self._app_job(
            stage=stage,
            command=(
                "python",
                "src/manage.py",
                "check_authority_provenance_readiness",
                "--no-fail",
            ),
            credential="migration",
            exact=False,
        )
        try:
            readiness = parse_last_json_object(readiness_output)
        except ValueError as error:
            raise RehearsalError("readiness_output_invalid", stage) from error
        if (
            readiness.get("status") != "ready"
            or readiness.get("activation_status") != "ready"
            or readiness.get("production_status") != "blocked"
            or readiness.get("blocker_total") != 0
            or reports[1] != reports[2]
        ):
            raise RehearsalError("preactivation_contract_invalid", stage)
        self._record(
            stage,
            {
                "backfill_apply_replay_equal": True,
                "readiness": self._readiness_summary(readiness),
            },
        )

    def observe_compatibility_readiness(self) -> None:
        """Prove full synthetic readiness through the genuine runtime login.

        Raises
        ------
        RehearsalError
            If health or build identity differs from the immutable image.
        """
        stage = "observe_compatibility_readiness"
        self._announce(stage)
        self._start_web(
            stage=stage,
            credential="runtime",
            exact=False,
            runtime_role_configured=True,
        )
        health = self._health_evidence(
            stage=stage,
            ready_status=200,
            expected_dependencies=COMPATIBILITY_READY_DEPENDENCIES,
        )
        build = self._wait_http(
            path="/api/v1/meta/build",
            expected_status=HTTP_OK,
            stage=stage,
        )
        if build.get("commit") != self.configuration.source_revision:
            raise RehearsalError("build_identity_mismatch", stage)
        self._build_identity = {
            key: build[key] for key in ("version", "commit") if key in build
        }
        self._stop_web_and_require_unreachable(stage)
        self._record(stage, {**health, "build_identity": self._build_identity})

    def observe_exact_pre_activation_fence(self) -> None:
        """Prove exact configuration fails closed while the marker is absent."""
        stage = "observe_exact_pre_activation_fence"
        self._announce(stage)
        self._start_web(
            stage=stage,
            credential="runtime",
            exact=True,
            runtime_role_configured=True,
        )
        health = self._health_evidence(
            stage=stage,
            ready_status=503,
            expected_dependencies=EXACT_PREACTIVATION_DEPENDENCIES,
            unavailable_dependency="authority_provenance",
        )
        self._stop_web_and_require_unreachable(stage)
        self._record(stage, health)

    def _running_labeled_containers(self, stage: str) -> list[str]:
        """Return running container names for this exact run label.

        Parameters
        ----------
        stage : str
            Public workflow stage.

        Returns
        -------
        list[str]
            Sorted exact names.
        """
        result = self._docker(
            "ps",
            "--filter",
            f"label={RUN_LABEL}={self.configuration.run_id}",
            "--format",
            "{{.Names}}",
            stage=stage,
        )
        return sorted(line for line in result.stdout.splitlines() if line)

    def activate_exact_provenance(self) -> None:
        """Activate once with all application processes stopped, then replay.

        Raises
        ------
        RehearsalError
            If any application process remains or activation is not exact.
        """
        stage = "activate_exact_provenance"
        self._announce(stage)
        running = self._running_labeled_containers(stage)
        if running != [self.resources.postgres]:
            raise RehearsalError("writers_not_stopped", stage)
        command = (
            "python",
            "src/manage.py",
            "activate_authority_provenance",
            "--actor",
            "oci.runtime.rehearsal.admin@maru.invalid",
            "--reason",
            "Approved isolated synthetic OCI rehearsal cutover.",
            "--acknowledge-processes-stopped",
        )
        first_output = self._app_job(
            stage=stage,
            command=command,
            credential="migration",
            exact=True,
        )
        replay_output = self._app_job(
            stage=stage,
            command=command,
            credential="migration",
            exact=True,
        )
        postflight_output = self._app_job(
            stage=stage,
            command=(
                "python",
                "src/manage.py",
                "check_authority_provenance_readiness",
            ),
            credential="migration",
            exact=True,
        )
        try:
            first = parse_last_json_object(first_output)
            replay = parse_last_json_object(replay_output)
            postflight = parse_last_json_object(postflight_output)
        except ValueError as error:
            raise RehearsalError("activation_output_invalid", stage) from error
        production_gates = postflight.get("known_production_gates")
        if (
            first.get("status") != "activated"
            or replay.get("status") != "already_active"
            or postflight.get("status") != "ready"
            or postflight.get("activation_status") != "blocked"
            or postflight.get("production_status") != "ready"
            or postflight.get("blocker_total") != 0
            or not isinstance(production_gates, dict)
            or set(production_gates) != REQUIRED_PRODUCTION_GATES
            or any(value != "resolved" for value in production_gates.values())
        ):
            raise RehearsalError("activation_contract_invalid", stage)
        self._record(
            stage,
            {
                "first_status": first.get("status"),
                "replay_status": replay.get("status"),
                "postflight": self._readiness_summary(postflight),
                "running_application_processes_at_boundary": 0,
            },
        )

    def observe_exact_runtime_readiness(self) -> None:
        """Start a fresh exact-mode pool through the genuine runtime login."""
        stage = "observe_exact_runtime_readiness"
        self._announce(stage)
        self._start_web(
            stage=stage,
            credential="runtime",
            exact=True,
            runtime_role_configured=True,
        )
        health = self._health_evidence(
            stage=stage,
            ready_status=200,
            expected_dependencies=EXACT_READY_DEPENDENCIES,
        )
        self._record(stage, health)

    def restart_web(self) -> None:
        """Stop and restart the same web container over persisted database state.

        Raises
        ------
        RehearsalError
            If health or immutable build identity changes across restart.
        """
        stage = "restart_web"
        self._announce(stage)
        self._stop_web_and_require_unreachable(stage)
        self._docker("start", self.resources.web, stage=stage)
        health = self._health_evidence(
            stage=stage,
            ready_status=200,
            expected_dependencies=EXACT_READY_DEPENDENCIES,
        )
        build = self._wait_http(
            path="/api/v1/meta/build",
            expected_status=HTTP_OK,
            stage=stage,
        )
        observed = {key: build[key] for key in self._build_identity if key in build}
        if observed != self._build_identity:
            raise RehearsalError("build_identity_mismatch", stage)
        self._record(stage, {**health, "same_build_identity": True})

    def observe_database_failure(self) -> None:
        """Prove liveness stays independent while readiness denies database loss."""
        stage = "observe_database_failure"
        self._announce(stage)
        self._docker("stop", "--time", "30", self.resources.postgres, stage=stage)
        health = self._health_evidence(
            stage=stage,
            ready_status=503,
            expected_dependencies=DATABASE_FAILURE_DEPENDENCIES,
            unavailable_dependency="database",
        )
        self._record(stage, health)

    def restart_database_and_web(self) -> None:
        """Restart database before web and prove the activated state persists."""
        stage = "restart_database_and_web"
        self._announce(stage)
        self._stop_web_and_require_unreachable(stage)
        self._docker("start", self.resources.postgres, stage=stage)
        self._wait_for_postgres(stage)
        self._docker("start", self.resources.web, stage=stage)
        health = self._health_evidence(
            stage=stage,
            ready_status=200,
            expected_dependencies=EXACT_READY_DEPENDENCIES,
        )
        self._record(stage, {**health, "persistent_volume_reused": True})

    def _final_counts(self, stage: str) -> dict[str, int]:
        """Read four aggregate persistence counts without subject identifiers.

        Parameters
        ----------
        stage : str
            Public workflow stage.

        Returns
        -------
        dict[str, int]
            Account, marker, reserved audit, and migration counts.

        Raises
        ------
        RehearsalError
            If PostgreSQL does not return the exact four integers.
        """
        query = """
SELECT json_build_object(
    'accounts', (SELECT count(*) FROM public.identity_account),
    'activation_markers', (
        SELECT count(*) FROM public.authorization_authorityprovenanceactivation
    ),
    'activation_audits', (
        SELECT count(*) FROM public.audit_auditevent
         WHERE operation = 'authorization.authority_provenance.activate'
    ),
    'migrations', (SELECT count(*) FROM public.django_migrations)
)::text;
"""
        output = self._postgres_sql(query, database=DATABASE_NAME, stage=stage)
        try:
            payload = parse_last_json_object(output)
        except ValueError as error:
            raise RehearsalError("count_output_invalid", stage) from error
        counts: dict[str, int] = {}
        for key, value in payload.items():
            if not isinstance(value, int):
                raise RehearsalError("count_output_invalid", stage)
            counts[key] = value
        return counts

    def replay_migrations_and_bootstrap(self) -> None:
        """Stop web, rerun migrations/bootstrap, and require no duplicate evidence.

        Raises
        ------
        RehearsalError
            If migrations, bootstrap, marker, or audit evidence duplicates.
        """
        stage = "replay_migrations_and_bootstrap"
        self._announce(stage)
        self._stop_web_and_require_unreachable(stage)
        migration_output = self._app_job(
            stage=stage,
            command=("python", "src/manage.py", "migrate", "--noinput"),
            credential="migration",
            exact=True,
        )
        bootstrap_output = self._app_job(
            stage=stage,
            command=("python", "-"),
            credential="runtime",
            exact=True,
            input_text=self._bootstrap_source,
        )
        try:
            bootstrap = parse_last_json_object(bootstrap_output)
        except ValueError as error:
            raise RehearsalError("bootstrap_output_invalid", stage) from error
        counts = self._final_counts(stage)
        if (
            bootstrap.get("status") != "already_present"
            or counts.get("accounts") != 1
            or counts.get("activation_markers") != 1
            or counts.get("activation_audits") != 1
            or "No migrations to apply" not in migration_output
        ):
            raise RehearsalError("replay_contract_invalid", stage)
        self._record(
            stage,
            {
                "migration_noop": True,
                "bootstrap_status": bootstrap.get("status"),
                "counts": counts,
            },
        )

    def final_readiness(self) -> None:
        """Start the final fresh pool and record complete synthetic readiness."""
        stage = "final_readiness"
        self._announce(stage)
        self._docker("start", self.resources.web, stage=stage)
        health = self._health_evidence(
            stage=stage,
            ready_status=200,
            expected_dependencies=EXACT_READY_DEPENDENCIES,
        )
        self._record(
            stage,
            {
                **health,
                "synthetic_topology_fully_ready": True,
                "production_ready": False,
            },
        )

    def _resource_labels(
        self,
        resource_type: str,
        name: str,
        *,
        stage: str,
    ) -> dict[str, str] | None:
        """Read all labels after a successful exact-name inventory.

        Parameters
        ----------
        resource_type : str
            ``container``, ``network``, or ``volume``.
        name : str
            Exact resource name.
        stage : str
            Public stage requesting ownership evidence.

        Returns
        -------
        dict[str, str] | None
            Labels, or ``None`` only when a successful inventory proves absence.

        Raises
        ------
        RehearsalError
            If Docker cannot inspect a present resource or labels are malformed.
        """
        if not self._resource_exists(resource_type, name, stage=stage):
            return None
        format_value = (
            "{{json .Config.Labels}}"
            if resource_type == "container"
            else "{{json .Labels}}"
        )
        result = self._docker(
            resource_type,
            "inspect",
            "--format",
            format_value,
            name,
            stage=stage,
        )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RehearsalError("resource_labels_invalid", stage) from error
        if parsed is None:
            return {}
        if not isinstance(parsed, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in parsed.items()
        ):
            raise RehearsalError("resource_labels_invalid", stage)
        return parsed

    def _require_owned_resource(
        self,
        resource_type: str,
        name: str,
        *,
        stage: str,
    ) -> bool:
        """Require both ownership labels for one present exact-name resource.

        Parameters
        ----------
        resource_type : str
            ``container``, ``network``, or ``volume``.
        name : str
            Exact resource name.
        stage : str
            Public retention or cleanup stage.

        Returns
        -------
        bool
            ``True`` when the owned resource exists, otherwise ``False``.

        Raises
        ------
        RehearsalError
            If a present resource does not carry both exact ownership labels.
        """
        labels = self._resource_labels(resource_type, name, stage=stage)
        if labels is None:
            return False
        if (
            labels.get(RESOURCE_LABEL) != "1"
            or labels.get(RUN_LABEL) != self.configuration.run_id
        ):
            raise RehearsalError("cleanup_label_mismatch", stage)
        return True

    def _job_container_names(self, *, stage: str) -> list[str]:
        """Discover tracked and retained one-shot jobs in this exact namespace.

        Parameters
        ----------
        stage : str
            Public retention or cleanup stage.

        Returns
        -------
        list[str]
            Reverse-sorted deterministic job names.
        """
        inventory = self._resource_names("container", stage=stage)
        pattern = re.compile(rf"{re.escape(self.resources.prefix)}-job-[0-9]{{2,}}\Z")
        names = set(self.resources.job_containers)
        names.update(name for name in inventory if pattern.fullmatch(name))
        return sorted(names, reverse=True)

    def _cleanup_container_names(self, *, stage: str) -> list[str]:
        """Return every fixed or one-shot container name for this run.

        Parameters
        ----------
        stage : str
            Public retention or cleanup stage.

        Returns
        -------
        list[str]
            Jobs followed by the fixed web and PostgreSQL names.
        """
        return list(
            dict.fromkeys(
                (
                    *self._job_container_names(stage=stage),
                    self.resources.web,
                    self.resources.postgres,
                )
            )
        )

    def _validate_owned_inventory(
        self,
        *,
        stage: str,
    ) -> tuple[list[str], bool, list[str]]:
        """Validate the complete namespace and label inventory before mutation.

        Parameters
        ----------
        stage : str
            Public retention or cleanup stage.

        Returns
        -------
        tuple[list[str], bool, list[str]]
            Present owned containers, network presence, and owned volumes.

        Raises
        ------
        RehearsalError
            If a namespace collision, missing label, or unexpected labeled
            resource makes ownership ambiguous.
        """
        containers = self._cleanup_container_names(stage=stage)
        present_containers = [
            container
            for container in containers
            if self._require_owned_resource("container", container, stage=stage)
        ]
        network_present = self._require_owned_resource(
            "network",
            self.resources.network,
            stage=stage,
        )
        present_volumes = [
            volume
            for volume in self.resources.volumes
            if self._require_owned_resource("volume", volume, stage=stage)
        ]
        expected_networks = {self.resources.network} if network_present else set()
        if (
            self._owned_resource_names("container", stage=stage)
            != set(present_containers)
            or self._owned_resource_names("network", stage=stage) != expected_networks
            or self._owned_resource_names("volume", stage=stage) != set(present_volumes)
        ):
            raise RehearsalError("cleanup_namespace_mismatch", stage)
        return present_containers, network_present, present_volumes

    def _remove_container(self, name: str, *, stage: str) -> None:
        """Remove one exact labeled container after ownership verification.

        Parameters
        ----------
        name : str
            Exact container name.
        stage : str
            Public stage performing removal.
        """
        if not self._require_owned_resource("container", name, stage=stage):
            return
        self._docker("rm", "--force", name, stage=stage)

    def cleanup(self, *, require_present: bool = False) -> int:
        """Delete only this run's exact label-verified synthetic resources.

        Parameters
        ----------
        require_present : bool, default=False
            Whether an empty initial inventory must be treated as an operator
            error rather than idempotent failure cleanup.

        Returns
        -------
        int
            Number of exact resources present before deletion.

        Raises
        ------
        RehearsalError
            If any resource label does not match this exact run.
        """
        stage = "cleanup"
        present_containers, network_present, present_volumes = (
            self._validate_owned_inventory(stage=stage)
        )
        initial_resource_count = (
            len(present_containers) + int(network_present) + len(present_volumes)
        )
        if require_present and initial_resource_count == 0:
            raise RehearsalError("retained_run_not_found", stage)

        for container in present_containers:
            self._remove_container(container, stage=stage)
        if network_present:
            self._require_owned_resource(
                "network",
                self.resources.network,
                stage=stage,
            )
            self._docker("network", "rm", self.resources.network, stage=stage)
        for volume in present_volumes:
            self._require_owned_resource("volume", volume, stage=stage)
            self._docker("volume", "rm", volume, stage=stage)

        remaining_containers = self._cleanup_container_names(stage=stage)
        if (
            any(
                self._resource_exists("container", name, stage=stage)
                for name in remaining_containers
            )
            or self._resource_exists(
                "network",
                self.resources.network,
                stage=stage,
            )
            or any(
                self._resource_exists("volume", volume, stage=stage)
                for volume in self.resources.volumes
            )
            or any(
                self._owned_resource_names(resource_type, stage=stage)
                for resource_type in ("container", "network", "volume")
            )
        ):
            raise RehearsalError("cleanup_incomplete", stage)
        return initial_resource_count

    def stop_for_retention(self) -> None:
        """Stop exact labeled containers while retaining volumes for inspection.

        Raises
        ------
        RehearsalError
            If ownership is ambiguous or the complete retained inventory cannot
            be proved stopped and unchanged.
        """
        stage = "retention"
        present_containers, network_present, present_volumes = (
            self._validate_owned_inventory(stage=stage)
        )
        for container in present_containers:
            self._require_owned_resource("container", container, stage=stage)
            self._docker(
                "stop",
                "--time",
                "30",
                container,
                stage=stage,
            )
        retained_containers, retained_network, retained_volumes = (
            self._validate_owned_inventory(stage=stage)
        )
        if (
            set(retained_containers) != set(present_containers)
            or retained_network != network_present
            or set(retained_volumes) != set(present_volumes)
        ):
            raise RehearsalError("retention_inventory_changed", stage)
        running = self._docker(
            "container",
            "ls",
            "--format",
            "{{.Names}}",
            stage=stage,
        )
        running_names = {
            line.strip() for line in running.stdout.splitlines() if line.strip()
        }
        if any(container in running_names for container in present_containers):
            raise RehearsalError("retention_stop_incomplete", stage)

    def _write_evidence(self) -> None:
        """Write the final sanitized JSON receipt under the ignored local path.

        Raises
        ------
        RehearsalError
            If a private value could enter the receipt.
        """
        if not evidence_is_sanitized(self.evidence, tuple(self._secrets.values())):
            raise RehearsalError("evidence_not_sanitized", "evidence")
        path = self.configuration.evidence_path.resolve()
        local_root = (REPOSITORY_ROOT / ".local-ci").resolve()
        if local_root not in path.parents:
            raise RehearsalError("evidence_path_invalid", "evidence")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def execute(self) -> int:
        """Run every stage, apply retention policy, and write sanitized evidence.

        Returns
        -------
        int
            Zero on complete success and one on a bounded failure.
        """
        failure: RehearsalError | None = None
        try:
            for stage in STAGE_ORDER:
                getattr(self, stage)()
        except RehearsalError as error:
            failure = error
        except Exception:  # noqa: BLE001 - never expose raw exception text
            failure = RehearsalError("internal_error", "unknown")

        succeeded = failure is None
        retain = (
            self.configuration.retain_resources
            if succeeded
            else self.configuration.retain_on_failure
        )
        cleanup_status = "retained_stopped" if retain else "removed"
        try:
            if retain:
                self.stop_for_retention()
            else:
                self.cleanup()
        except RehearsalError:
            cleanup_status = "failed"
            if failure is None:
                failure = RehearsalError("cleanup_failed", "cleanup")

        self.evidence["completed_at"] = _utc_now()
        self.evidence["result"] = "passed" if failure is None else "failed"
        self.evidence["cleanup"] = {
            "status": cleanup_status,
            "synthetic_resources_only": True,
        }
        if failure is not None:
            self.evidence["failure"] = {
                "code": failure.code,
                "stage": failure.stage,
                "details_disclosed": False,
            }
        try:
            self._write_evidence()
        except RehearsalError:
            print("[synthetic-oci] failed (code=evidence_write_failed)")
            return 1
        if failure is not None:
            print(
                "[synthetic-oci] failed "
                f"(stage={failure.stage}; code={failure.code}); "
                "raw command output and credentials were not recorded"
            )
            return 1
        print(f"[synthetic-oci] passed; evidence={self.configuration.evidence_path}")
        return 0


def _argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser for immutable identity, namespace, timing, and retention inputs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-image", default=DEFAULT_APPLICATION_IMAGE)
    parser.add_argument("--expected-source-revision", default=DEFAULT_SOURCE_REVISION)
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument(
        "--run-id",
        help="Optional twelve-character lowercase hex id",
    )
    identity.add_argument(
        "--cleanup-retained",
        metavar="RUN_ID",
        help="Irreversibly remove one exact label-verified retained synthetic run",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        help="Path below .local-ci; defaults to a run-id-specific receipt",
    )
    parser.add_argument(
        "--retain-resources",
        action="store_true",
        help="Stop and retain successful synthetic resources for inspection",
    )
    parser.add_argument(
        "--retain-on-failure",
        action="store_true",
        help="Stop and retain failed synthetic resources for bounded diagnosis",
    )
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=DEFAULT_COMMAND_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--health-timeout-seconds",
        type=int,
        default=DEFAULT_HEALTH_TIMEOUT_SECONDS,
    )
    return parser


def configuration_from_arguments(
    arguments: argparse.Namespace,
) -> RehearsalConfiguration:
    """Validate parsed arguments and derive the ignored evidence path.

    Parameters
    ----------
    arguments : argparse.Namespace
        Parsed command-line values.

    Returns
    -------
    RehearsalConfiguration
        Immutable validated configuration.

    Raises
    ------
    ValueError
        If an identity, deadline, namespace, or evidence path is unsafe.
    """
    application_image = validate_image_reference(str(arguments.app_image))
    source_revision = validate_source_revision(str(arguments.expected_source_revision))
    run_id = validate_run_id(arguments.run_id or secrets.token_hex(6))
    command_timeout = int(arguments.command_timeout_seconds)
    health_timeout = int(arguments.health_timeout_seconds)
    if (
        command_timeout < MINIMUM_COMMAND_TIMEOUT_SECONDS
        or health_timeout < MINIMUM_HEALTH_TIMEOUT_SECONDS
    ):
        raise ValueError("timeouts must preserve bounded startup and shutdown windows")
    evidence_path = arguments.evidence or Path(
        ".local-ci",
        "oci-runtime-rehearsal",
        f"{run_id}.json",
    )
    resolved = (REPOSITORY_ROOT / evidence_path).resolve()
    local_root = (REPOSITORY_ROOT / ".local-ci").resolve()
    if local_root not in resolved.parents:
        raise ValueError("evidence path must remain below .local-ci")
    return RehearsalConfiguration(
        application_image=application_image,
        source_revision=source_revision,
        run_id=run_id,
        evidence_path=resolved,
        retain_resources=bool(arguments.retain_resources),
        retain_on_failure=bool(arguments.retain_on_failure),
        command_timeout_seconds=command_timeout,
        health_timeout_seconds=health_timeout,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse inputs and run the synthetic OCI rehearsal.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Optional arguments excluding the program name.

    Returns
    -------
    int
        Process exit code.
    """
    parser = _argument_parser()
    arguments = parser.parse_args(argv)
    cleanup_run_id = arguments.cleanup_retained
    if cleanup_run_id is not None:
        try:
            run_id = validate_run_id(str(cleanup_run_id))
        except ValueError as error:
            parser.error(str(error))
        cleanup_configuration = RehearsalConfiguration(
            application_image=DEFAULT_APPLICATION_IMAGE,
            source_revision=DEFAULT_SOURCE_REVISION,
            run_id=run_id,
            evidence_path=(
                REPOSITORY_ROOT
                / ".local-ci"
                / "oci-runtime-rehearsal"
                / f"{run_id}.json"
            ),
            retain_resources=False,
            retain_on_failure=False,
        )
        try:
            OciRuntimeRehearsal(cleanup_configuration).cleanup(require_present=True)
        except RehearsalError as error:
            print(
                "[synthetic-oci] retained cleanup refused "
                f"(stage={error.stage}; code={error.code})"
            )
            return 1
        print(
            "[synthetic-oci] retained synthetic resources removed irreversibly "
            f"(run_id={run_id})"
        )
        return 0
    try:
        configuration = configuration_from_arguments(arguments)
    except ValueError as error:
        parser.error(str(error))
    return OciRuntimeRehearsal(configuration).execute()


if __name__ == "__main__":
    raise SystemExit(main())
