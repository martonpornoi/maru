"""Rehearse immutable Maru static delivery through an unprivileged OCI edge.

This executable evaluator is deliberately synthetic. It proves that one exact
Maru candidate's already-collected static files can be copied byte-for-byte
into a read-only edge volume while dynamic and private documentation requests
continue to reach the candidate's Gunicorn process. It does not select a
production edge provider, terminate TLS, or claim production deployment
approval.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING or __package__:
    from scripts.rehearse_oci_runtime import (
        CommandResult,
        CommandRunner,
        RehearsalError,
        evidence_is_sanitized,
        parse_last_json_object,
        validate_image_reference,
        validate_run_id,
        validate_source_revision,
    )
else:  # pragma: no cover - exercised by the documented direct script invocation
    from rehearse_oci_runtime import (
        CommandResult,
        CommandRunner,
        RehearsalError,
        evidence_is_sanitized,
        parse_last_json_object,
        validate_image_reference,
        validate_run_id,
        validate_source_revision,
    )

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from email.message import Message


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EDGE_CONFIG_PATH = REPOSITORY_ROOT / "scripts" / "oci-static-edge.conf"
EXPECTED_EDGE_CONFIG_SHA256: Final = (
    "aca9da2ad29c32e972227ef34e7bef1c0423b6d8d4c63baa822fc30eda5e6b3c"
)
DEFAULT_APPLICATION_IMAGE: Final = (
    "ghcr.io/martonpornoi/maru@"
    "sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445"
)
DEFAULT_SOURCE_REVISION: Final = "be0b21db9ba2d2a956bd192a1d66c537d702c4c4"
DEFAULT_EDGE_IMAGE: Final = (
    "ghcr.io/nginx/nginx-unprivileged:1.30.4-alpine3.24-slim@"
    "sha256:3b569ded54fe09ab73dbdb409f403631d55c0bb231e4adc10b7c974beb0dc7be"
)
POSTGRES_IMAGE: Final = (
    "postgres:17.11-alpine@"
    "sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
)
OCI_PLATFORM: Final = "linux/amd64"
DATABASE_NAME: Final = "maru"
DATABASE_ROLE: Final = "maru_static"
DEMO_ADMIN_EMAIL: Final = "demo.admin@maru.invalid"
RESOURCE_LABEL: Final = "io.maru.oci-static-delivery"
RUN_LABEL: Final = "io.maru.oci-static-delivery-run"
EDGE_CONTAINER_PORT: Final = 8080
DEFAULT_COMMAND_TIMEOUT_SECONDS: Final = 600
DEFAULT_HTTP_TIMEOUT_SECONDS: Final = 120
MINIMUM_COMMAND_TIMEOUT_SECONDS: Final = 30
MINIMUM_HTTP_TIMEOUT_SECONDS: Final = 10
MAX_RESPONSE_BYTES: Final = 32 * 1024 * 1024
MAX_EDGE_DENIAL_BYTES: Final = 4096
MAX_MANIFEST_FILES: Final = 100_000
MAX_TCP_PORT: Final = 65_535
MAX_CSRF_TOKEN_LENGTH: Final = 256
TMPFS_PATH: Final = "/tmp"  # noqa: S108 - fixed in-container tmpfs mount
TMPFS_SIZE_BYTES: Final = 67_108_864
HTTP_OK: Final = 200
HTTP_NOT_MODIFIED: Final = 304
HTTP_NOT_FOUND: Final = 404
HTTP_FORBIDDEN: Final = 403
HTTP_METHOD_NOT_ALLOWED: Final = 405
HTTP_BAD_GATEWAY: Final = frozenset({502, 503, 504})
EXPECTED_APP_USER: Final = frozenset({"10001", "10001:10001"})
EXPECTED_EDGE_USER: Final = frozenset({"101", "101:101"})

LANDING_ASSETS: Final = (
    "/static/core/brand/favicon.ico",
    "/static/core/brand/apple-touch-icon.png",
    "/static/core/brand/site.webmanifest",
    "/static/core/brand.css",
    "/static/core/brand/maru_rectangle_full_logo.png",
)
MANIFEST_ICON_ASSETS: Final = (
    "/static/core/brand/android-chrome-192x192.png",
    "/static/core/brand/android-chrome-512x512.png",
)
STATIC_DYNAMIC_ESCAPE_PROBES: Final = (
    "/static/../health/live",
    "/static/%2e%2e/health/live",
    "/static/core%2f..%2f..%2fhealth/live",
    "/static%2f%2e%2e%2fhealth/live",
    "/static%5c..%5chealth/live",
    "//static/../health/live",
    "///static/%2e%2e/health/live",
    "/%2fstatic/%2e%2e/health/live",
    "/%73tatic/%2e%2e/health/live",
    r"/static\..\health/live",
    r"/\static\..\health/live",
    r"/%73tatic\%2e%2e\health/live",
)
MEDIA_DYNAMIC_ESCAPE_PROBES: Final = (
    "/media/../health/live",
    "/media/%2e%2e/health/live",
    "/media%2f%2e%2e%2fhealth/live",
    "/media%5c..%5chealth/live",
    "//media/../health/live",
    "/%2fmedia/%2e%2e/health/live",
    "/%6dedia/%2e%2e/health/live",
    r"/media\..\health/live",
    r"/\media\..\health/live",
)
LOGIN_ASSETS: Final = ("/static/core/brand/maru_square_logo_no_text.png",)
REDOC_BUNDLE_PATH: Final = (
    "/static/drf_spectacular_sidecar/redoc/bundles/redoc.standalone.js"
)
DOCUMENTATION_ASSETS: Final = (
    "/static/drf_spectacular_sidecar/swagger-ui-dist/swagger-ui.css",
    "/static/drf_spectacular_sidecar/swagger-ui-dist/swagger-ui-bundle.js",
    "/static/drf_spectacular_sidecar/swagger-ui-dist/swagger-ui-standalone-preset.js",
    "/static/drf_spectacular_sidecar/swagger-ui-dist/favicon-32x32.png",
    REDOC_BUNDLE_PATH,
)
REQUIRED_STATIC_ASSETS: Final = frozenset(
    (*LANDING_ASSETS, *MANIFEST_ICON_ASSETS, *LOGIN_ASSETS, *DOCUMENTATION_ASSETS)
)
EXPECTED_MIME_TYPES: Final[dict[str, frozenset[str]]] = {
    ".css": frozenset({"text/css"}),
    ".ico": frozenset({"image/x-icon", "image/vnd.microsoft.icon"}),
    ".js": frozenset({"application/javascript", "text/javascript"}),
    ".png": frozenset({"image/png"}),
    ".webmanifest": frozenset({"application/manifest+json"}),
}
FORBIDDEN_DOCUMENTATION_ORIGINS: Final = (
    "cdn.redoc.ly",
    "cdn.jsdelivr.net",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
)
REDOC_REMOTE_LOGO_URL: Final = b"https://cdn.redoc.ly/redoc/logo-mini.svg"
REDOC_LOCAL_LOGO_DATA_URL: Final = (
    b"data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)
REDOC_BUNDLE_SOURCE_SIZE: Final = 1_097_271
REDOC_BUNDLE_SOURCE_SHA256: Final = (
    "1320f442151c57c447d3b70c7ffc6c4f86d08464020fe34c8cc5d3164e9944f0"
)
REDOC_BUNDLE_EDGE_SIZE: Final = 1_097_309
REDOC_BUNDLE_EDGE_SHA256: Final = (
    "488ad6f335c47d69afe969ab3c9a906d5d2b91695d6b3e0be63ab76f63c94021"
)

STATIC_MANIFEST_SOURCE: Final = r"""
import hashlib
import json
import os
import stat

root = "/app/staticfiles"
if not os.path.isdir(root):
    raise SystemExit(2)
files = []
for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
    directories.sort()
    filenames.sort()
    for directory in directories:
        candidate = os.path.join(current, directory)
        if not stat.S_ISDIR(os.lstat(candidate).st_mode):
            raise SystemExit(3)
    for filename in filenames:
        candidate = os.path.join(current, filename)
        metadata = os.lstat(candidate)
        if not stat.S_ISREG(metadata.st_mode):
            raise SystemExit(4)
        relative = os.path.relpath(candidate, root).replace(os.sep, "/")
        if relative.startswith("../") or relative.startswith("/") or "\\" in relative:
            raise SystemExit(5)
        digest = hashlib.sha256()
        with open(candidate, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files.append(
            {"path": relative, "sha256": digest.hexdigest(), "size": metadata.st_size}
        )
files.sort(key=lambda entry: entry["path"])
print(json.dumps({"files": files, "schema_version": 1}, sort_keys=True))
"""

DEMO_BOOTSTRAP_SOURCE: Final = r"""
import io
import json
import sys

import django
from django.core.management import call_command

password = sys.stdin.read()
if not 24 <= len(password) <= 256:
    raise SystemExit(2)
django.setup()
sink = io.StringIO()
call_command(
    "seed_demo_data",
    password=password,
    reset_passwords=False,
    verbosity=0,
    stdout=sink,
)
print(json.dumps({"schema_version": 1, "status": "seeded", "synthetic": True}))
"""

STAGE_ORDER: Final = (
    "verify_artifacts",
    "create_isolated_resources",
    "capture_image_static_manifest",
    "populate_static_volume",
    "initialize_application",
    "start_delivery_topology",
    "verify_dynamic_boundary",
    "verify_static_delivery",
    "verify_private_api_documentation",
    "verify_runtime_hardening",
    "exercise_restart_boundaries",
    "final_delivery_check",
)


@dataclass(frozen=True, slots=True)
class StaticDeliveryConfiguration:
    """Validated public inputs for one isolated static-delivery run.

    Attributes
    ----------
    application_image : str
        Immutable digest-pinned Maru application image.
    source_revision : str
        Exact source revision expected in the application image label.
    edge_image : str
        Immutable digest-pinned reference edge image.
    run_id : str
        Twelve-character lowercase hexadecimal synthetic run identifier.
    evidence_path : pathlib.Path
        Ignored path for the sanitized schema-versioned receipt.
    edge_config_path : pathlib.Path
        Reviewed repository Nginx configuration input.
    retain_resources : bool
        Whether a successful run stops and retains its exact resources.
    retain_on_failure : bool
        Whether a failed run stops and retains its exact resources.
    command_timeout_seconds : int
        Maximum duration for one external command.
    http_timeout_seconds : int
        Maximum duration for a bounded HTTP readiness wait.
    """

    application_image: str
    source_revision: str
    edge_image: str
    run_id: str
    evidence_path: Path
    edge_config_path: Path
    retain_resources: bool
    retain_on_failure: bool
    command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS
    http_timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS


@dataclass(slots=True)
class StaticDeliveryResources:
    """Exact Docker resource names owned by one static-delivery run.

    Attributes
    ----------
    prefix : str
        Common exact resource-name prefix derived from the run identifier.
    backend_network : str
        Internal database network name.
    proxy_network : str
        Internal Gunicorn-to-edge network name.
    ingress_network : str
        Edge-only host-publication network name.
    postgres : str
        PostgreSQL container name.
    web : str
        Gunicorn container name.
    edge : str
        Reference edge container name.
    data_volume : str
        Disposable PostgreSQL data-volume name.
    postgres_secret_volume : str
        PostgreSQL secret-volume name.
    app_secret_volume : str
        Application secret-volume name.
    static_volume : str
        Exact candidate static-volume name.
    config_volume : str
        Snapshotted edge-configuration volume name.
    job_containers : list[str]
        Ordered short-lived job-container names created during the run.
    """

    prefix: str
    backend_network: str
    proxy_network: str
    ingress_network: str
    postgres: str
    web: str
    edge: str
    data_volume: str
    postgres_secret_volume: str
    app_secret_volume: str
    static_volume: str
    config_volume: str
    job_containers: list[str] = field(default_factory=list)

    @classmethod
    def for_run(cls, run_id: str) -> StaticDeliveryResources:
        """Derive the complete exact namespace from one validated identifier.

        Parameters
        ----------
        run_id : str
            Validated twelve-character lowercase hexadecimal run identifier.

        Returns
        -------
        StaticDeliveryResources
            Exact resource names derived only from the run identifier.
        """
        validate_run_id(run_id)
        prefix = f"maru-static-{run_id}"
        return cls(
            prefix=prefix,
            backend_network=f"{prefix}-backend",
            proxy_network=f"{prefix}-proxy",
            ingress_network=f"{prefix}-ingress",
            postgres=f"{prefix}-postgres",
            web=f"{prefix}-web",
            edge=f"{prefix}-edge",
            data_volume=f"{prefix}-data",
            postgres_secret_volume=f"{prefix}-postgres-secret",
            app_secret_volume=f"{prefix}-app-secret",
            static_volume=f"{prefix}-static",
            config_volume=f"{prefix}-config",
        )

    @property
    def networks(self) -> tuple[str, str, str]:
        """Return all networks in cleanup order.

        Returns
        -------
        tuple[str, str, str]
            Database backend, internal proxy, and ingress networks.
        """
        return (
            self.backend_network,
            self.proxy_network,
            self.ingress_network,
        )

    @property
    def volumes(self) -> tuple[str, str, str, str, str]:
        """Return every exact volume in cleanup order.

        Returns
        -------
        tuple[str, str, str, str, str]
            Data, PostgreSQL secret, app secret, static, and config volumes.
        """
        return (
            self.data_volume,
            self.postgres_secret_volume,
            self.app_secret_volume,
            self.static_volume,
            self.config_volume,
        )


@dataclass(frozen=True, slots=True)
class StaticFileEvidence:
    """One canonical regular-file entry from the candidate static manifest.

    Attributes
    ----------
    path : str
        Normalized path relative to the candidate static root.
    size : int
        Exact file size in bytes.
    sha256 : str
        Lowercase SHA-256 digest of the file bytes.
    """

    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class HttpResult:
    """Bounded in-memory HTTP response used only during evaluation.

    Attributes
    ----------
    status : int
        HTTP response status code.
    headers : collections.abc.Mapping[str, str]
        Lowercase bounded response-header mapping.
    body : bytes
        Bounded response body retained only in memory.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Preserve redirect responses so authorization boundaries can be asserted."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        """Decline automatic redirect following.

        Parameters
        ----------
        *_args : object
            Positional redirect metadata supplied by ``urllib``.
        **_kwargs : object
            Keyword redirect metadata supplied by ``urllib``.
        """


class _HtmlReferenceParser(HTMLParser):
    """Collect bounded resource references and named form inputs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []
        self.inputs: dict[str, str] = {}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Collect relevant ``href``, ``src``, and input-value attributes.

        Parameters
        ----------
        tag : str
            Lowercase HTML element name.
        attrs : list[tuple[str, str | None]]
            Parsed attributes in document order.
        """
        attributes = dict(attrs)
        if tag in {"img", "link", "script"}:
            value = attributes.get("src") or attributes.get("href")
            if value:
                self.references.append(value)
        if tag == "input":
            name = attributes.get("name")
            if name:
                self.inputs[name] = attributes.get("value") or ""


def _utc_now() -> str:
    """Return one second-precision UTC timestamp.

    Returns
    -------
    str
        ISO-8601 timestamp ending in ``Z``.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _pgpass_line(password: str) -> str:
    """Build the private-network pgpass record for the isolated application.

    Parameters
    ----------
    password : str
        Generated database password retained only in memory and secret volumes.

    Returns
    -------
    str
        Newline-terminated private-network pgpass record.

    Raises
    ------
    ValueError
        If the generated password could change pgpass parsing.
    """
    if not password or any(character in password for character in ":\\\n\r"):
        raise ValueError("generated password contains a pgpass reserved character")
    return f"postgres:5432:{DATABASE_NAME}:{DATABASE_ROLE}:{password}\n"


def _headers_as_mapping(headers: Message) -> dict[str, str]:
    """Normalize response headers without retaining duplicate secret values.

    Parameters
    ----------
    headers : Message
        In-memory HTTP response headers.

    Returns
    -------
    dict[str, str]
        Case-folded names mapped to comma-joined values.
    """
    return {name.casefold(): ", ".join(headers.get_all(name, [])) for name in headers}


def _content_type(result: HttpResult) -> str:
    """Return the normalized response media type without parameters.

    Parameters
    ----------
    result : HttpResult
        Bounded HTTP response.

    Returns
    -------
    str
        Case-folded media type without parameters.
    """
    return result.headers.get("content-type", "").partition(";")[0].strip().casefold()


def _tmpfs_mount(uid: int, gid: int) -> str:
    """Build one explicitly size-bounded hardened temporary-filesystem mount.

    Parameters
    ----------
    uid : int
        Positive numeric owner identifier.
    gid : int
        Positive numeric group identifier.

    Returns
    -------
    str
        Docker ``--tmpfs`` value with exact security and size options.

    Raises
    ------
    ValueError
        If either numeric identity is not positive.
    """
    if uid <= 0 or gid <= 0:
        raise ValueError("tmpfs ownership must remain unprivileged")
    return (
        f"{TMPFS_PATH}:rw,noexec,nosuid,nodev,mode=0700,"
        f"uid={uid},gid={gid},size={TMPFS_SIZE_BYTES}"
    )


def edge_config_is_safe(source: str) -> bool:
    """Return whether the reviewed adapter keeps the static/proxy boundary exact.

    Parameters
    ----------
    source : str
        Candidate Nginx ``default.conf`` source.

    Returns
    -------
    bool
        Whether required fail-closed sentinels are present and unsafe ones absent.
    """
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != (
        EXPECTED_EDGE_CONFIG_SHA256
    ):
        return False
    directives = "\n".join(line.partition("#")[0] for line in source.splitlines())
    required = (
        "listen 8080",
        "location = /static",
        "location ^~ /static/",
        "location = /static/core/brand/site.webmanifest",
        "location = " + REDOC_BUNDLE_PATH,
        "default_type application/manifest+json",
        "root /srv/maru",
        "try_files $uri =404",
        "disable_symlinks on",
        "autoindex off",
        'add_header Cache-Control "public, max-age=0, must-revalidate" always',
        "location ^~ /media/",
        'add_header Cache-Control "no-store" always',
        "proxy_pass http://maru-web:8000",
        "proxy_cache off",
        "proxy_next_upstream off",
        "sub_filter_types application/javascript",
        "sub_filter_once on",
        "sub_filter_last_modified off",
        "if_modified_since off",
        "max_ranges 0",
        "gzip off",
        'set $redoc_precondition "$request_method:$http_if_none_match"',
        'if ($redoc_precondition ~ "^(GET|HEAD):[*]$")',
        "return 304",
        "sub_filter 'https://cdn.redoc.ly/redoc/logo-mini.svg' "
        "'data:image/gif;base64,"
        "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'",
        "proxy_set_header X-Forwarded-For $remote_addr",
        'proxy_set_header X-Forwarded-Port ""',
        'proxy_set_header X-Forwarded-Prefix ""',
        r'if ($request_uri ~* "^(?:/|%2f|%5c|\\x5c)+'
        r'static(?:/|%2f|%5c|\\x5c)")',
        r'if ($request_uri ~* "^(?:/|%2f|%5c|\\x5c)+'
        r'media(?:/|%2f|%5c|\\x5c)")',
        r'if ($request_uri ~* "^[^?]*(?:/|%2f|%5c|\\x5c)'
        r'(?:[.]|%2e){1,2}(?:/|%2f|%5c|\\x5c|[?]|$)")',
    )
    forbidden = (
        "$proxy_add_x_forwarded_for",
        "proxy_cache on",
        "immutable",
        "autoindex on",
    )
    return all(sentinel in directives for sentinel in required) and not any(
        sentinel in directives for sentinel in forbidden
    )


class OciStaticDeliveryRehearsal:
    """Orchestrate and record one exact-image static-delivery rehearsal."""

    def __init__(
        self,
        configuration: StaticDeliveryConfiguration,
        *,
        runner: CommandRunner | None = None,
    ) -> None:
        """Initialize isolated resources, secrets, HTTP state, and evidence.

        Parameters
        ----------
        configuration : StaticDeliveryConfiguration
            Validated public identity, timing, receipt, and retention inputs.
        runner : CommandRunner | None, default=None
            Injectable shell-free subprocess boundary.

        Raises
        ------
        RehearsalError
            If generated credentials are unexpectedly not distinct.
        """
        self.configuration = configuration
        self.runner = runner or CommandRunner()
        self.resources = StaticDeliveryResources.for_run(configuration.run_id)
        self._job_index = 0
        self._secrets = {
            "database": secrets.token_urlsafe(36),
            "demo_password": secrets.token_urlsafe(48),
        }
        if len(set(self._secrets.values())) != len(self._secrets):
            raise RehearsalError("credential_generation_failed", "preflight")
        self._image_manifest: dict[str, StaticFileEvidence] = {}
        self._manifest_digest = ""
        self._config_digest = ""
        self._config_source = ""
        self._config_bytes = b""
        self._build_identity: dict[str, object] = {}
        self._edge_origin = ""
        self._edge_port = 0
        self._edge_ports_observed: list[int] = []
        self._landing_references: set[str] = set()
        self._manifest_icon_references: set[str] = set()
        self._documentation_references: set[str] = set()
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self._cookie_jar),
        )
        self._no_redirect_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self._cookie_jar),
            _NoRedirectHandler(),
        )
        self.evidence: dict[str, object] = {
            "schema_version": 1,
            "run_id": configuration.run_id,
            "started_at": _utc_now(),
            "application": {
                "image": configuration.application_image,
                "source_revision": configuration.source_revision,
            },
            "edge": {
                "image": configuration.edge_image,
                "platform": OCI_PLATFORM,
            },
            "postgresql": {"image": POSTGRES_IMAGE, "major": 17},
            "topology": {
                "backend_network_internal": True,
                "proxy_network_internal": True,
                "database_host_port": False,
                "web_host_port": False,
                "edge_loopback_only": True,
                "edge_database_network_access": False,
                "edge_static_mount_read_only": True,
                "dynamic_upstream": "gunicorn",
                "production_provider_selected": False,
                "tls_terminated": False,
            },
            "stages": [],
        }

    def _run(
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        input_text: str | bytes | None = None,
        allow_failure: bool = False,
    ) -> CommandResult:
        """Run one shell-free command through the shared bounded runner.

        Parameters
        ----------
        arguments : Sequence[str]
            Exact subprocess argument vector.
        stage : str
            Stable public workflow stage.
        input_text : str | bytes | None, default=None
            Optional private standard input retained only in memory. Bytes are
            transmitted without platform newline translation.
        allow_failure : bool, default=False
            Whether a nonzero result is returned to the caller.

        Returns
        -------
        CommandResult
            Captured in-memory subprocess result.
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
        input_text: str | bytes | None = None,
        allow_failure: bool = False,
    ) -> CommandResult:
        """Run one bounded Docker CLI command.

        Parameters
        ----------
        *arguments : str
            Docker arguments after the executable name.
        stage : str
            Stable public workflow stage.
        input_text : str | bytes | None, default=None
            Optional private standard input retained only in memory. Bytes are
            transmitted without platform newline translation.
        allow_failure : bool, default=False
            Whether a nonzero result is returned to the caller.

        Returns
        -------
        CommandResult
            Captured in-memory Docker result.
        """
        return self._run(
            ("docker", *arguments),
            stage=stage,
            input_text=input_text,
            allow_failure=allow_failure,
        )

    def _labels(self) -> tuple[str, ...]:
        """Return both exact ownership-label arguments for this run.

        Returns
        -------
        tuple[str, ...]
            Repeated Docker ``--label`` arguments.
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
            Exact job name in this run's namespace.
        """
        self._job_index += 1
        name = f"{self.resources.prefix}-job-{self._job_index:02d}"
        self.resources.job_containers.append(name)
        return name

    def _announce(self, stage: str) -> None:
        """Print one credential-free progress line.

        Parameters
        ----------
        stage : str
            Stable public stage name.
        """
        print(f"[synthetic-oci-static] {stage}")

    def _record(
        self,
        name: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """Append one sanitized successful stage to the in-memory receipt.

        Parameters
        ----------
        name : str
            Stable stage name.
        details : Mapping[str, object] | None, default=None
            Optional public, count-only, or boolean evidence.

        Raises
        ------
        RehearsalError
            If the evidence structure or its sanitization is invalid.
        """
        record: dict[str, object] = {"name": name, "status": "passed"}
        if details:
            record["details"] = dict(details)
        stages = self.evidence.get("stages")
        if not isinstance(stages, list):
            raise RehearsalError("evidence_invalid", name)
        candidate = [*stages, record]
        if not self._evidence_is_sanitized(candidate):
            raise RehearsalError("evidence_not_sanitized", name)
        stages.append(record)

    def _evidence_is_sanitized(self, payload: object) -> bool:
        """Reject credentials, fixture identity, cookies, and raw private bodies.

        Parameters
        ----------
        payload : object
            Candidate JSON-safe receipt fragment.

        Returns
        -------
        bool
            Whether no private value or body marker is serialized.
        """
        if not evidence_is_sanitized(payload, tuple(self._secrets.values())):
            return False
        serialized = json.dumps(payload, sort_keys=True).casefold()
        forbidden = (
            DEMO_ADMIN_EMAIL.casefold(),
            "csrftoken",
            "sessionid",
            "set-cookie",
            "authorization:",
            "<!doctype html",
            "<html",
        )
        return all(value not in serialized for value in forbidden)

    def _inspect_image(self, reference: str, *, stage: str) -> dict[str, object]:
        """Return the one structured Docker image record for a pinned reference.

        Parameters
        ----------
        reference : str
            Exact digest-pinned image reference.
        stage : str
            Public stage requesting inspection.

        Returns
        -------
        dict[str, object]
            The sole structured Docker image record.

        Raises
        ------
        RehearsalError
            If Docker does not return exactly one valid record.
        """
        result = self._docker("image", "inspect", reference, stage=stage)
        try:
            inspected = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RehearsalError("image_identity_invalid", stage) from error
        if (
            not isinstance(inspected, list)
            or len(inspected) != 1
            or not isinstance(inspected[0], dict)
        ):
            raise RehearsalError("image_identity_invalid", stage)
        return inspected[0]

    @staticmethod
    def _require_requested_digest(
        image: Mapping[str, object],
        reference: str,
        *,
        stage: str,
    ) -> None:
        """Require an inspected image to retain the exact requested digest.

        Parameters
        ----------
        image : Mapping[str, object]
            Structured Docker image inspection record.
        reference : str
            Exact digest-pinned image reference.
        stage : str
            Public stage requesting verification.

        Raises
        ------
        RehearsalError
            If repository digests are malformed or omit the requested digest.
        """
        repo_digests = image.get("RepoDigests")
        if not isinstance(repo_digests, list):
            raise RehearsalError("image_identity_invalid", stage)
        requested_digest = reference.rsplit("@", 1)[1]
        if not any(
            isinstance(value, str) and value.endswith(f"@{requested_digest}")
            for value in repo_digests
        ):
            raise RehearsalError("image_digest_mismatch", stage)

    def verify_artifacts(self) -> None:
        """Verify tooling, three immutable images, source identity, and config.

        Raises
        ------
        RehearsalError
            If an image, platform, user, source label, or config is not exact.
        """
        stage = "verify_artifacts"
        self._announce(stage)
        validate_image_reference(self.configuration.application_image)
        validate_image_reference(self.configuration.edge_image)
        validate_image_reference(POSTGRES_IMAGE)
        validate_source_revision(self.configuration.source_revision)
        self._docker("version", "--format", "{{.Server.Version}}", stage=stage)
        for reference in (
            self.configuration.application_image,
            self.configuration.edge_image,
            POSTGRES_IMAGE,
        ):
            self._docker(
                "pull",
                "--platform",
                OCI_PLATFORM,
                reference,
                stage=stage,
            )

        application = self._inspect_image(
            self.configuration.application_image,
            stage=stage,
        )
        edge = self._inspect_image(self.configuration.edge_image, stage=stage)
        postgres = self._inspect_image(POSTGRES_IMAGE, stage=stage)
        for image, reference in (
            (application, self.configuration.application_image),
            (edge, self.configuration.edge_image),
            (postgres, POSTGRES_IMAGE),
        ):
            self._require_requested_digest(image, reference, stage=stage)
            if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
                raise RehearsalError("image_platform_mismatch", stage)

        app_config = application.get("Config")
        edge_config = edge.get("Config")
        if not isinstance(app_config, dict) or not isinstance(edge_config, dict):
            raise RehearsalError("image_identity_invalid", stage)
        labels = app_config.get("Labels")
        if (
            not isinstance(labels, dict)
            or labels.get("org.opencontainers.image.revision")
            != self.configuration.source_revision
        ):
            raise RehearsalError("image_source_mismatch", stage)
        if str(app_config.get("User", "")) not in EXPECTED_APP_USER:
            raise RehearsalError("application_user_invalid", stage)
        if str(edge_config.get("User", "")) not in EXPECTED_EDGE_USER:
            raise RehearsalError("edge_user_invalid", stage)

        config_path = self.configuration.edge_config_path.resolve()
        if config_path != EDGE_CONFIG_PATH.resolve() or not config_path.is_file():
            raise RehearsalError("edge_config_invalid", stage)
        config_source = config_path.read_bytes()
        try:
            decoded_config = config_source.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RehearsalError("edge_config_invalid", stage) from error
        if (
            not config_source
            or len(config_source) > 64 * 1024
            or not edge_config_is_safe(decoded_config)
        ):
            raise RehearsalError("edge_config_invalid", stage)
        self._config_digest = hashlib.sha256(config_source).hexdigest()
        self._config_source = decoded_config
        self._config_bytes = config_source
        self._record(
            stage,
            {
                "application_digest_verified": True,
                "application_revision_verified": True,
                "edge_digest_verified": True,
                "postgresql_digest_verified": True,
                "platform": OCI_PLATFORM,
                "application_user": "10001:10001",
                "edge_user": "101:101",
                "edge_config_sha256": self._config_digest,
            },
        )

    def _resource_names(self, resource_type: str, *, stage: str) -> set[str]:
        """Read one complete Docker resource-name inventory fail closed.

        Parameters
        ----------
        resource_type : str
            ``container``, ``network``, or ``volume``.
        stage : str
            Public stage requesting inventory.

        Returns
        -------
        set[str]
            Exact names reported by Docker.

        Raises
        ------
        RehearsalError
            If the resource type is unsupported.
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
        """List every resource carrying both exact ownership labels.

        Parameters
        ----------
        resource_type : str
            ``container``, ``network``, or ``volume``.
        stage : str
            Public stage requesting inventory.

        Returns
        -------
        set[str]
            Exact names carrying both run labels.

        Raises
        ------
        RehearsalError
            If the resource type is unsupported.
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
        """Return whether a successful inventory contains one exact name.

        Parameters
        ----------
        resource_type : str
            ``container``, ``network``, or ``volume``.
        name : str
            Exact resource name.
        stage : str
            Public stage requesting inventory.

        Returns
        -------
        bool
            Whether Docker reports the exact name.
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
        """Create one mode-0400 secret file from private standard input.

        Parameters
        ----------
        volume : str
            Exact labeled volume name.
        content : str
            Private content sent only through standard input.
        owner : str
            Numeric container UID:GID owning the resulting file.
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

    def _create_config_volume(self, *, stage: str) -> None:
        """Snapshot the reviewed edge config into one run-owned volume.

        Parameters
        ----------
        stage : str
            Public resource-creation stage.

        Raises
        ------
        RehearsalError
            If preflight did not establish a reviewed configuration source.
        """
        if not self._config_source or not self._config_bytes or not self._config_digest:
            raise RehearsalError("edge_config_unavailable", stage)
        self._docker(
            "volume",
            "create",
            *self._labels(),
            self.resources.config_volume,
            stage=stage,
        )
        job_name = self._next_job_name()
        self._docker(
            "run",
            "--interactive",
            "--name",
            job_name,
            "--network",
            "none",
            "--platform",
            OCI_PLATFORM,
            *self._labels(),
            "--user",
            "0:0",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            (
                f"type=volume,source={self.resources.config_volume},"
                "target=/config,volume-nocopy"
            ),
            "--entrypoint",
            "sh",
            self.configuration.edge_image,
            "-c",
            (
                'set -eu; test -z "$(find /config -mindepth 1 -print -quit)"; '
                "umask 022; cat > /config/default.conf; "
                "chmod 0444 /config/default.conf"
            ),
            stage=stage,
            input_text=self._config_bytes,
        )
        validation_job = self._next_job_name()
        validated = self._docker(
            "run",
            "--name",
            validation_job,
            "--network",
            "none",
            "--platform",
            OCI_PLATFORM,
            *self._labels(),
            "--user",
            "0:0",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            (
                f"type=volume,source={self.resources.config_volume},"
                "target=/config,readonly,volume-nocopy"
            ),
            "--entrypoint",
            "sh",
            self.configuration.edge_image,
            "-c",
            (
                'set -eu; test "$(find /config -mindepth 1 -maxdepth 1 '
                '-print | wc -l)" -eq 1; test -f /config/default.conf; '
                "test ! -L /config/default.conf; sha256sum /config/default.conf"
            ),
            stage=stage,
        )
        match = re.fullmatch(
            r"([0-9a-f]{64})\s+/config/default\.conf\s*",
            validated.stdout,
        )
        if match is None or match.group(1) != self._config_digest:
            raise RehearsalError("edge_config_snapshot_mismatch", stage)

    def _job_container_names(self, *, stage: str) -> list[str]:
        """Discover tracked and retained one-shot jobs in this namespace.

        Parameters
        ----------
        stage : str
            Public retention or cleanup stage.

        Returns
        -------
        list[str]
            Reverse-sorted exact job names.
        """
        inventory = self._resource_names("container", stage=stage)
        pattern = re.compile(rf"{re.escape(self.resources.prefix)}-job-[0-9]{{2,}}\Z")
        names = set(self.resources.job_containers)
        names.update(name for name in inventory if pattern.fullmatch(name))
        return sorted(names, reverse=True)

    def create_isolated_resources(self) -> None:
        """Create isolated networks, data/static volumes, and secret volumes.

        Raises
        ------
        RehearsalError
            If any exact or run-labeled resource already exists.
        """
        stage = "create_isolated_resources"
        self._announce(stage)
        fixed_resources = (
            ("container", self.resources.postgres),
            ("container", self.resources.web),
            ("container", self.resources.edge),
            *(("network", network) for network in self.resources.networks),
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
            self.resources.backend_network,
            stage=stage,
        )
        self._docker(
            "network",
            "create",
            "--internal",
            *self._labels(),
            self.resources.proxy_network,
            stage=stage,
        )
        self._docker(
            "network",
            "create",
            *self._labels(),
            self.resources.ingress_network,
            stage=stage,
        )
        for volume in (self.resources.data_volume, self.resources.static_volume):
            self._docker("volume", "create", *self._labels(), volume, stage=stage)
        self._create_secret_volume(
            volume=self.resources.postgres_secret_volume,
            content=self._secrets["database"],
            owner="0:0",
            stage=stage,
        )
        self._create_secret_volume(
            volume=self.resources.app_secret_volume,
            content=_pgpass_line(self._secrets["database"]),
            owner="10001:10001",
            stage=stage,
        )
        self._create_config_volume(stage=stage)
        self._record(
            stage,
            {
                "backend_network_internal": True,
                "proxy_network_internal": True,
                "ingress_network_isolated_to_edge": True,
                "edge_database_network_access": False,
                "fresh_static_volume": True,
                "reviewed_config_snapshotted": True,
                "credentials_in_argv_or_environment": False,
            },
        )

    @staticmethod
    def _parse_static_manifest(
        payload: Mapping[str, object],
        *,
        stage: str,
    ) -> dict[str, StaticFileEvidence]:
        """Validate one canonical regular-file manifest from the candidate.

        Parameters
        ----------
        payload : Mapping[str, object]
            Decoded manifest emitted by the candidate job.
        stage : str
            Public stage requesting validation.

        Returns
        -------
        dict[str, StaticFileEvidence]
            Canonically ordered entries keyed by relative path.

        Raises
        ------
        RehearsalError
            If the shape, paths, sizes, hashes, ordering, or uniqueness differ.
        """
        if (
            set(payload) != {"files", "schema_version"}
            or payload.get("schema_version") != 1
        ):
            raise RehearsalError("static_manifest_invalid", stage)
        files = payload.get("files")
        if not isinstance(files, list) or not 0 < len(files) <= MAX_MANIFEST_FILES:
            raise RehearsalError("static_manifest_invalid", stage)
        manifest: dict[str, StaticFileEvidence] = {}
        for raw_entry in files:
            if not isinstance(raw_entry, dict) or set(raw_entry) != {
                "path",
                "sha256",
                "size",
            }:
                raise RehearsalError("static_manifest_invalid", stage)
            path = raw_entry.get("path")
            sha256 = raw_entry.get("sha256")
            size = raw_entry.get("size")
            if (
                not isinstance(path, str)
                or not path
                or path.startswith("/")
                or "\\" in path
                or "\x00" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or not isinstance(sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
                or path in manifest
            ):
                raise RehearsalError("static_manifest_invalid", stage)
            manifest[path] = StaticFileEvidence(path=path, size=size, sha256=sha256)
        if list(manifest) != sorted(manifest):
            raise RehearsalError("static_manifest_not_canonical", stage)
        return manifest

    @staticmethod
    def _static_manifest_digest(
        manifest: Mapping[str, StaticFileEvidence],
    ) -> str:
        """Return the canonical SHA-256 for one validated static manifest.

        Parameters
        ----------
        manifest : Mapping[str, StaticFileEvidence]
            Validated canonical manifest.

        Returns
        -------
        str
            Lowercase SHA-256 over canonical JSON entries.
        """
        canonical = [
            {
                "path": entry.path,
                "sha256": entry.sha256,
                "size": entry.size,
            }
            for entry in manifest.values()
        ]
        encoded = json.dumps(
            canonical,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _static_manifest_job(
        self,
        *,
        stage: str,
        mount_static_volume: bool,
    ) -> dict[str, StaticFileEvidence]:
        """Read the image or copy-up volume manifest from a hardened app job.

        Parameters
        ----------
        stage : str
            Public stage requesting the manifest.
        mount_static_volume : bool
            Whether Docker must populate and mount the named static volume.

        Returns
        -------
        dict[str, StaticFileEvidence]
            Validated canonical manifest.

        Raises
        ------
        RehearsalError
            If the job output is not a complete valid manifest.
        """
        name = self._next_job_name()
        volume_mount = (
            (
                "--mount",
                (
                    f"type=volume,source={self.resources.static_volume},"
                    "target=/app/staticfiles,readonly"
                ),
            )
            if mount_static_volume
            else ()
        )
        result = self._docker(
            "run",
            "--name",
            name,
            "--network",
            "none",
            "--platform",
            OCI_PLATFORM,
            *self._labels(),
            "--user",
            "10001:10001",
            "--read-only",
            "--tmpfs",
            _tmpfs_mount(10001, 10001),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            *volume_mount,
            "--entrypoint",
            "python",
            self.configuration.application_image,
            "-c",
            STATIC_MANIFEST_SOURCE,
            stage=stage,
        )
        try:
            payload = parse_last_json_object(result.stdout)
        except ValueError as error:
            raise RehearsalError("static_manifest_invalid", stage) from error
        return self._parse_static_manifest(payload, stage=stage)

    def capture_image_static_manifest(self) -> None:
        """Capture a canonical manifest directly from the exact app image.

        Raises
        ------
        RehearsalError
            If the manifest or any required candidate asset is unavailable.
        """
        stage = "capture_image_static_manifest"
        self._announce(stage)
        self._image_manifest = self._static_manifest_job(
            stage=stage,
            mount_static_volume=False,
        )
        missing = {
            path.removeprefix("/static/")
            for path in REQUIRED_STATIC_ASSETS
            if path.removeprefix("/static/") not in self._image_manifest
        }
        if missing:
            raise RehearsalError("required_static_asset_missing", stage)
        self._manifest_digest = self._static_manifest_digest(self._image_manifest)
        self.evidence["static_manifest"] = {
            "file_count": len(self._image_manifest),
            "byte_count": sum(entry.size for entry in self._image_manifest.values()),
            "sha256": self._manifest_digest,
        }
        self._record(
            stage,
            {
                "regular_files_only": True,
                "required_asset_count": len(REQUIRED_STATIC_ASSETS),
                "manifest_sha256": self._manifest_digest,
            },
        )

    def populate_static_volume(self) -> None:
        """Prove Docker copy-up reproduces the exact candidate static manifest.

        Raises
        ------
        RehearsalError
            If the source manifest is absent or volume bytes drift.
        """
        stage = "populate_static_volume"
        self._announce(stage)
        if not self._image_manifest or not self._manifest_digest:
            raise RehearsalError("static_manifest_unavailable", stage)
        volume_manifest = self._static_manifest_job(
            stage=stage,
            mount_static_volume=True,
        )
        if volume_manifest != self._image_manifest or (
            self._static_manifest_digest(volume_manifest) != self._manifest_digest
        ):
            raise RehearsalError("static_volume_drift", stage)
        static_evidence = self.evidence.get("static_manifest")
        if not isinstance(static_evidence, dict):
            raise RehearsalError("evidence_invalid", stage)
        static_evidence["image_volume_exact_match"] = True
        self._record(
            stage,
            {
                "docker_empty_volume_copy_up": True,
                "image_volume_exact_match": True,
                "candidate_rebuilt": False,
                "candidate_files_modified": False,
            },
        )

    def _wait_for_postgres(self, *, stage: str) -> None:
        """Wait until the exact PostgreSQL container accepts local connections.

        Parameters
        ----------
        stage : str
            Public startup stage.

        Raises
        ------
        RehearsalError
            If PostgreSQL misses the bounded readiness deadline.
        """
        deadline = time.monotonic() + self.configuration.http_timeout_seconds
        while time.monotonic() < deadline:
            result = self._docker(
                "exec",
                self.resources.postgres,
                "pg_isready",
                "--username",
                DATABASE_ROLE,
                "--dbname",
                DATABASE_NAME,
                stage=stage,
                allow_failure=True,
            )
            if result.returncode == 0:
                return
            time.sleep(1)
        raise RehearsalError("postgres_health_timeout", stage)

    def _start_postgres(self, *, stage: str) -> None:
        """Create PostgreSQL on the internal network without a host port.

        Parameters
        ----------
        stage : str
            Public startup stage.
        """
        self._docker(
            "run",
            "--detach",
            "--name",
            self.resources.postgres,
            "--network",
            self.resources.backend_network,
            "--network-alias",
            "postgres",
            "--platform",
            OCI_PLATFORM,
            *self._labels(),
            "--mount",
            (
                f"type=volume,source={self.resources.data_volume},"
                "target=/var/lib/postgresql/data"
            ),
            "--mount",
            (
                f"type=volume,source={self.resources.postgres_secret_volume},"
                "target=/run/secrets,readonly"
            ),
            "--env",
            f"POSTGRES_USER={DATABASE_ROLE}",
            "--env",
            f"POSTGRES_DB={DATABASE_NAME}",
            "--env",
            "POSTGRES_PASSWORD_FILE=/run/secrets/value",
            "--health-cmd",
            f"pg_isready -U {DATABASE_ROLE} -d {DATABASE_NAME}",
            "--health-interval",
            "2s",
            "--health-timeout",
            "3s",
            "--health-retries",
            "30",
            POSTGRES_IMAGE,
            stage=stage,
        )
        self._wait_for_postgres(stage=stage)

    def _application_environment(self) -> tuple[str, ...]:
        """Return credential-free local settings for isolated app containers.

        Returns
        -------
        tuple[str, ...]
            Repeated Docker ``--env`` arguments containing no password.
        """
        values = (
            "DJANGO_SETTINGS_MODULE=maru.settings.local",
            (
                "MARU_DATABASE_URL=postgresql://"
                f"{DATABASE_ROLE}@postgres:5432/{DATABASE_NAME}"
            ),
            "PGPASSFILE=/run/secrets/value",
            "MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE=false",
        )
        arguments: list[str] = []
        for value in values:
            arguments.extend(("--env", value))
        return tuple(arguments)

    def _app_job(
        self,
        *,
        stage: str,
        command: Sequence[str],
        input_text: str | None = None,
    ) -> str:
        """Run one hardened exact-image job against isolated PostgreSQL.

        Parameters
        ----------
        stage : str
            Public workflow stage.
        command : Sequence[str]
            Exact command after the immutable application reference.
        input_text : str | None, default=None
            Optional private standard input.

        Returns
        -------
        str
            Captured standard output retained only in memory.
        """
        name = self._next_job_name()
        interactive = ("--interactive",) if input_text is not None else ()
        result = self._docker(
            "run",
            *interactive,
            "--name",
            name,
            "--network",
            self.resources.backend_network,
            "--platform",
            OCI_PLATFORM,
            *self._labels(),
            "--user",
            "10001:10001",
            "--read-only",
            "--tmpfs",
            _tmpfs_mount(10001, 10001),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            (
                f"type=volume,source={self.resources.app_secret_volume},"
                "target=/run/secrets,readonly"
            ),
            *self._application_environment(),
            self.configuration.application_image,
            *command,
            stage=stage,
            input_text=input_text,
        )
        return result.stdout

    def initialize_application(self) -> None:
        """Migrate and seed a login-capable synthetic local application.

        Raises
        ------
        RehearsalError
            If the bounded synthetic bootstrap result differs from its contract.
        """
        stage = "initialize_application"
        self._announce(stage)
        self._start_postgres(stage=stage)
        for command in (
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
        ):
            self._app_job(stage=stage, command=command)
        bootstrap_output = self._app_job(
            stage=stage,
            command=("python", "-c", DEMO_BOOTSTRAP_SOURCE),
            input_text=self._secrets["demo_password"],
        )
        try:
            bootstrap = parse_last_json_object(bootstrap_output)
        except ValueError as error:
            raise RehearsalError("demo_bootstrap_invalid", stage) from error
        if bootstrap != {
            "schema_version": 1,
            "status": "seeded",
            "synthetic": True,
        }:
            raise RehearsalError("demo_bootstrap_invalid", stage)
        self._record(
            stage,
            {
                "migration_graph_applied": True,
                "django_check_passed": True,
                "synthetic_login_ready": True,
                "password_in_argv_or_environment": False,
            },
        )

    def _start_web(self, *, stage: str) -> None:
        """Create the exact Gunicorn candidate on the internal network.

        Parameters
        ----------
        stage : str
            Public startup stage.
        """
        self._docker(
            "run",
            "--detach",
            "--name",
            self.resources.web,
            "--network",
            self.resources.backend_network,
            "--network-alias",
            "maru-web",
            "--platform",
            OCI_PLATFORM,
            *self._labels(),
            "--user",
            "10001:10001",
            "--read-only",
            "--tmpfs",
            _tmpfs_mount(10001, 10001),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            (
                f"type=volume,source={self.resources.app_secret_volume},"
                "target=/run/secrets,readonly"
            ),
            *self._application_environment(),
            self.configuration.application_image,
            stage=stage,
        )
        self._docker(
            "network",
            "connect",
            "--alias",
            "maru-web",
            self.resources.proxy_network,
            self.resources.web,
            stage=stage,
        )

    def _start_edge(self, *, stage: str) -> None:
        """Create an unprivileged read-only edge with one loopback host port.

        Parameters
        ----------
        stage : str
            Public startup stage.

        """
        self._docker(
            "create",
            "--name",
            self.resources.edge,
            "--network",
            self.resources.ingress_network,
            "--platform",
            OCI_PLATFORM,
            "--publish",
            f"127.0.0.1::{EDGE_CONTAINER_PORT}",
            *self._labels(),
            "--user",
            "101:101",
            "--read-only",
            "--tmpfs",
            _tmpfs_mount(101, 101),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            (
                f"type=volume,source={self.resources.static_volume},"
                "target=/srv/maru/static,readonly"
            ),
            "--mount",
            (
                f"type=volume,source={self.resources.config_volume},"
                "target=/etc/nginx/conf.d,readonly"
            ),
            "--entrypoint",
            "/usr/sbin/nginx",
            self.configuration.edge_image,
            "-g",
            "daemon off;",
            stage=stage,
        )
        self._docker(
            "network",
            "connect",
            "--alias",
            "maru-edge",
            self.resources.proxy_network,
            self.resources.edge,
            stage=stage,
        )
        self._docker("start", self.resources.edge, stage=stage)
        self._refresh_edge_origin(stage=stage)
        self._require_edge_config_snapshot(stage=stage)

    def _refresh_edge_origin(self, *, stage: str) -> None:
        """Rediscover the current ephemeral loopback port after an edge start.

        Docker Desktop may allocate a different ephemeral port whenever the
        same stopped container is started. Every HTTP probe must therefore use
        a fresh, validated ``docker port`` result rather than the creation-time
        allocation.

        Parameters
        ----------
        stage : str
            Public startup or restart stage.

        Raises
        ------
        RehearsalError
            If Docker does not publish exactly one valid loopback binding.
        """
        port_result = self._docker(
            "port",
            self.resources.edge,
            f"{EDGE_CONTAINER_PORT}/tcp",
            stage=stage,
        )
        bindings = [
            line.strip() for line in port_result.stdout.splitlines() if line.strip()
        ]
        if len(bindings) != 1:
            raise RehearsalError("edge_port_binding_invalid", stage)
        match = re.fullmatch(r"127\.0\.0\.1:([0-9]{1,5})", bindings[0])
        if match is None:
            raise RehearsalError("edge_port_binding_invalid", stage)
        port = int(match.group(1))
        if not 1 <= port <= MAX_TCP_PORT:
            raise RehearsalError("edge_port_binding_invalid", stage)
        self._edge_port = port
        self._edge_origin = f"http://127.0.0.1:{port}"
        self._edge_ports_observed.append(port)
        edge_evidence = self.evidence.get("edge")
        if not isinstance(edge_evidence, dict):
            raise RehearsalError("evidence_invalid", stage)
        edge_evidence.update(
            {
                "config_sha256": self._config_digest,
                "host_binding": "127.0.0.1",
                "host_port": port,
                "host_ports_observed": list(self._edge_ports_observed),
            }
        )

    def _require_edge_config_snapshot(self, *, stage: str) -> None:
        """Require the running edge to expose the exact snapshotted config.

        Parameters
        ----------
        stage : str
            Public startup, hardening, or restart stage.

        Raises
        ------
        RehearsalError
            If the in-container config digest differs or Nginx rejects it.
        """
        digest = self._docker(
            "exec",
            self.resources.edge,
            "sha256sum",
            "/etc/nginx/conf.d/default.conf",
            stage=stage,
        )
        match = re.fullmatch(
            r"([0-9a-f]{64})\s+/etc/nginx/conf\.d/default\.conf\s*",
            digest.stdout,
        )
        if match is None or match.group(1) != self._config_digest:
            raise RehearsalError("edge_config_snapshot_mismatch", stage)
        if not self._config_source:
            raise RehearsalError("edge_config_unavailable", stage)
        effective = self._docker(
            "exec",
            self.resources.edge,
            "/usr/sbin/nginx",
            "-T",
            stage=stage,
        )
        if self._config_source.strip() not in (
            effective.stdout + "\n" + effective.stderr
        ):
            raise RehearsalError("edge_effective_config_mismatch", stage)

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> HttpResult | None:
        """Issue one bounded loopback HTTP request and retain its body in memory.

        Parameters
        ----------
        path : str
            Absolute same-origin path beginning with one or more slashes.
        method : str, default="GET"
            HTTP method.
        data : bytes | None, default=None
            Optional in-memory request body.
        headers : Mapping[str, str] | None, default=None
            Additional request headers.
        follow_redirects : bool, default=False
            Whether the opener may follow redirects.

        Returns
        -------
        HttpResult | None
            Bounded response, or ``None`` only when the endpoint is unreachable.

        Raises
        ------
        RehearsalError
            If the path is unsafe or the response exceeds its byte bound.
        """
        if not self._edge_origin or not path.startswith("/"):
            raise RehearsalError("http_request_invalid", "http_probe")
        request = urllib.request.Request(  # noqa: S310 - fixed loopback HTTP origin
            self._edge_origin + path,
            data=data,
            headers={
                "User-Agent": "Maru OCI static delivery evaluator",
                **dict(headers or {}),
            },
            method=method,
        )
        opener = self._opener if follow_redirects else self._no_redirect_opener
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        except (OSError, TimeoutError, urllib.error.URLError):
            return None
        try:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise RehearsalError("http_response_too_large", "http_probe")
            return HttpResult(
                status=int(response.status),
                headers=_headers_as_mapping(response.headers),
                body=body,
            )
        finally:
            response.close()

    def _wait_for_status(
        self,
        path: str,
        expected: frozenset[int],
        *,
        stage: str,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResult:
        """Wait for one edge path to return any explicitly accepted status.

        Parameters
        ----------
        path : str
            Absolute same-origin path.
        expected : frozenset[int]
            Explicitly accepted HTTP statuses.
        stage : str
            Public workflow stage.
        headers : Mapping[str, str] | None, default=None
            Optional request headers, including content negotiation.

        Returns
        -------
        HttpResult
            First accepted bounded response.

        Raises
        ------
        RehearsalError
            If the path misses the bounded status deadline.
        """
        deadline = time.monotonic() + self.configuration.http_timeout_seconds
        while time.monotonic() < deadline:
            result = self._request(path, headers=headers)
            if result is not None and result.status in expected:
                return result
            time.sleep(1)
        raise RehearsalError("http_status_timeout", stage)

    def _wait_until_unreachable(self, *, stage: str) -> None:
        """Wait until the stopped edge loopback endpoint cannot be reached.

        Parameters
        ----------
        stage : str
            Public restart stage.

        Raises
        ------
        RehearsalError
            If the stopped edge remains reachable.
        """
        deadline = time.monotonic() + min(
            self.configuration.http_timeout_seconds,
            30,
        )
        while time.monotonic() < deadline:
            if self._request("/health/live") is None:
                return
            time.sleep(0.5)
        raise RehearsalError("stopped_edge_reachable", stage)

    @staticmethod
    def _json_object(result: HttpResult, *, stage: str) -> dict[str, object]:
        """Decode one bounded HTTP body as a top-level JSON object.

        Parameters
        ----------
        result : HttpResult
            Bounded HTTP response.
        stage : str
            Public workflow stage.

        Returns
        -------
        dict[str, object]
            Decoded top-level object.

        Raises
        ------
        RehearsalError
            If the body is not a valid top-level JSON object.
        """
        try:
            payload = json.loads(result.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RehearsalError("http_json_invalid", stage) from error
        if not isinstance(payload, dict):
            raise RehearsalError("http_json_invalid", stage)
        return payload

    @staticmethod
    def _html_parser(result: HttpResult, *, stage: str) -> _HtmlReferenceParser:
        """Decode one bounded HTML response and collect references.

        Parameters
        ----------
        result : HttpResult
            Bounded HTTP response.
        stage : str
            Public workflow stage.

        Returns
        -------
        _HtmlReferenceParser
            Completed bounded reference parser.

        Raises
        ------
        RehearsalError
            If MIME or UTF-8 encoding is invalid.
        """
        if _content_type(result) != "text/html":
            raise RehearsalError("html_content_type_invalid", stage)
        try:
            source = result.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RehearsalError("html_encoding_invalid", stage) from error
        parser = _HtmlReferenceParser()
        parser.feed(source)
        parser.close()
        return parser

    def _same_origin_paths(
        self,
        references: Sequence[str],
        *,
        stage: str,
    ) -> set[str]:
        """Resolve references and reject every non-loopback origin.

        Parameters
        ----------
        references : Sequence[str]
            HTML or manifest references.
        stage : str
            Public workflow stage.

        Returns
        -------
        set[str]
            Same-origin paths with any query preserved.

        Raises
        ------
        RehearsalError
            If any reference resolves outside the exact edge origin.
        """
        origin = urllib.parse.urlsplit(self._edge_origin)
        paths: set[str] = set()
        for reference in references:
            resolved = urllib.parse.urlsplit(
                urllib.parse.urljoin(self._edge_origin + "/", reference)
            )
            if resolved.scheme not in {"http", "https"} or (
                resolved.scheme,
                resolved.netloc,
            ) != (origin.scheme, origin.netloc):
                raise RehearsalError("third_party_asset_reference", stage)
            path = resolved.path
            if resolved.query:
                path = f"{path}?{resolved.query}"
            paths.add(path)
        return paths

    def _documentation_static_paths(
        self,
        references: Sequence[str],
        *,
        stage: str,
    ) -> set[str]:
        """Require every documentation resource reference below ``/static/``.

        Parameters
        ----------
        references : Sequence[str]
            Server-rendered script, stylesheet, icon, and image references.
        stage : str
            Public documentation stage.

        Returns
        -------
        set[str]
            Exact same-origin static paths without query components.

        Raises
        ------
        RehearsalError
            If a reference is off-origin or enters a dynamic same-origin route.
        """
        resolved = self._same_origin_paths(references, stage=stage)
        paths = {urllib.parse.urlsplit(reference).path for reference in resolved}
        if any(not path.startswith("/static/") for path in paths):
            raise RehearsalError(
                "documentation_non_static_asset_reference",
                stage,
            )
        return paths

    def _require_no_store(self, result: HttpResult, *, stage: str) -> None:
        """Require a dynamic or private response to prohibit shared caching.

        Parameters
        ----------
        result : HttpResult
            Dynamic or private HTTP response.
        stage : str
            Public workflow stage.

        Raises
        ------
        RehearsalError
            If ``Cache-Control`` omits ``no-store``.
        """
        directives = {
            directive.strip().casefold()
            for directive in result.headers.get("cache-control", "").split(",")
        }
        if "no-store" not in directives:
            raise RehearsalError("dynamic_cache_boundary_invalid", stage)

    @staticmethod
    def _require_edge_owned_not_found(
        result: HttpResult | None,
        *,
        stage: str,
    ) -> None:
        """Require a compact edge denial rather than a Django fallback.

        Parameters
        ----------
        result : HttpResult | None
            Response to one raw immutable or media namespace escape probe.
        stage : str
            Public static-delivery stage.

        Raises
        ------
        RehearsalError
            If the request is unreachable, succeeds, or reaches Django.
        """
        if (
            result is None
            or result.status != HTTP_NOT_FOUND
            or result.headers.get("x-request-id")
            or len(result.body) > MAX_EDGE_DENIAL_BYTES
        ):
            raise RehearsalError("edge_namespace_escape_invalid", stage)

    @staticmethod
    def _require_dynamic_cache_separation(
        result: HttpResult,
        *,
        stage: str,
    ) -> None:
        """Reject the public static cache policy on a dynamic response.

        Parameters
        ----------
        result : HttpResult
            Dynamic edge response.
        stage : str
            Public workflow stage.

        Raises
        ------
        RehearsalError
            If a dynamic response inherits the static revalidation policy or
            advertises immutable caching.
        """
        directives = {
            directive.strip().casefold()
            for directive in result.headers.get("cache-control", "").split(",")
            if directive.strip()
        }
        static_policy = {"public", "max-age=0", "must-revalidate"}
        if "immutable" in directives or static_policy <= directives:
            raise RehearsalError("dynamic_cache_boundary_invalid", stage)

    @staticmethod
    def _require_static_revalidation_cache(
        result: HttpResult,
        *,
        stage: str,
    ) -> None:
        """Require the safe public revalidation policy on a static response.

        Parameters
        ----------
        result : HttpResult
            Successful or denied static edge response.
        stage : str
            Public workflow stage.

        Raises
        ------
        RehearsalError
            If the cache policy permits immutable or stale reuse.
        """
        directives = {
            directive.strip().casefold()
            for directive in result.headers.get("cache-control", "").split(",")
            if directive.strip()
        }
        if (
            not {"public", "max-age=0", "must-revalidate"} <= directives
            or "immutable" in directives
        ):
            raise RehearsalError("static_cache_boundary_invalid", stage)

    def _static_manifest_entry(
        self,
        path: str,
        *,
        stage: str,
    ) -> StaticFileEvidence:
        """Resolve one `/static/` URL to its candidate manifest entry.

        Parameters
        ----------
        path : str
            Exact query-free static path.
        stage : str
            Public workflow stage.

        Returns
        -------
        StaticFileEvidence
            Exact candidate manifest entry.

        Raises
        ------
        RehearsalError
            If the path is unsafe or absent from the candidate manifest.
        """
        parsed = urllib.parse.urlsplit(path)
        if parsed.query or not parsed.path.startswith("/static/"):
            raise RehearsalError("static_path_invalid", stage)
        relative = parsed.path.removeprefix("/static/")
        entry = self._image_manifest.get(relative)
        if entry is None:
            raise RehearsalError("static_manifest_entry_missing", stage)
        return entry

    @staticmethod
    def _require_redoc_edge_representation(
        entry: StaticFileEvidence,
        result: HttpResult,
        *,
        stage: str,
    ) -> None:
        """Require the pinned candidate bundle and its one edge-only rewrite.

        Parameters
        ----------
        entry : StaticFileEvidence
            Exact source bundle evidence from the candidate image manifest.
        result : HttpResult
            JavaScript representation returned by the reference edge.
        stage : str
            Public workflow stage.

        Raises
        ------
        RehearsalError
            If the candidate bytes, deterministic rewrite, or validators drift.
        """
        if (
            entry.size != REDOC_BUNDLE_SOURCE_SIZE
            or entry.sha256 != REDOC_BUNDLE_SOURCE_SHA256
        ):
            raise RehearsalError("redoc_source_bundle_mismatch", stage)
        body = result.body
        if (
            len(body) != REDOC_BUNDLE_EDGE_SIZE
            or hashlib.sha256(body).hexdigest() != REDOC_BUNDLE_EDGE_SHA256
            or REDOC_REMOTE_LOGO_URL in body
            or body.count(REDOC_LOCAL_LOGO_DATA_URL) != 1
        ):
            raise RehearsalError("redoc_edge_transform_invalid", stage)
        forbidden_headers = (
            "accept-ranges",
            "content-encoding",
            "content-length",
            "content-range",
            "etag",
            "last-modified",
        )
        if any(result.headers.get(name) for name in forbidden_headers):
            raise RehearsalError("redoc_edge_header_invalid", stage)

    def _verify_redoc_replay_boundaries(
        self,
        entry: StaticFileEvidence,
        path: str,
        expected_mime: frozenset[str],
        *,
        stage: str,
    ) -> None:
        """Reject conditional or range paths around the ReDoc body filter.

        Parameters
        ----------
        entry : StaticFileEvidence
            Exact source bundle evidence from the candidate image manifest.
        path : str
            Exact edge URL for the transformed ReDoc bundle.
        expected_mime : frozenset[str]
            Accepted JavaScript media types.
        stage : str
            Public workflow stage.

        Raises
        ------
        RehearsalError
            If a request bypasses or changes the complete edge representation.
        """
        for method in ("GET", "HEAD"):
            wildcard = self._request(
                path,
                method=method,
                headers={"If-None-Match": "*"},
            )
            if (
                wildcard is None
                or wildcard.status != HTTP_NOT_MODIFIED
                or wildcard.body
                or wildcard.headers.get("etag")
                or wildcard.headers.get("last-modified")
            ):
                raise RehearsalError("redoc_wildcard_validator_invalid", stage)
            self._require_static_revalidation_cache(wildcard, stage=stage)
        unsafe_wildcard = self._request(
            path,
            method="POST",
            headers={"If-None-Match": "*"},
        )
        if (
            unsafe_wildcard is None
            or unsafe_wildcard.status not in {HTTP_FORBIDDEN, HTTP_METHOD_NOT_ALLOWED}
            or unsafe_wildcard.headers.get("etag")
            or unsafe_wildcard.headers.get("last-modified")
        ):
            raise RehearsalError("redoc_unsafe_wildcard_invalid", stage)
        probes = (
            (
                "redoc_stale_validator_boundary_invalid",
                {"If-None-Match": '"candidate-source"'},
            ),
            (
                "redoc_range_boundary_invalid",
                {"Range": "bytes=0-255"},
            ),
            (
                "redoc_revalidation_boundary_invalid",
                {"If-Modified-Since": "Wed, 31 Dec 2099 23:59:59 GMT"},
            ),
        )
        for error_code, headers in probes:
            repeated = self._request(path, headers=headers)
            if (
                repeated is None
                or repeated.status != HTTP_OK
                or _content_type(repeated) not in expected_mime
            ):
                raise RehearsalError(error_code, stage)
            self._require_redoc_edge_representation(entry, repeated, stage=stage)
            self._require_static_revalidation_cache(repeated, stage=stage)
            if (
                repeated.headers.get(
                    "x-content-type-options",
                    "",
                ).casefold()
                != "nosniff"
            ):
                raise RehearsalError("static_nosniff_missing", stage)

    def _verify_one_static_asset(
        self,
        path: str,
        *,
        stage: str,
        conditional: bool = True,
    ) -> None:
        """Require status, MIME, bytes, cache, and conditional delivery.

        The exact ReDoc source bundle is the sole explicit representation
        exception: its image/volume hash remains pinned while the edge replaces
        one remote attribution-image URL with an inert data URL. That response
        exposes no source-file validator and rejects range bypasses.

        Parameters
        ----------
        path : str
            Exact static URL path.
        stage : str
            Public workflow stage.
        conditional : bool, default=True
            Whether to require a validator-driven 304 response.

        Raises
        ------
        RehearsalError
            If status, MIME, bytes, cache, nosniff, or validation differs.
        """
        entry = self._static_manifest_entry(path, stage=stage)
        result = self._wait_for_status(path, frozenset({HTTP_OK}), stage=stage)
        suffix = Path(urllib.parse.urlsplit(path).path).suffix.casefold()
        expected_mime = EXPECTED_MIME_TYPES.get(suffix)
        if expected_mime is None or _content_type(result) not in expected_mime:
            raise RehearsalError("static_mime_invalid", stage)
        is_redoc_bundle = urllib.parse.urlsplit(path).path == REDOC_BUNDLE_PATH
        if is_redoc_bundle:
            self._require_redoc_edge_representation(entry, result, stage=stage)
        elif len(result.body) != entry.size or (
            hashlib.sha256(result.body).hexdigest() != entry.sha256
        ):
            raise RehearsalError("static_response_drift", stage)
        self._require_static_revalidation_cache(result, stage=stage)
        if result.headers.get("x-content-type-options", "").casefold() != "nosniff":
            raise RehearsalError("static_nosniff_missing", stage)
        if is_redoc_bundle:
            self._verify_redoc_replay_boundaries(
                entry,
                path,
                expected_mime,
                stage=stage,
            )
            return
        validator_name = "if-none-match"
        validator_value = result.headers.get("etag", "")
        if not validator_value:
            validator_name = "if-modified-since"
            validator_value = result.headers.get("last-modified", "")
        if not validator_value:
            raise RehearsalError("static_validator_missing", stage)
        if conditional:
            repeated = self._request(
                path,
                headers={validator_name: validator_value},
            )
            if repeated is None or repeated.status != HTTP_NOT_MODIFIED:
                raise RehearsalError("static_conditional_request_invalid", stage)

    def start_delivery_topology(self) -> None:
        """Start internal Gunicorn and the only loopback-published edge.

        Raises
        ------
        RehearsalError
            If the edge cannot return the minimized liveness contract.
        """
        stage = "start_delivery_topology"
        self._announce(stage)
        self._start_web(stage=stage)
        self._start_edge(stage=stage)
        live = self._wait_for_status(
            "/health/live",
            frozenset({HTTP_OK}),
            stage=stage,
        )
        if self._json_object(live, stage=stage) != {"status": "ok"}:
            raise RehearsalError("liveness_contract_invalid", stage)
        self._require_dynamic_cache_separation(live, stage=stage)
        self._record(
            stage,
            {
                "gunicorn_internal_only": True,
                "edge_loopback_only": True,
                "edge_host_port": self._edge_port,
                "static_mount_read_only": True,
            },
        )

    def verify_dynamic_boundary(self) -> None:
        """Prove landing, health, and build responses traverse the edge.

        Raises
        ------
        RehearsalError
            If liveness, build identity, HTML, or landing references differ.
        """
        stage = "verify_dynamic_boundary"
        self._announce(stage)
        live = self._wait_for_status(
            "/health/live",
            frozenset({HTTP_OK}),
            stage=stage,
        )
        if self._json_object(live, stage=stage) != {"status": "ok"}:
            raise RehearsalError("liveness_contract_invalid", stage)
        self._require_dynamic_cache_separation(live, stage=stage)
        build_result = self._wait_for_status(
            "/api/v1/meta/build",
            frozenset({HTTP_OK}),
            stage=stage,
        )
        build = self._json_object(build_result, stage=stage)
        self._require_dynamic_cache_separation(build_result, stage=stage)
        if (
            set(build) != {"commit", "service", "version"}
            or build.get("service") != "maru"
            or build.get("commit") != self.configuration.source_revision
            or not isinstance(build.get("version"), str)
            or not build.get("version")
        ):
            raise RehearsalError("build_identity_mismatch", stage)
        self._build_identity = {
            "version": build["version"],
            "commit": build["commit"],
        }
        landing = self._wait_for_status("/", frozenset({HTTP_OK}), stage=stage)
        self._require_dynamic_cache_separation(landing, stage=stage)
        parser = self._html_parser(landing, stage=stage)
        references = self._same_origin_paths(parser.references, stage=stage)
        self._landing_references = {
            urllib.parse.urlsplit(path).path
            for path in references
            if urllib.parse.urlsplit(path).path.startswith("/static/")
        }
        if not set(LANDING_ASSETS) <= self._landing_references:
            raise RehearsalError("landing_static_references_missing", stage)
        self._record(
            stage,
            {
                "live_http": HTTP_OK,
                "build_identity": self._build_identity,
                "landing_http": HTTP_OK,
                "landing_static_reference_count": len(self._landing_references),
                "dynamic_upstream": "gunicorn",
            },
        )

    def verify_static_delivery(self) -> None:
        """Prove exact static bytes, MIME, cache, denial, and manifest icons.

        Raises
        ------
        RehearsalError
            If any asset, icon, validator, denial, or media boundary differs.
        """
        stage = "verify_static_delivery"
        self._announce(stage)
        for path in LANDING_ASSETS:
            self._verify_one_static_asset(path, stage=stage)

        manifest_result = self._wait_for_status(
            "/static/core/brand/site.webmanifest",
            frozenset({HTTP_OK}),
            stage=stage,
        )
        manifest = self._json_object(manifest_result, stage=stage)
        icons = manifest.get("icons")
        if not isinstance(icons, list):
            raise RehearsalError("webmanifest_icons_invalid", stage)
        icon_references: list[str] = []
        for icon in icons:
            if not isinstance(icon, dict) or not isinstance(icon.get("src"), str):
                raise RehearsalError("webmanifest_icons_invalid", stage)
            icon_references.append(icon["src"])
        resolved_icons = self._same_origin_paths(icon_references, stage=stage)
        self._manifest_icon_references = {
            urllib.parse.urlsplit(path).path for path in resolved_icons
        }
        if self._manifest_icon_references != set(MANIFEST_ICON_ASSETS):
            raise RehearsalError("webmanifest_icons_invalid", stage)
        for path in MANIFEST_ICON_ASSETS:
            self._verify_one_static_asset(path, stage=stage)

        for path in STATIC_DYNAMIC_ESCAPE_PROBES:
            self._require_edge_owned_not_found(
                self._request(path),
                stage=stage,
            )
        for path in MEDIA_DYNAMIC_ESCAPE_PROBES:
            self._require_edge_owned_not_found(
                self._request(path),
                stage=stage,
            )

        missing = self._request("/static/core/brand/not-present-oci-probe.css")
        if missing is None or missing.status != HTTP_NOT_FOUND:
            raise RehearsalError("missing_static_fallback_invalid", stage)
        self._require_static_revalidation_cache(missing, stage=stage)
        method_denied = self._request(
            "/static/core/brand.css",
            method="POST",
            data=b"probe=denied",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if method_denied is None or method_denied.status not in {
            HTTP_FORBIDDEN,
            HTTP_METHOD_NOT_ALLOWED,
        }:
            raise RehearsalError("static_method_boundary_invalid", stage)
        self._require_static_revalidation_cache(method_denied, stage=stage)
        media = self._request("/media/oci-static-delivery-probe.txt")
        if media is None or media.status != HTTP_NOT_FOUND:
            raise RehearsalError("media_boundary_invalid", stage)
        self._require_no_store(media, stage=stage)
        self._record(
            stage,
            {
                "landing_assets_verified": len(LANDING_ASSETS),
                "manifest_icons_verified": len(MANIFEST_ICON_ASSETS),
                "conditional_http": HTTP_NOT_MODIFIED,
                "missing_static_http": HTTP_NOT_FOUND,
                "static_mutation_denied": True,
                "static_escape_probes_denied": len(STATIC_DYNAMIC_ESCAPE_PROBES),
                "media_escape_probes_denied": len(MEDIA_DYNAMIC_ESCAPE_PROBES),
                "media_exposed": False,
                "static_fallback_to_application": False,
            },
        )

    def _login_synthetic_administrator(self, *, stage: str) -> set[str]:
        """Authenticate through the edge with an in-memory CSRF and cookie jar.

        Parameters
        ----------
        stage : str
            Public documentation stage.

        Returns
        -------
        set[str]
            Same-origin static paths referenced by the login page.

        Raises
        ------
        RehearsalError
            If login assets, CSRF, credentials, or redirect behavior differ.
        """
        login_path = "/accounts/login/?next=/api/v1/docs/"
        login = self._wait_for_status(
            login_path,
            frozenset({HTTP_OK}),
            stage=stage,
        )
        parser = self._html_parser(login, stage=stage)
        token = parser.inputs.get("csrfmiddlewaretoken", "")
        if not token or len(token) > MAX_CSRF_TOKEN_LENGTH:
            raise RehearsalError("login_csrf_invalid", stage)
        references = self._same_origin_paths(parser.references, stage=stage)
        login_static = {
            urllib.parse.urlsplit(path).path
            for path in references
            if urllib.parse.urlsplit(path).path.startswith("/static/")
        }
        if not set(LOGIN_ASSETS) <= login_static:
            raise RehearsalError("login_static_references_missing", stage)
        for path in sorted(login_static):
            self._verify_one_static_asset(path, stage=stage, conditional=False)

        encoded = urllib.parse.urlencode(
            {
                "csrfmiddlewaretoken": token,
                "next": "/api/v1/docs/",
                "password": self._secrets["demo_password"],
                "username": DEMO_ADMIN_EMAIL,
            }
        ).encode()
        response = self._request(
            login_path,
            method="POST",
            data=encoded,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self._edge_origin,
                "Referer": self._edge_origin + login_path,
            },
        )
        if response is None or response.status not in {302, 303}:
            raise RehearsalError("synthetic_login_failed", stage)
        location = response.headers.get("location", "")
        if not location.startswith("/api/v1/docs/"):
            raise RehearsalError("synthetic_login_failed", stage)
        return login_static

    @staticmethod
    def _require_private_documentation_headers(
        result: HttpResult,
        *,
        stage: str,
    ) -> None:
        """Require the application-owned private documentation header contract.

        Parameters
        ----------
        result : HttpResult
            Schema, Swagger, or ReDoc response.
        stage : str
            Public documentation stage.

        Raises
        ------
        RehearsalError
            If cache, robot, or opener policy headers differ.
        """
        directives = {
            directive.strip().casefold()
            for directive in result.headers.get("cache-control", "").split(",")
        }
        if not {"private", "no-store", "max-age=0"} <= directives:
            raise RehearsalError("private_documentation_headers_invalid", stage)
        if (
            result.headers.get("pragma", "").casefold() != "no-cache"
            or result.headers.get("x-robots-tag", "").casefold()
            != "noindex, nofollow, noarchive"
            or result.headers.get("cross-origin-opener-policy", "").casefold()
            != "same-origin"
        ):
            raise RehearsalError("private_documentation_headers_invalid", stage)

    def verify_private_api_documentation(self) -> None:
        """Prove private same-origin schema, Swagger, ReDoc, and sidecars.

        Raises
        ------
        RehearsalError
            If authorization, OpenAPI, headers, assets, or origins differ.
        """
        stage = "verify_private_api_documentation"
        self._announce(stage)
        anonymous_schema = self._wait_for_status(
            "/api/v1/schema",
            frozenset({HTTP_FORBIDDEN}),
            stage=stage,
            headers={"Accept": "application/vnd.oai.openapi+json"},
        )
        self._require_private_documentation_headers(
            anonymous_schema,
            stage=stage,
        )
        for path in ("/api/v1/docs/", "/api/v1/redoc/"):
            denied = self._request(path)
            if denied is None or denied.status not in {302, 303}:
                raise RehearsalError("anonymous_documentation_boundary_invalid", stage)
            if not denied.headers.get("location", "").startswith("/accounts/login/"):
                raise RehearsalError("anonymous_documentation_boundary_invalid", stage)
            self._require_no_store(denied, stage=stage)

        login_assets = self._login_synthetic_administrator(stage=stage)
        schema_result = self._wait_for_status(
            "/api/v1/schema",
            frozenset({HTTP_OK}),
            stage=stage,
            headers={"Accept": "application/vnd.oai.openapi+json"},
        )
        if _content_type(schema_result) not in {
            "application/json",
            "application/vnd.oai.openapi+json",
        }:
            raise RehearsalError("openapi_content_type_invalid", stage)
        schema = self._json_object(schema_result, stage=stage)
        if schema.get("openapi") != "3.1.0":
            raise RehearsalError("openapi_contract_invalid", stage)
        self._require_private_documentation_headers(schema_result, stage=stage)

        documentation_references: set[str] = set()
        for path in ("/api/v1/docs/", "/api/v1/redoc/"):
            page = self._wait_for_status(path, frozenset({HTTP_OK}), stage=stage)
            self._require_private_documentation_headers(page, stage=stage)
            parser = self._html_parser(page, stage=stage)
            try:
                source = page.body.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RehearsalError("html_encoding_invalid", stage) from error
            normalized_source = source.casefold()
            if "/api/v1/schema" not in source or any(
                forbidden in normalized_source
                for forbidden in FORBIDDEN_DOCUMENTATION_ORIGINS
            ):
                raise RehearsalError("documentation_origin_invalid", stage)
            documentation_references.update(
                self._documentation_static_paths(
                    parser.references,
                    stage=stage,
                )
            )
        if not set(DOCUMENTATION_ASSETS) <= documentation_references:
            raise RehearsalError("documentation_static_references_missing", stage)
        for path in sorted(documentation_references):
            self._verify_one_static_asset(path, stage=stage, conditional=False)
        self._documentation_references = documentation_references
        self._record(
            stage,
            {
                "anonymous_schema_http": HTTP_FORBIDDEN,
                "anonymous_html_redirected": True,
                "synthetic_platform_login": True,
                "login_assets_verified": len(login_assets),
                "openapi_version": "3.1.0",
                "swagger_http": HTTP_OK,
                "redoc_http": HTTP_OK,
                "redoc_remote_logo_localized_at_edge": True,
                "redoc_source_bundle": {
                    "sha256": REDOC_BUNDLE_SOURCE_SHA256,
                    "size": REDOC_BUNDLE_SOURCE_SIZE,
                },
                "redoc_edge_representation": {
                    "sha256": REDOC_BUNDLE_EDGE_SHA256,
                    "size": REDOC_BUNDLE_EDGE_SIZE,
                },
                "documentation_asset_count": len(documentation_references),
                "third_party_server_html_references": 0,
                "private_artifacts_recorded": False,
            },
        )

    def _inspect_container(self, name: str, *, stage: str) -> dict[str, object]:
        """Return the one structured Docker container inspection record.

        Parameters
        ----------
        name : str
            Exact container name.
        stage : str
            Public hardening or cleanup stage.

        Returns
        -------
        dict[str, object]
            The sole structured container record.

        Raises
        ------
        RehearsalError
            If Docker does not return exactly one valid record.
        """
        result = self._docker("container", "inspect", name, stage=stage)
        try:
            inspected = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RehearsalError("container_inspection_invalid", stage) from error
        if (
            not isinstance(inspected, list)
            or len(inspected) != 1
            or not isinstance(inspected[0], dict)
        ):
            raise RehearsalError("container_inspection_invalid", stage)
        return inspected[0]

    @staticmethod
    def _container_mounts(
        inspection: Mapping[str, object],
        *,
        stage: str,
    ) -> list[dict[str, object]]:
        """Return a container's structured mount list fail closed.

        Parameters
        ----------
        inspection : Mapping[str, object]
            Structured container inspection record.
        stage : str
            Public hardening stage.

        Returns
        -------
        list[dict[str, object]]
            Structured mount records.

        Raises
        ------
        RehearsalError
            If mount inspection is malformed.
        """
        mounts = inspection.get("Mounts")
        if not isinstance(mounts, list) or any(
            not isinstance(mount, dict) for mount in mounts
        ):
            raise RehearsalError("container_inspection_invalid", stage)
        return mounts

    @staticmethod
    def _container_networks(
        inspection: Mapping[str, object],
        *,
        stage: str,
    ) -> frozenset[str]:
        """Return the exact set of networks attached to one container.

        Parameters
        ----------
        inspection : Mapping[str, object]
            Structured container inspection record.
        stage : str
            Public hardening stage.

        Returns
        -------
        frozenset[str]
            Exact Docker network names.

        Raises
        ------
        RehearsalError
            If network inspection is malformed.
        """
        network_settings = inspection.get("NetworkSettings")
        if not isinstance(network_settings, dict):
            raise RehearsalError("container_inspection_invalid", stage)
        networks = network_settings.get("Networks")
        if not isinstance(networks, dict) or any(
            not isinstance(name, str) or not isinstance(details, dict)
            for name, details in networks.items()
        ):
            raise RehearsalError("container_inspection_invalid", stage)
        return frozenset(networks)

    @staticmethod
    def _require_exact_named_mounts(
        mounts: Sequence[Mapping[str, object]],
        *,
        expected: Mapping[str, tuple[str, bool]],
        stage: str,
    ) -> None:
        """Require one exact set of named-volume destinations and modes.

        Parameters
        ----------
        mounts : Sequence[Mapping[str, object]]
            Structured Docker mount records.
        expected : Mapping[str, tuple[str, bool]]
            Destination mapped to exact volume name and expected writable flag.
        stage : str
            Public hardening stage.

        Raises
        ------
        RehearsalError
            If a mount is missing, duplicated, writable unexpectedly, or extra.
        """
        if len(mounts) != len(expected):
            raise RehearsalError("container_mount_boundary_invalid", stage)
        observed: dict[str, tuple[str, bool]] = {}
        for mount in mounts:
            destination = mount.get("Destination")
            name = mount.get("Name")
            writable = mount.get("RW")
            if (
                mount.get("Type") != "volume"
                or not isinstance(destination, str)
                or not isinstance(name, str)
                or not isinstance(writable, bool)
                or destination in observed
            ):
                raise RehearsalError("container_mount_boundary_invalid", stage)
            observed[destination] = (name, writable)
        if observed != dict(expected):
            raise RehearsalError("container_mount_boundary_invalid", stage)

    @staticmethod
    def _require_hardened_container(
        inspection: Mapping[str, object],
        *,
        expected_user: frozenset[str],
        stage: str,
    ) -> None:
        """Require explicit non-root, read-only, capability-free execution.

        Parameters
        ----------
        inspection : Mapping[str, object]
            Structured container inspection record.
        expected_user : frozenset[str]
            Accepted explicit numeric user spellings.
        stage : str
            Public hardening stage.

        Raises
        ------
        RehearsalError
            If user, root filesystem, privileges, capabilities, or tmpfs differ.
        """
        config = inspection.get("Config")
        host_config = inspection.get("HostConfig")
        if not isinstance(config, dict) or not isinstance(host_config, dict):
            raise RehearsalError("container_inspection_invalid", stage)
        cap_drop = host_config.get("CapDrop")
        cap_add = host_config.get("CapAdd")
        security_options = host_config.get("SecurityOpt")
        tmpfs = host_config.get("Tmpfs")
        user = str(config.get("User", ""))
        if (
            user not in expected_user
            or host_config.get("ReadonlyRootfs") is not True
            or host_config.get("Privileged") is not False
            or not isinstance(cap_drop, list)
            or {str(value).casefold() for value in cap_drop} != {"all"}
            or cap_add not in (None, [])
            or not isinstance(security_options, list)
            or "no-new-privileges:true" not in security_options
        ):
            raise RehearsalError("container_hardening_invalid", stage)
        if (
            not isinstance(tmpfs, dict)
            or set(tmpfs) != {TMPFS_PATH}
            or not isinstance(tmpfs.get(TMPFS_PATH), str)
        ):
            raise RehearsalError("container_tmpfs_invalid", stage)
        uid, separator, configured_gid = user.partition(":")
        gid = configured_gid if separator else uid
        expected_tmpfs = {
            "rw",
            "noexec",
            "nosuid",
            "nodev",
            "mode=0700",
            f"uid={uid}",
            f"gid={gid}",
            f"size={TMPFS_SIZE_BYTES}",
        }
        observed_tmpfs = {
            value.strip().casefold()
            for value in tmpfs[TMPFS_PATH].split(",")
            if value.strip()
        }
        if observed_tmpfs != expected_tmpfs:
            raise RehearsalError("container_tmpfs_invalid", stage)

    @staticmethod
    def _port_bindings(
        inspection: Mapping[str, object],
        *,
        stage: str,
    ) -> dict[str, object]:
        """Return a container's structured host-port bindings.

        Parameters
        ----------
        inspection : Mapping[str, object]
            Structured container inspection record.
        stage : str
            Public hardening stage.

        Returns
        -------
        dict[str, object]
            Structured host port bindings, or an empty mapping.

        Raises
        ------
        RehearsalError
            If host-port inspection is malformed.
        """
        host_config = inspection.get("HostConfig")
        if not isinstance(host_config, dict):
            raise RehearsalError("container_inspection_invalid", stage)
        bindings = host_config.get("PortBindings")
        if bindings is None:
            return {}
        if not isinstance(bindings, dict):
            raise RehearsalError("container_inspection_invalid", stage)
        return bindings

    @staticmethod
    def _require_edge_loopback_binding(
        inspection: Mapping[str, object],
        *,
        host_port: int,
        stage: str,
    ) -> None:
        """Require one requested and one allocated loopback edge binding.

        Docker retains an empty ``HostPort`` in ``HostConfig.PortBindings``
        when the operator requests an ephemeral port. The allocated port is
        reported separately in ``NetworkSettings.Ports``. Some engines copy
        the allocated value into both fields, so accept either representation
        while requiring the runtime mapping to equal the port returned by
        ``docker port``.

        Parameters
        ----------
        inspection : Mapping[str, object]
            Structured edge-container inspection record.
        host_port : int
            Allocated loopback port previously returned by Docker.
        stage : str
            Public workflow stage performing the inspection.

        Raises
        ------
        RehearsalError
            If the requested or allocated binding is missing, expanded, or
            exposed beyond IPv4 loopback.
        """
        expected_port = f"{EDGE_CONTAINER_PORT}/tcp"
        requested = OciStaticDeliveryRehearsal._port_bindings(
            inspection,
            stage=stage,
        )
        if set(requested) != {expected_port}:
            raise RehearsalError("edge_port_binding_invalid", stage)
        requested_values = requested.get(expected_port)
        if not isinstance(requested_values, list) or len(requested_values) != 1:
            raise RehearsalError("edge_port_binding_invalid", stage)
        requested_binding = requested_values[0]
        if (
            not isinstance(requested_binding, dict)
            or requested_binding.get("HostIp") != "127.0.0.1"
            or requested_binding.get("HostPort") not in {"", str(host_port)}
        ):
            raise RehearsalError("edge_port_binding_invalid", stage)

        network_settings = inspection.get("NetworkSettings")
        if not isinstance(network_settings, dict):
            raise RehearsalError("container_inspection_invalid", stage)
        runtime = network_settings.get("Ports")
        if not isinstance(runtime, dict) or set(runtime) != {expected_port}:
            raise RehearsalError("edge_port_binding_invalid", stage)
        runtime_values = runtime.get(expected_port)
        if not isinstance(runtime_values, list) or len(runtime_values) != 1:
            raise RehearsalError("edge_port_binding_invalid", stage)
        runtime_binding = runtime_values[0]
        if (
            not isinstance(runtime_binding, dict)
            or runtime_binding.get("HostIp") != "127.0.0.1"
            or runtime_binding.get("HostPort") != str(host_port)
        ):
            raise RehearsalError("edge_port_binding_invalid", stage)

    def verify_runtime_hardening(self) -> None:
        """Inspect users, filesystems, mounts, networks, and host ports.

        Raises
        ------
        RehearsalError
            If any runtime isolation or effective-user contract differs.
        """
        stage = "verify_runtime_hardening"
        self._announce(stage)
        postgres = self._inspect_container(self.resources.postgres, stage=stage)
        web = self._inspect_container(self.resources.web, stage=stage)
        edge = self._inspect_container(self.resources.edge, stage=stage)
        self._require_hardened_container(
            web,
            expected_user=EXPECTED_APP_USER,
            stage=stage,
        )
        self._require_hardened_container(
            edge,
            expected_user=EXPECTED_EDGE_USER,
            stage=stage,
        )
        if self._port_bindings(postgres, stage=stage) or self._port_bindings(
            web,
            stage=stage,
        ):
            raise RehearsalError("internal_host_port_exposed", stage)
        self._require_edge_loopback_binding(
            edge,
            host_port=self._edge_port,
            stage=stage,
        )

        web_mounts = self._container_mounts(web, stage=stage)
        edge_mounts = self._container_mounts(edge, stage=stage)
        self._require_exact_named_mounts(
            web_mounts,
            expected={
                "/run/secrets": (self.resources.app_secret_volume, False),
            },
            stage=stage,
        )
        self._require_exact_named_mounts(
            edge_mounts,
            expected={
                "/srv/maru/static": (self.resources.static_volume, False),
                "/etc/nginx/conf.d": (self.resources.config_volume, False),
            },
            stage=stage,
        )
        if any("docker.sock" in str(mount.get("Source", "")) for mount in edge_mounts):
            raise RehearsalError("docker_socket_exposed", stage)
        self._require_edge_config_snapshot(stage=stage)

        expected_networks = {
            self.resources.postgres: frozenset({self.resources.backend_network}),
            self.resources.web: frozenset(
                {self.resources.backend_network, self.resources.proxy_network}
            ),
            self.resources.edge: frozenset(
                {self.resources.ingress_network, self.resources.proxy_network}
            ),
        }
        for name, inspection in (
            (self.resources.postgres, postgres),
            (self.resources.web, web),
            (self.resources.edge, edge),
        ):
            if (
                self._container_networks(inspection, stage=stage)
                != expected_networks[name]
            ):
                raise RehearsalError("container_network_boundary_invalid", stage)

        for container, expected_uid in (
            (self.resources.web, "10001"),
            (self.resources.edge, "101"),
        ):
            uid = self._docker("exec", container, "id", "-u", stage=stage)
            if uid.stdout.strip() != expected_uid:
                raise RehearsalError("container_user_invalid", stage)

        for network, expected_internal in (
            (self.resources.backend_network, True),
            (self.resources.proxy_network, True),
            (self.resources.ingress_network, False),
        ):
            result = self._docker(
                "network",
                "inspect",
                "--format",
                "{{json .Internal}}",
                network,
                stage=stage,
            )
            if result.stdout.strip().casefold() != str(expected_internal).casefold():
                raise RehearsalError("network_isolation_invalid", stage)
        self._record(
            stage,
            {
                "application_uid": 10001,
                "edge_uid": 101,
                "application_root_filesystem_read_only": True,
                "edge_root_filesystem_read_only": True,
                "capabilities_dropped": True,
                "no_new_privileges": True,
                "tmpfs_size_bytes": TMPFS_SIZE_BYTES,
                "static_volume_read_only": True,
                "config_snapshot_volume_read_only": True,
                "config_snapshot_digest_verified": True,
                "docker_socket_exposed": False,
                "database_network_internal": True,
                "proxy_network_internal": True,
                "edge_database_network_access": False,
                "database_host_ports": 0,
                "web_host_ports": 0,
                "edge_loopback_host_ports": 1,
            },
        )

    def exercise_restart_boundaries(self) -> None:
        """Prove static independence plus Gunicorn and edge stop/start recovery.

        Raises
        ------
        RehearsalError
            If outage isolation, recovery identity, or artifact integrity differs.
        """
        stage = "exercise_restart_boundaries"
        self._announce(stage)
        self._docker("stop", "--time", "30", self.resources.web, stage=stage)
        self._verify_one_static_asset(
            "/static/core/brand.css",
            stage=stage,
            conditional=False,
        )
        unavailable = self._wait_for_status(
            "/api/v1/meta/build",
            HTTP_BAD_GATEWAY,
            stage=stage,
        )
        if unavailable.status not in HTTP_BAD_GATEWAY:
            raise RehearsalError("dynamic_outage_boundary_invalid", stage)
        self._require_dynamic_cache_separation(unavailable, stage=stage)
        self._docker("start", self.resources.web, stage=stage)
        recovered = self._wait_for_status(
            "/api/v1/meta/build",
            frozenset({HTTP_OK}),
            stage=stage,
        )
        recovered_build = self._json_object(recovered, stage=stage)
        self._require_dynamic_cache_separation(recovered, stage=stage)
        if {
            key: recovered_build.get(key) for key in self._build_identity
        } != self._build_identity:
            raise RehearsalError("build_identity_mismatch", stage)

        self._docker("stop", "--time", "30", self.resources.edge, stage=stage)
        self._wait_until_unreachable(stage=stage)
        self._docker("start", self.resources.edge, stage=stage)
        self._refresh_edge_origin(stage=stage)
        self._require_edge_config_snapshot(stage=stage)
        edge_recovered = self._wait_for_status(
            "/api/v1/meta/build",
            frozenset({HTTP_OK}),
            stage=stage,
        )
        edge_build = self._json_object(edge_recovered, stage=stage)
        self._require_dynamic_cache_separation(edge_recovered, stage=stage)
        if {key: edge_build.get(key) for key in self._build_identity} != (
            self._build_identity
        ):
            raise RehearsalError("build_identity_mismatch", stage)
        self._verify_one_static_asset(
            "/static/core/brand.css",
            stage=stage,
            conditional=False,
        )
        retained_manifest = self._static_manifest_job(
            stage=stage,
            mount_static_volume=True,
        )
        if (
            retained_manifest != self._image_manifest
            or self._static_manifest_digest(retained_manifest) != self._manifest_digest
        ):
            raise RehearsalError("restart_artifact_drift", stage)
        self._record(
            stage,
            {
                "static_available_while_gunicorn_stopped": True,
                "dynamic_unavailable_while_gunicorn_stopped": True,
                "gunicorn_same_build_recovered": True,
                "edge_endpoint_absent_while_stopped": True,
                "edge_same_build_recovered": True,
                "edge_host_ports_observed": len(self._edge_ports_observed),
                "static_manifest_unchanged": True,
                "edge_config_snapshot_unchanged": True,
            },
        )

    def final_delivery_check(self) -> None:
        """Repeat every required static path and exact dynamic build identity.

        Raises
        ------
        RehearsalError
            If final static bytes or dynamic build identity differ.
        """
        stage = "final_delivery_check"
        self._announce(stage)
        required_paths = sorted(
            set(REQUIRED_STATIC_ASSETS)
            | self._landing_references
            | self._manifest_icon_references
            | self._documentation_references
        )
        for path in required_paths:
            self._verify_one_static_asset(path, stage=stage, conditional=False)
        build_result = self._wait_for_status(
            "/api/v1/meta/build",
            frozenset({HTTP_OK}),
            stage=stage,
        )
        build = self._json_object(build_result, stage=stage)
        self._require_dynamic_cache_separation(build_result, stage=stage)
        if {
            key: build.get(key) for key in self._build_identity
        } != self._build_identity:
            raise RehearsalError("build_identity_mismatch", stage)
        self._record(
            stage,
            {
                "required_static_paths_verified": len(required_paths),
                "same_build_identity": True,
                "manifest_sha256": self._manifest_digest,
                "private_artifacts_recorded": False,
            },
        )

    def _resource_labels(
        self,
        resource_type: str,
        name: str,
        *,
        stage: str,
    ) -> dict[str, str] | None:
        """Read labels after an exact-name inventory proves presence or absence.

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
        dict[str, str] | None
            Labels, or ``None`` only when inventory proves absence.

        Raises
        ------
        RehearsalError
            If labels are malformed.
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
            labels = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RehearsalError("resource_labels_invalid", stage) from error
        if labels is None:
            return {}
        if not isinstance(labels, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in labels.items()
        ):
            raise RehearsalError("resource_labels_invalid", stage)
        return labels

    def _require_owned_resource(
        self,
        resource_type: str,
        name: str,
        *,
        stage: str,
    ) -> bool:
        """Require both exact ownership labels for one present resource.

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
            Whether the exact owned resource exists.

        Raises
        ------
        RehearsalError
            If a present resource omits either ownership label.
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

    def _cleanup_container_names(self, *, stage: str) -> list[str]:
        """Return jobs followed by edge, Gunicorn, and PostgreSQL names.

        Parameters
        ----------
        stage : str
            Public retention or cleanup stage.

        Returns
        -------
        list[str]
            Deterministic complete container namespace.
        """
        return list(
            dict.fromkeys(
                (
                    *self._job_container_names(stage=stage),
                    self.resources.edge,
                    self.resources.web,
                    self.resources.postgres,
                )
            )
        )

    def _validate_owned_inventory(
        self,
        *,
        stage: str,
    ) -> tuple[list[str], list[str], list[str]]:
        """Validate the complete exact namespace before retention or cleanup.

        Parameters
        ----------
        stage : str
            Public retention or cleanup stage.

        Returns
        -------
        tuple[list[str], list[str], list[str]]
            Present owned containers, networks, and volumes.

        Raises
        ------
        RehearsalError
            If names, ownership labels, or labeled inventories differ.
        """
        containers = [
            name
            for name in self._cleanup_container_names(stage=stage)
            if self._require_owned_resource("container", name, stage=stage)
        ]
        networks = [
            name
            for name in self.resources.networks
            if self._require_owned_resource("network", name, stage=stage)
        ]
        volumes = [
            name
            for name in self.resources.volumes
            if self._require_owned_resource("volume", name, stage=stage)
        ]
        if (
            self._owned_resource_names("container", stage=stage) != set(containers)
            or self._owned_resource_names("network", stage=stage) != set(networks)
            or self._owned_resource_names("volume", stage=stage) != set(volumes)
        ):
            raise RehearsalError("cleanup_namespace_mismatch", stage)
        return containers, networks, volumes

    def _remove_container(self, name: str, *, stage: str) -> None:
        """Remove one exact container after rechecking both ownership labels.

        Parameters
        ----------
        name : str
            Exact container name.
        stage : str
            Public cleanup stage.
        """
        if self._require_owned_resource("container", name, stage=stage):
            self._docker("rm", "--force", name, stage=stage)

    def cleanup(self, *, require_present: bool = False) -> int:
        """Delete only this exact label-verified synthetic resource namespace.

        Parameters
        ----------
        require_present : bool, default=False
            Whether an empty initial inventory is an operator error.

        Returns
        -------
        int
            Number of exact resources present before deletion.

        Raises
        ------
        RehearsalError
            If ownership is ambiguous or final inventory is not empty.
        """
        stage = "cleanup"
        containers, networks, volumes = self._validate_owned_inventory(stage=stage)
        initial_resource_count = len(containers) + len(networks) + len(volumes)
        if require_present and initial_resource_count == 0:
            raise RehearsalError("retained_run_not_found", stage)
        for container in containers:
            self._remove_container(container, stage=stage)
        for network in networks:
            if self._require_owned_resource("network", network, stage=stage):
                self._docker("network", "rm", network, stage=stage)
        for volume in volumes:
            if self._require_owned_resource("volume", volume, stage=stage):
                self._docker("volume", "rm", volume, stage=stage)

        remaining_names = self._cleanup_container_names(stage=stage)
        if (
            any(
                self._resource_exists("container", name, stage=stage)
                for name in remaining_names
            )
            or any(
                self._resource_exists("network", name, stage=stage)
                for name in self.resources.networks
            )
            or any(
                self._resource_exists("volume", name, stage=stage)
                for name in self.resources.volumes
            )
            or any(
                self._owned_resource_names(resource_type, stage=stage)
                for resource_type in ("container", "network", "volume")
            )
        ):
            raise RehearsalError("cleanup_incomplete", stage)
        return initial_resource_count

    def stop_for_retention(self) -> None:
        """Stop every owned container while retaining an unchanged inventory.

        Raises
        ------
        RehearsalError
            If ownership, retained inventory, or stopped state cannot be proved.
        """
        stage = "retention"
        containers, networks, volumes = self._validate_owned_inventory(stage=stage)
        running_result = self._docker(
            "container",
            "ls",
            "--format",
            "{{.Names}}",
            stage=stage,
        )
        running = {
            line.strip() for line in running_result.stdout.splitlines() if line.strip()
        }
        for container in containers:
            if container not in running:
                continue
            self._require_owned_resource("container", container, stage=stage)
            self._docker("stop", "--time", "30", container, stage=stage)
        retained_containers, retained_networks, retained_volumes = (
            self._validate_owned_inventory(stage=stage)
        )
        if (
            set(retained_containers) != set(containers)
            or set(retained_networks) != set(networks)
            or set(retained_volumes) != set(volumes)
        ):
            raise RehearsalError("retention_inventory_changed", stage)
        remaining_running = self._docker(
            "container",
            "ls",
            "--format",
            "{{.Names}}",
            stage=stage,
        )
        running_names = {
            line.strip()
            for line in remaining_running.stdout.splitlines()
            if line.strip()
        }
        if any(container in running_names for container in retained_containers):
            raise RehearsalError("retention_stop_incomplete", stage)

    def _write_evidence(self) -> None:
        """Write the final sanitized receipt below the ignored local directory.

        Raises
        ------
        RehearsalError
            If receipt sanitization or its resolved path is unsafe.
        """
        if not self._evidence_is_sanitized(self.evidence):
            raise RehearsalError("evidence_not_sanitized", "evidence")
        path = self.configuration.evidence_path.resolve()
        local_root = (REPOSITORY_ROOT / ".local-ci").resolve()
        if local_root not in path.parents:
            raise RehearsalError("evidence_path_invalid", "evidence")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            raise RehearsalError("evidence_write_failed", "evidence") from error

    def execute(self) -> int:  # noqa: PLR0912 - explicit bounded lifecycle branches
        """Run all stages, enforce retention policy, and write safe evidence.

        Returns
        -------
        int
            Zero on complete success, one on bounded failure, and 130 after an
            operator interrupt is cleaned up.
        """
        failure: RehearsalError | None = None
        interrupted = False
        current_stage = "preflight"
        print(f"[synthetic-oci-static] run_id={self.configuration.run_id}")
        try:
            for current_stage in STAGE_ORDER:
                getattr(self, current_stage)()
        except KeyboardInterrupt:
            interrupted = True
            failure = RehearsalError("interrupted", current_stage)
        except RehearsalError as error:
            failure = error
        except Exception:  # noqa: BLE001 - never disclose private exception text
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
        except KeyboardInterrupt:
            interrupted = True
            cleanup_status = "failed"
            if failure is None:
                failure = RehearsalError("interrupted", "cleanup")
        except Exception:  # noqa: BLE001 - never disclose private exception text
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
            print("[synthetic-oci-static] failed (code=evidence_write_failed)")
            return 130 if interrupted else 1
        if failure is not None:
            print(
                "[synthetic-oci-static] failed "
                f"(stage={failure.stage}; code={failure.code}); "
                "raw command output, credentials, cookies, HTML, and schema "
                "were not recorded"
            )
            return 130 if interrupted else 1
        print(
            "[synthetic-oci-static] passed; "
            "evidence="
            f"{self.configuration.evidence_path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()}"
        )
        return 0


def _argument_parser() -> argparse.ArgumentParser:
    """Build the static-delivery evaluator command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser for immutable identities, timing, retention, and cleanup.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-image", default=DEFAULT_APPLICATION_IMAGE)
    parser.add_argument("--expected-source-revision", default=DEFAULT_SOURCE_REVISION)
    parser.add_argument("--edge-image", default=DEFAULT_EDGE_IMAGE)
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
        "--http-timeout-seconds",
        type=int,
        default=DEFAULT_HTTP_TIMEOUT_SECONDS,
    )
    return parser


def configuration_from_arguments(
    arguments: argparse.Namespace,
) -> StaticDeliveryConfiguration:
    """Validate arguments and derive one ignored evidence path.

    Parameters
    ----------
    arguments : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    StaticDeliveryConfiguration
        Immutable validated evaluator inputs.

    Raises
    ------
    ValueError
        If an identity, timeout, or evidence path is unsafe.
    """
    application_image = validate_image_reference(str(arguments.app_image))
    edge_image = validate_image_reference(str(arguments.edge_image))
    source_revision = validate_source_revision(str(arguments.expected_source_revision))
    run_id = validate_run_id(arguments.run_id or secrets.token_hex(6))
    command_timeout = int(arguments.command_timeout_seconds)
    http_timeout = int(arguments.http_timeout_seconds)
    if (
        command_timeout < MINIMUM_COMMAND_TIMEOUT_SECONDS
        or http_timeout < MINIMUM_HTTP_TIMEOUT_SECONDS
    ):
        raise ValueError("timeouts must preserve bounded startup and shutdown windows")
    evidence_path = arguments.evidence or Path(
        ".local-ci",
        "oci-static-delivery",
        f"{run_id}.json",
    )
    resolved = (REPOSITORY_ROOT / evidence_path).resolve()
    local_root = (REPOSITORY_ROOT / ".local-ci").resolve()
    if local_root not in resolved.parents:
        raise ValueError("evidence path must remain below .local-ci")
    return StaticDeliveryConfiguration(
        application_image=application_image,
        source_revision=source_revision,
        edge_image=edge_image,
        run_id=run_id,
        evidence_path=resolved,
        edge_config_path=EDGE_CONFIG_PATH,
        retain_resources=bool(arguments.retain_resources),
        retain_on_failure=bool(arguments.retain_on_failure),
        command_timeout_seconds=command_timeout,
        http_timeout_seconds=http_timeout,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse inputs and run or clean one synthetic static-delivery rehearsal.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Optional argument vector excluding the program name.

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
        cleanup_configuration = StaticDeliveryConfiguration(
            application_image=DEFAULT_APPLICATION_IMAGE,
            source_revision=DEFAULT_SOURCE_REVISION,
            edge_image=DEFAULT_EDGE_IMAGE,
            run_id=run_id,
            evidence_path=(
                REPOSITORY_ROOT / ".local-ci" / "oci-static-delivery" / f"{run_id}.json"
            ),
            edge_config_path=EDGE_CONFIG_PATH,
            retain_resources=False,
            retain_on_failure=False,
        )
        try:
            OciStaticDeliveryRehearsal(cleanup_configuration).cleanup(
                require_present=True
            )
        except RehearsalError as error:
            print(
                "[synthetic-oci-static] retained cleanup refused "
                f"(stage={error.stage}; code={error.code})"
            )
            return 1
        print(
            "[synthetic-oci-static] retained synthetic resources removed "
            f"irreversibly (run_id={run_id})"
        )
        return 0
    try:
        configuration = configuration_from_arguments(arguments)
    except ValueError as error:
        parser.error(str(error))
    return OciStaticDeliveryRehearsal(configuration).execute()


if __name__ == "__main__":
    raise SystemExit(main())
