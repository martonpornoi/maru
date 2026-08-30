"""Verify one immutable Maru release from independent consumer inputs.

The verifier downloads every attached asset into a new directory and checks the
complete source, checksum, manifest, OCI, SBOM, and strict provenance chain. It
does not execute or extract downloaded content and never mutates remote state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, cast
from urllib.parse import quote

if TYPE_CHECKING:
    from collections.abc import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GITHUB_HOST: Final = "github.com"
MINIMUM_GH_VERSION: Final = (2, 96, 0)
RELEASE_API_VERSION: Final = "2026-03-10"
RELEASE_WORKFLOW: Final = ".github/workflows/release.yml"
MAIN_REF: Final = "refs/heads/main"
SLSA_PREDICATE: Final = "https://slsa.dev/provenance/v1"
CHECKSUMS_NAME: Final = "SHA256SUMS"
MANIFEST_NAME: Final = "release-manifest.json"
COMMAND_TIMEOUT_SECONDS: Final = 120
DOWNLOAD_TIMEOUT_SECONDS: Final = 300
SBOM_TIMEOUT_SECONDS: Final = 600
REPOSITORY_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,38})/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z"
)
TAG_PATTERN = re.compile(
    r"v(?P<year>[0-9]{4})\."
    r"(?P<month>0[1-9]|1[0-2])\."
    r"(?P<pull_request>[1-9][0-9]*)"
    r"(?:-rc\.(?P<candidate>[1-9][0-9]*))?\Z"
)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
ASSET_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
CHECKSUM_LINE_PATTERN = re.compile(
    r"(?P<digest>[0-9a-f]{64})  release-assets/"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\Z"
)
GH_VERSION_PATTERN = re.compile(
    r"gh version (?P<major>[0-9]+)\."
    r"(?P<minor>[0-9]+)\."
    r"(?P<patch>[0-9]+)(?:[-+][^ ]+)?"
    r"(?: \([^\r\n()]+\))?\Z"
)
LS_REMOTE_LINE_PATTERN = re.compile(
    r"(?P<sha>[0-9a-f]{40})\t(?P<ref>refs/tags/[^\r\n]+)\Z"
)
GENERATOR_PATTERN = re.compile(
    r"Tool: (?P<tool>syft|buildkit)-v?[0-9]+"
    r"(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?\Z"
)
SPDX_ID_PATTERN = re.compile(r"SPDXRef-[A-Za-z0-9.-]+\Z")

Channel = Literal["candidate", "gold"]


class ConsumerVerificationError(RuntimeError):
    """Report one sanitized fail-closed consumer verification failure."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured output from one explicit-argv subprocess.

    Parameters
    ----------
    returncode : int
        Process exit status.
    stdout : str
        Standard output retained in memory.
    stderr : str
        Standard error retained in memory and never surfaced by the verifier.

    Attributes
    ----------
    returncode : int
        Process exit status.
    stdout : str
        Standard output retained in memory.
    stderr : str
        Standard error retained in memory and never surfaced by the verifier.
    """

    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Run bounded commands without a shell or token-bearing diagnostics."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        timeout_seconds: int = COMMAND_TIMEOUT_SECONDS,
    ) -> CommandResult:
        """Run one command and return its captured output.

        Parameters
        ----------
        arguments : Sequence[str]
            Exact argv vector. Shell interpretation is never enabled.
        stage : str
            Sanitized operation name used in errors.
        timeout_seconds : int, default=COMMAND_TIMEOUT_SECONDS
            Positive process deadline.

        Returns
        -------
        CommandResult
            Completed process result.

        Raises
        ------
        ConsumerVerificationError
            If arguments are unsafe, the command cannot start, times out, or
            exits unsuccessfully.
        """
        if (
            isinstance(arguments, str)
            or not arguments
            or timeout_seconds < 1
            or any(
                not isinstance(argument, str) or not argument for argument in arguments
            )
        ):
            raise ConsumerVerificationError(f"invalid command contract: {stage}")
        try:
            completed = subprocess.run(  # noqa: S603 - explicit argv, no shell
                list(arguments),
                cwd=REPOSITORY_ROOT,
                text=True,
                encoding="utf-8",
                errors="strict",
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ConsumerVerificationError(f"command timed out: {stage}") from error
        except (OSError, UnicodeError) as error:
            raise ConsumerVerificationError(
                f"command unavailable or output is not UTF-8: {stage}"
            ) from error
        result = CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if result.returncode != 0:
            raise ConsumerVerificationError(
                f"command failed: {stage}; exit={result.returncode}"
            )
        return result


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    """Tag-derived release identity that is independent of the manifest.

    Parameters
    ----------
    version : str
        Display CalVer in ``YYYY.MM.PR`` form.
    python_version : str
        PEP 440-compatible version.
    pull_request : int
        Release pull request encoded by the CalVer.
    channel : Channel
        Candidate or gold channel.
    candidate_number : int | None
        Positive candidate sequence, or ``None`` for gold.
    prerelease : bool
        Expected GitHub prerelease state.
    image_tag : str
        Expected mutable OCI tag.
    title : str
        Expected manifest title.

    Attributes
    ----------
    version : str
        Display CalVer in ``YYYY.MM.PR`` form.
    python_version : str
        PEP 440-compatible version.
    pull_request : int
        Release pull request encoded by the CalVer.
    channel : Channel
        Candidate or gold channel.
    candidate_number : int | None
        Positive candidate sequence, or ``None`` for gold.
    prerelease : bool
        Expected GitHub prerelease state.
    image_tag : str
        Expected mutable OCI tag.
    title : str
        Expected manifest title.
    """

    version: str
    python_version: str
    pull_request: int
    channel: Channel
    candidate_number: int | None
    prerelease: bool
    image_tag: str
    title: str


@dataclass(frozen=True, slots=True)
class ConsumerExpectations:
    """Independent inputs for one release-consumer verification.

    Parameters
    ----------
    repository : str
        Lowercase GitHub ``owner/repository`` identity.
    tag : str
        Immutable Maru release tag.
    source_commit : str
        Expected protected-main commit.
    image : str
        Expected mutable GHCR image tag.
    image_digest : str
        Expected immutable OCI digest.
    download_directory : Path
        New directory that will receive all attached assets.
    identity : ReleaseIdentity
        Identity derived only from the supplied tag.

    Attributes
    ----------
    repository : str
        Lowercase GitHub ``owner/repository`` identity.
    tag : str
        Immutable Maru release tag.
    source_commit : str
        Expected protected-main commit.
    image : str
        Expected mutable GHCR image tag.
    image_digest : str
        Expected immutable OCI digest.
    download_directory : Path
        New directory that will receive all attached assets.
    identity : ReleaseIdentity
        Identity derived only from the supplied tag.
    """

    repository: str
    tag: str
    source_commit: str
    image: str
    image_digest: str
    download_directory: Path
    identity: ReleaseIdentity

    @classmethod
    def from_inputs(
        cls,
        *,
        repository: str,
        tag: str,
        source_commit: str,
        image: str,
        image_digest: str,
        download_directory: Path,
    ) -> ConsumerExpectations:
        """Validate independent user inputs and derive release identity.

        Parameters
        ----------
        repository : str
            Lowercase GitHub ``owner/repository`` identity.
        tag : str
            Immutable Maru release tag.
        source_commit : str
            Expected protected-main commit.
        image : str
            Expected mutable GHCR image tag.
        image_digest : str
            Expected immutable OCI digest.
        download_directory : Path
            New directory that will receive every attached asset.

        Returns
        -------
        ConsumerExpectations
            Validated consumer expectations.

        Raises
        ------
        ConsumerVerificationError
            If an identity is malformed or internally inconsistent.
        """
        if REPOSITORY_PATTERN.fullmatch(repository) is None:
            raise ConsumerVerificationError(
                "repository must be a lowercase owner/repository identity"
            )
        tag_match = TAG_PATTERN.fullmatch(tag)
        if tag_match is None:
            raise ConsumerVerificationError(
                "tag must use vYYYY.MM.PR or vYYYY.MM.PR-rc.N"
            )
        if COMMIT_PATTERN.fullmatch(source_commit) is None:
            raise ConsumerVerificationError(
                "source commit must be a lowercase 40-character Git SHA"
            )
        if DIGEST_PATTERN.fullmatch(image_digest) is None:
            raise ConsumerVerificationError(
                "image digest must use lowercase sha256:<64-hex>"
            )

        year = tag_match.group("year")
        month = tag_match.group("month")
        pull_request = int(tag_match.group("pull_request"))
        candidate_text = tag_match.group("candidate")
        candidate_number = int(candidate_text) if candidate_text is not None else None
        version = f"{year}.{month}.{pull_request}"
        python_version = f"{year}.{int(month)}.{pull_request}"
        if candidate_number is None:
            channel: Channel = "gold"
            image_tag = version
            title = f"Maru {version}"
        else:
            channel = "candidate"
            image_tag = f"{version}-rc.{candidate_number}"
            title = f"Maru {version} release candidate {candidate_number}"
        expected_image = f"ghcr.io/{repository}:{image_tag}"
        if image != expected_image:
            raise ConsumerVerificationError(
                f"image must equal the tag-derived reference {expected_image}"
            )
        try:
            absolute_download_directory = download_directory.absolute()
        except OSError as error:
            raise ConsumerVerificationError(
                "download directory could not be normalized"
            ) from error
        if (
            absolute_download_directory.is_symlink()
            or absolute_download_directory.exists()
        ):
            raise ConsumerVerificationError("download directory must not already exist")
        identity = ReleaseIdentity(
            version=version,
            python_version=python_version,
            pull_request=pull_request,
            channel=channel,
            candidate_number=candidate_number,
            prerelease=candidate_number is not None,
            image_tag=image_tag,
            title=title,
        )
        return cls(
            repository=repository,
            tag=tag,
            source_commit=source_commit,
            image=image,
            image_digest=image_digest,
            download_directory=absolute_download_directory,
            identity=identity,
        )

    @property
    def image_name(self) -> str:
        """Return the tag-free GHCR image name.

        Returns
        -------
        str
            Exact ``ghcr.io/owner/repository`` name.
        """
        return f"ghcr.io/{self.repository}"

    @property
    def immutable_image(self) -> str:
        """Return the digest-bound OCI image reference.

        Returns
        -------
        str
            Exact image name plus supplied immutable digest.
        """
        return f"{self.image_name}@{self.image_digest}"

    @property
    def github_repository(self) -> str:
        """Return the host-qualified public GitHub repository identity.

        Returns
        -------
        str
            Exact ``github.com/owner/repository`` identity.
        """
        return f"{GITHUB_HOST}/{self.repository}"

    @property
    def expected_assets(self) -> frozenset[str]:
        """Return the exact release asset contract for this tag.

        Returns
        -------
        frozenset[str]
            Eight expected release-asset basenames.
        """
        return frozenset(
            {
                "LICENSE",
                "THIRD_PARTY_NOTICES.md",
                f"maru-docs-{self.identity.version}.tar.gz",
                "openapi.yaml",
                "pnpm-lock.yaml",
                MANIFEST_NAME,
                CHECKSUMS_NAME,
                "uv.lock",
            }
        )


@dataclass(frozen=True, slots=True)
class VerificationSummary:
    """Sanitized counts from a successful verification.

    Parameters
    ----------
    assets : int
        Number of individually attested assets.
    checksum_payloads : int
        Number of payloads covered by ``SHA256SUMS``.
    sbom_packages : int
        Number of packages in the digest-bound SPDX document.
    sbom_generators : tuple[str, ...]
        Sanitized Syft and BuildKit generator declarations.
    provenance_attestations : int
        Number of exact verified SLSA provenance results.

    Attributes
    ----------
    assets : int
        Number of individually attested assets.
    checksum_payloads : int
        Number of payloads covered by ``SHA256SUMS``.
    sbom_packages : int
        Number of packages in the digest-bound SPDX document.
    sbom_generators : tuple[str, ...]
        Sanitized Syft and BuildKit generator declarations.
    provenance_attestations : int
        Number of exact verified SLSA provenance results.
    """

    assets: int
    checksum_payloads: int
    sbom_packages: int
    sbom_generators: tuple[str, ...]
    provenance_attestations: int


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build one JSON object while rejecting duplicate keys.

    Parameters
    ----------
    pairs : list[tuple[str, object]]
        Parsed key-value pairs.

    Returns
    -------
    dict[str, object]
        Unique-key JSON object.

    Raises
    ------
    ConsumerVerificationError
        If a key appears more than once.
    """
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConsumerVerificationError("JSON contains a duplicate key")
        result[key] = value
    return result


def _strict_json_loads(text: str, *, stage: str) -> object:
    """Parse JSON with duplicate-key rejection and a sanitized error.

    Parameters
    ----------
    text : str
        JSON document.
    stage : str
        Sanitized document identity.

    Returns
    -------
    object
        Parsed JSON value.

    Raises
    ------
    ConsumerVerificationError
        If the document is empty, malformed, or has duplicate keys.
    """
    if not text.strip():
        raise ConsumerVerificationError(f"empty JSON document: {stage}")
    try:
        parsed: object = json.loads(text, object_pairs_hook=_unique_json_object)
    except json.JSONDecodeError as error:
        raise ConsumerVerificationError(f"malformed JSON document: {stage}") from error
    return parsed


def _require_object(value: object, *, stage: str) -> dict[str, object]:
    """Require a JSON object.

    Parameters
    ----------
    value : object
        Parsed value.
    stage : str
        Sanitized field identity.

    Returns
    -------
    dict[str, object]
        Validated object.

    Raises
    ------
    ConsumerVerificationError
        If the value is not an object with string keys.
    """
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ConsumerVerificationError(f"expected JSON object: {stage}")
    return cast("dict[str, object]", value)


def _require_list(value: object, *, stage: str) -> list[object]:
    """Require a JSON array.

    Parameters
    ----------
    value : object
        Parsed value.
    stage : str
        Sanitized field identity.

    Returns
    -------
    list[object]
        Validated array.

    Raises
    ------
    ConsumerVerificationError
        If the value is not an array.
    """
    if not isinstance(value, list):
        raise ConsumerVerificationError(f"expected JSON array: {stage}")
    return cast("list[object]", value)


def _require_string(value: object, *, stage: str) -> str:
    """Require a non-empty printable JSON string.

    Parameters
    ----------
    value : object
        Parsed value.
    stage : str
        Sanitized field identity.

    Returns
    -------
    str
        Validated string.

    Raises
    ------
    ConsumerVerificationError
        If the value is empty, non-string, or contains control characters.
    """
    if not isinstance(value, str) or not value or not value.isprintable():
        raise ConsumerVerificationError(f"expected printable string: {stage}")
    return value


def _require_exact(
    payload: dict[str, object],
    field: str,
    expected: object,
    *,
    stage: str,
) -> None:
    """Require one exact JSON value and exact JSON scalar type.

    Parameters
    ----------
    payload : dict[str, object]
        JSON object to inspect.
    field : str
        Field name.
    expected : object
        Independently expected value.
    stage : str
        Sanitized object identity.

    Raises
    ------
    ConsumerVerificationError
        If the field is missing, differs, or uses a different scalar type.
    """
    observed = payload.get(field)
    if type(observed) is not type(expected) or observed != expected:
        raise ConsumerVerificationError(f"{stage} field differs: {field}")


def _require_aware_datetime(value: object, *, stage: str) -> datetime:
    """Require one printable, timezone-aware ISO 8601 timestamp.

    Parameters
    ----------
    value : object
        JSON value to parse.
    stage : str
        Sanitized timestamp identity.

    Returns
    -------
    datetime
        Parsed timezone-aware instant.

    Raises
    ------
    ConsumerVerificationError
        If the value is not a printable ISO 8601 timestamp with an offset.
    """
    timestamp = _require_string(value, stage=stage)
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as error:
        raise ConsumerVerificationError(
            f"invalid ISO 8601 timestamp: {stage}"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConsumerVerificationError(f"timezone is missing: {stage}")
    return parsed


def _verify_prerequisites(runner: CommandRunner) -> None:
    """Verify supported local capabilities and safe GitHub authentication.

    Parameters
    ----------
    runner : CommandRunner
        Explicit-argv command runner.

    Raises
    ------
    ConsumerVerificationError
        If a required tool, GitHub CLI version, or active authentication is
        unavailable.
    """
    version_output = runner.run(("gh", "--version"), stage="GitHub CLI version")
    first_line = version_output.stdout.splitlines()[0] if version_output.stdout else ""
    version_match = GH_VERSION_PATTERN.fullmatch(first_line)
    if version_match is None:
        raise ConsumerVerificationError("GitHub CLI version could not be parsed")
    version = tuple(
        int(version_match.group(name)) for name in ("major", "minor", "patch")
    )
    if version < MINIMUM_GH_VERSION:
        minimum = ".".join(str(part) for part in MINIMUM_GH_VERSION)
        raise ConsumerVerificationError(f"GitHub CLI {minimum} or later is required")
    runner.run(
        ("gh", "auth", "status", "--active", "--hostname", GITHUB_HOST),
        stage="safe GitHub authentication",
    )
    runner.run(("git", "--version"), stage="Git capability")
    runner.run(
        ("docker", "buildx", "imagetools", "inspect", "--help"),
        stage="Docker Buildx imagetools capability",
    )


def _release_api_payload(
    expectations: ConsumerExpectations,
    runner: CommandRunner,
) -> dict[str, object]:
    """Fetch and parse the authenticated release-by-tag response.

    Parameters
    ----------
    expectations : ConsumerExpectations
        Independent release inputs.
    runner : CommandRunner
        Explicit-argv command runner.

    Returns
    -------
    dict[str, object]
        Parsed GitHub release object.
    """
    endpoint = (
        f"repos/{expectations.repository}/releases/tags/"
        f"{quote(expectations.tag, safe='')}"
    )
    result = runner.run(
        (
            "gh",
            "api",
            "--hostname",
            GITHUB_HOST,
            "--method",
            "GET",
            endpoint,
            "--header",
            f"X-GitHub-Api-Version: {RELEASE_API_VERSION}",
        ),
        stage="immutable release API read",
    )
    return _require_object(
        _strict_json_loads(result.stdout, stage="release API response"),
        stage="release API response",
    )


def _pull_request_payload(
    expectations: ConsumerExpectations,
    runner: CommandRunner,
) -> dict[str, object]:
    """Fetch the authenticated release pull request from public GitHub.

    Parameters
    ----------
    expectations : ConsumerExpectations
        Tag-derived release pull-request identity.
    runner : CommandRunner
        Explicit-argv command runner.

    Returns
    -------
    dict[str, object]
        Parsed GitHub pull-request object.
    """
    result = runner.run(
        (
            "gh",
            "pr",
            "view",
            str(expectations.identity.pull_request),
            "--repo",
            expectations.github_repository,
            "--json",
            "number,state,mergedAt,mergeCommit,baseRefName,url",
        ),
        stage="release pull-request read",
    )
    return _require_object(
        _strict_json_loads(result.stdout, stage="pull-request response"),
        stage="pull-request response",
    )


def _safe_asset_name(value: object) -> str:
    """Require one simple release-asset basename.

    Parameters
    ----------
    value : object
        GitHub asset name.

    Returns
    -------
    str
        Safe basename.

    Raises
    ------
    ConsumerVerificationError
        If the name could traverse, nest, or contain control characters.
    """
    name = _require_string(value, stage="release asset name")
    if ASSET_NAME_PATTERN.fullmatch(name) is None or Path(name).name != name:
        raise ConsumerVerificationError("release asset name is not a safe basename")
    return name


def _remote_asset_inventory(assets: object) -> dict[str, str]:
    """Validate GitHub's uploaded asset inventory.

    Parameters
    ----------
    assets : object
        Parsed release ``assets`` value.

    Returns
    -------
    dict[str, str]
        Asset names mapped to GitHub-reported SHA-256 digests.

    Raises
    ------
    ConsumerVerificationError
        If an asset is malformed, duplicated, empty, or not uploaded.
    """
    inventory: dict[str, str] = {}
    for raw_asset in _require_list(assets, stage="release assets"):
        asset = _require_object(raw_asset, stage="release asset")
        name = _safe_asset_name(asset.get("name"))
        if name in inventory:
            raise ConsumerVerificationError("release contains duplicate asset names")
        _require_exact(asset, "state", "uploaded", stage=f"release asset {name}")
        size = asset.get("size")
        if type(size) is not int or size < 1:
            raise ConsumerVerificationError(f"release asset is empty: {name}")
        digest = _require_string(asset.get("digest"), stage=f"asset digest {name}")
        if DIGEST_PATTERN.fullmatch(digest) is None:
            raise ConsumerVerificationError(f"release asset digest is invalid: {name}")
        inventory[name] = digest
    return inventory


def _verify_release_payload(
    payload: dict[str, object],
    expectations: ConsumerExpectations,
) -> dict[str, str]:
    """Require immutable release state and the exact remote asset contract.

    Parameters
    ----------
    payload : dict[str, object]
        Parsed GitHub release response.
    expectations : ConsumerExpectations
        Independent release inputs.

    Returns
    -------
    dict[str, str]
        Exact remote asset digest inventory.

    Raises
    ------
    ConsumerVerificationError
        If release identity, state, or assets differ.
    """
    _require_exact(payload, "tag_name", expectations.tag, stage="release")
    _require_exact(
        payload,
        "target_commitish",
        expectations.source_commit,
        stage="release",
    )
    _require_exact(payload, "draft", expected=False, stage="release")
    _require_exact(payload, "immutable", expected=True, stage="release")
    _require_exact(
        payload,
        "prerelease",
        expectations.identity.prerelease,
        stage="release",
    )
    inventory = _remote_asset_inventory(payload.get("assets"))
    if inventory.keys() != expectations.expected_assets:
        missing = sorted(expectations.expected_assets - inventory.keys())
        extra = sorted(inventory.keys() - expectations.expected_assets)
        raise ConsumerVerificationError(
            f"release asset set differs: missing={missing!r}; extra={extra!r}"
        )
    return inventory


def _verify_nonempty_json_result(text: str, *, stage: str) -> None:
    """Require a non-empty JSON object or array from a verification command.

    Parameters
    ----------
    text : str
        Command output.
    stage : str
        Sanitized verification identity.

    Raises
    ------
    ConsumerVerificationError
        If the result is malformed or empty.
    """
    parsed = _strict_json_loads(text, stage=stage)
    if not isinstance(parsed, (dict, list)) or not parsed:
        raise ConsumerVerificationError(f"empty verification result: {stage}")


def _is_link_or_reparse(path: Path) -> bool:
    """Return whether an existing path is a symlink, junction, or reparse point.

    Parameters
    ----------
    path : Path
        Existing path to inspect without resolving it.

    Returns
    -------
    bool
        Whether the path can redirect filesystem access.

    Raises
    ------
    ConsumerVerificationError
        If path metadata cannot be inspected.
    """
    try:
        metadata = path.lstat()
        junction_probe = getattr(path, "is_junction", None)
        is_junction = bool(junction_probe()) if junction_probe is not None else False
    except OSError as error:
        raise ConsumerVerificationError(
            "download path metadata could not be inspected"
        ) from error
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or is_junction or bool(file_attributes & reparse_flag)


def _reject_linked_download_path(directory: Path, *, include_directory: bool) -> None:
    """Reject redirecting components in an isolated download path.

    Parameters
    ----------
    directory : Path
        Absolute download directory.
    include_directory : bool
        Whether the newly created directory itself must also be inspected.

    Raises
    ------
    ConsumerVerificationError
        If an existing component is a symlink, junction, or reparse point.
    """
    paths = directory.parents
    if include_directory:
        paths = (directory, *paths)
    for path in paths:
        if path.is_symlink() or (path.exists() and _is_link_or_reparse(path)):
            raise ConsumerVerificationError(
                "download directory cannot use a link or reparse point"
            )


def _create_download_directory(directory: Path) -> None:
    """Create one new directory without following redirecting path entries.

    Parameters
    ----------
    directory : Path
        User-selected output directory.

    Raises
    ------
    ConsumerVerificationError
        If the path or an existing ancestor redirects access, already exists,
        or cannot be created.
    """
    if directory.is_symlink() or directory.exists():
        raise ConsumerVerificationError("download directory must not already exist")
    _reject_linked_download_path(directory, include_directory=False)
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise ConsumerVerificationError(
            "download directory could not be created"
        ) from error
    _reject_linked_download_path(directory, include_directory=True)
    try:
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise ConsumerVerificationError(
                "download directory is not a direct directory"
            )
    except OSError as error:
        raise ConsumerVerificationError(
            "download directory could not be inspected"
        ) from error


def _sha256(path: Path) -> str:
    """Calculate a file's lowercase SHA-256 digest.

    Parameters
    ----------
    path : Path
        File to hash.

    Returns
    -------
    str
        Lowercase hexadecimal digest.

    Raises
    ------
    ConsumerVerificationError
        If the file cannot be read.
    """
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise ConsumerVerificationError(
            f"asset could not be read: {path.name}"
        ) from error
    return digest.hexdigest()


def _downloaded_asset_inventory(
    directory: Path,
    expected_assets: frozenset[str],
) -> dict[str, str]:
    """Require exact direct regular files and calculate their digests.

    Parameters
    ----------
    directory : Path
        Isolated download directory.
    expected_assets : frozenset[str]
        Exact expected asset basenames.

    Returns
    -------
    dict[str, str]
        Asset names mapped to GitHub-style SHA-256 digests.

    Raises
    ------
    ConsumerVerificationError
        If a nested, linked, reparse, missing, or extra entry is present.
    """
    inventory: dict[str, str] = {}
    try:
        entries = tuple(directory.iterdir())
    except OSError as error:
        raise ConsumerVerificationError(
            "download directory could not be inspected"
        ) from error
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for path in entries:
        try:
            metadata = path.lstat()
        except OSError as error:
            raise ConsumerVerificationError(
                f"downloaded entry could not be inspected: {path.name}"
            ) from error
        file_attributes = getattr(metadata, "st_file_attributes", 0)
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or bool(file_attributes & reparse_flag)
        ):
            raise ConsumerVerificationError(
                f"downloaded entry is not a direct regular file: {path.name}"
            )
        name = _safe_asset_name(path.name)
        if name in inventory:
            raise ConsumerVerificationError("download contains duplicate asset names")
        inventory[name] = f"sha256:{_sha256(path)}"
    if inventory.keys() != expected_assets:
        missing = sorted(expected_assets - inventory.keys())
        extra = sorted(inventory.keys() - expected_assets)
        raise ConsumerVerificationError(
            f"downloaded asset set differs: missing={missing!r}; extra={extra!r}"
        )
    return inventory


def _parse_checksum_inventory(text: str) -> dict[str, str]:
    """Parse the exact Linux ``sha256sum`` inventory published by Maru.

    Parameters
    ----------
    text : str
        Complete ``SHA256SUMS`` content.

    Returns
    -------
    dict[str, str]
        Safe payload basenames mapped to lowercase hexadecimal digests.

    Raises
    ------
    ConsumerVerificationError
        If a line, path, digest, or basename is malformed or duplicated.
    """
    lines = text.splitlines()
    if not lines:
        raise ConsumerVerificationError("SHA256SUMS is empty")
    inventory: dict[str, str] = {}
    for line in lines:
        match = CHECKSUM_LINE_PATTERN.fullmatch(line)
        if match is None:
            raise ConsumerVerificationError("SHA256SUMS contains a malformed line")
        name = _safe_asset_name(match.group("name"))
        if name == CHECKSUMS_NAME or name in inventory:
            raise ConsumerVerificationError(
                "SHA256SUMS contains a self-reference or duplicate"
            )
        inventory[name] = match.group("digest")
    return inventory


def _verify_checksums(
    directory: Path,
    expected_assets: frozenset[str],
) -> dict[str, str]:
    """Require exact checksum coverage and matching payload bytes.

    Parameters
    ----------
    directory : Path
        Isolated download directory.
    expected_assets : frozenset[str]
        Exact eight-asset contract.

    Returns
    -------
    dict[str, str]
        Seven payload basenames mapped to hexadecimal digests.

    Raises
    ------
    ConsumerVerificationError
        If coverage or a payload digest differs.
    """
    try:
        text = (directory / CHECKSUMS_NAME).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ConsumerVerificationError(
            "SHA256SUMS could not be read as UTF-8"
        ) from error
    inventory = _parse_checksum_inventory(text)
    expected_payloads = expected_assets - {CHECKSUMS_NAME}
    if inventory.keys() != expected_payloads:
        missing = sorted(expected_payloads - inventory.keys())
        extra = sorted(inventory.keys() - expected_payloads)
        raise ConsumerVerificationError(
            f"checksum payload set differs: missing={missing!r}; extra={extra!r}"
        )
    for name, expected_digest in inventory.items():
        if _sha256(directory / name) != expected_digest:
            raise ConsumerVerificationError(f"checksum differs for payload: {name}")
    return inventory


def _verify_manifest(
    text: str,
    expectations: ConsumerExpectations,
) -> datetime:
    """Require the attested manifest to match every independent identity.

    Parameters
    ----------
    text : str
        Complete manifest JSON.
    expectations : ConsumerExpectations
        Independent release inputs and tag-derived identity.

    Raises
    ------
    ConsumerVerificationError
        If schema, exact types, identities, or merge timing differ.

    Returns
    -------
    datetime
        Timezone-aware merge instant recorded by the manifest.
    """
    manifest = _require_object(
        _strict_json_loads(text, stage="release manifest"),
        stage="release manifest",
    )
    expected_keys = {
        "application_license",
        "candidate_number",
        "channel",
        "commit",
        "image",
        "image_digest",
        "image_tag",
        "merged_at",
        "pull_request",
        "python_version",
        "tag",
        "title",
        "version",
    }
    if manifest.keys() != expected_keys:
        raise ConsumerVerificationError("release manifest schema differs")
    identity = expectations.identity
    expected_fields: dict[str, object] = {
        "application_license": {
            "expression": "Apache-2.0 AND MIT",
            "files": ["LICENSE", "THIRD_PARTY_NOTICES.md"],
            "scope": "Maru source and bundled Staff Console runtime",
        },
        "candidate_number": identity.candidate_number,
        "channel": identity.channel,
        "commit": expectations.source_commit,
        "image": expectations.image,
        "image_digest": expectations.image_digest,
        "image_tag": identity.image_tag,
        "pull_request": identity.pull_request,
        "python_version": identity.python_version,
        "tag": expectations.tag,
        "title": identity.title,
        "version": identity.version,
    }
    for field, expected in expected_fields.items():
        _require_exact(manifest, field, expected, stage="release manifest")
    merged = _require_aware_datetime(
        manifest.get("merged_at"),
        stage="manifest merged_at",
    )
    merged_utc = merged.astimezone(UTC)
    year_text, month_text, _ = identity.version.split(".")
    if merged_utc.year != int(year_text) or merged_utc.month != int(month_text):
        raise ConsumerVerificationError("manifest merged_at differs from CalVer month")
    return merged


def _verify_pull_request(
    payload: dict[str, object],
    expectations: ConsumerExpectations,
    manifest_merged_at: datetime,
) -> None:
    """Reconcile the actual merged release PR with source and manifest evidence.

    Parameters
    ----------
    payload : dict[str, object]
        Host-pinned ``gh pr view`` response.
    expectations : ConsumerExpectations
        Tag-derived PR number and independent source identity.
    manifest_merged_at : datetime
        Merge instant parsed from the release manifest.

    Raises
    ------
    ConsumerVerificationError
        If the PR is missing, unmerged, based elsewhere, or disagrees with the
        expected source, repository, number, or manifest merge instant.
    """
    expected_keys = {
        "baseRefName",
        "mergeCommit",
        "mergedAt",
        "number",
        "state",
        "url",
    }
    if payload.keys() != expected_keys:
        raise ConsumerVerificationError("release pull-request schema differs")
    identity = expectations.identity
    _require_exact(payload, "number", identity.pull_request, stage="release PR")
    _require_exact(payload, "state", "MERGED", stage="release PR")
    _require_exact(payload, "baseRefName", "main", stage="release PR")
    _require_exact(
        payload,
        "url",
        (
            f"https://{GITHUB_HOST}/{expectations.repository}/pull/"
            f"{identity.pull_request}"
        ),
        stage="release PR",
    )
    merge_commit = _require_object(
        payload.get("mergeCommit"),
        stage="release PR merge commit",
    )
    if merge_commit.keys() != {"oid"}:
        raise ConsumerVerificationError("release PR merge-commit schema differs")
    _require_exact(
        merge_commit,
        "oid",
        expectations.source_commit,
        stage="release PR merge commit",
    )
    merged_at = _require_aware_datetime(
        payload.get("mergedAt"),
        stage="release PR mergedAt",
    )
    merged_at_utc = merged_at.astimezone(UTC)
    year_text, month_text, _ = identity.version.split(".")
    if merged_at_utc.year != int(year_text) or merged_at_utc.month != int(month_text):
        raise ConsumerVerificationError("release PR mergedAt differs from CalVer month")
    if merged_at != manifest_merged_at:
        raise ConsumerVerificationError(
            "release PR merge instant differs from the manifest"
        )


def _verify_tag_source(
    expectations: ConsumerExpectations,
    runner: CommandRunner,
) -> None:
    """Independently resolve the public Git tag to exact source.

    Parameters
    ----------
    expectations : ConsumerExpectations
        Independent release inputs.
    runner : CommandRunner
        Explicit-argv command runner.

    Raises
    ------
    ConsumerVerificationError
        If the lightweight or peeled annotated tag differs from source.
    """
    direct_ref = f"refs/tags/{expectations.tag}"
    peeled_ref = f"{direct_ref}^{{}}"
    result = runner.run(
        (
            "git",
            "ls-remote",
            "--exit-code",
            f"https://github.com/{expectations.repository}.git",
            direct_ref,
            peeled_ref,
        ),
        stage="public tag-to-source resolution",
    )
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = LS_REMOTE_LINE_PATTERN.fullmatch(line)
        if match is None:
            raise ConsumerVerificationError("Git tag resolution output is malformed")
        ref = match.group("ref")
        if ref not in {direct_ref, peeled_ref} or ref in refs:
            raise ConsumerVerificationError(
                "Git tag resolution returned unexpected refs"
            )
        refs[ref] = match.group("sha")
    if direct_ref not in refs:
        raise ConsumerVerificationError("Git tag is missing")
    resolved_source = refs.get(peeled_ref, refs[direct_ref])
    if resolved_source != expectations.source_commit:
        raise ConsumerVerificationError("Git tag does not resolve to expected source")


def _parse_image_manifest_digest(text: str, *, stage: str) -> str:
    """Extract one valid digest from Buildx manifest JSON.

    Parameters
    ----------
    text : str
        ``docker buildx imagetools inspect`` JSON output.
    stage : str
        Sanitized image identity.

    Returns
    -------
    str
        GitHub-style SHA-256 digest.

    Raises
    ------
    ConsumerVerificationError
        If the manifest or digest is malformed.
    """
    manifest = _require_object(
        _strict_json_loads(text, stage=stage),
        stage=stage,
    )
    digest = _require_string(manifest.get("digest"), stage=f"{stage} digest")
    if DIGEST_PATTERN.fullmatch(digest) is None:
        raise ConsumerVerificationError(f"invalid image digest: {stage}")
    return digest


def _verify_image_identity(
    expectations: ConsumerExpectations,
    runner: CommandRunner,
) -> None:
    """Prove mutable tag and digest-bound image resolve identically.

    Parameters
    ----------
    expectations : ConsumerExpectations
        Independent image tag and digest.
    runner : CommandRunner
        Explicit-argv command runner.

    Raises
    ------
    ConsumerVerificationError
        If either OCI lookup differs from the supplied digest.
    """
    for reference, stage in (
        (expectations.image, "mutable image tag"),
        (expectations.immutable_image, "immutable image digest"),
    ):
        result = runner.run(
            (
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                reference,
                "--format",
                "{{json .Manifest}}",
            ),
            stage=f"{stage} inspection",
        )
        if _parse_image_manifest_digest(result.stdout, stage=stage) != (
            expectations.image_digest
        ):
            raise ConsumerVerificationError(f"{stage} resolves to another digest")


def _inspect_spdx(
    expectations: ConsumerExpectations,
    runner: CommandRunner,
) -> tuple[int, tuple[str, ...]]:
    """Inspect digest-bound SPDX 2.3 content and generator declarations.

    Parameters
    ----------
    expectations : ConsumerExpectations
        Immutable image identity.
    runner : CommandRunner
        Explicit-argv command runner.

    Returns
    -------
    tuple[int, tuple[str, ...]]
        Package count and sanitized tool-generator strings.

    Raises
    ------
    ConsumerVerificationError
        If SPDX identity, packages, or Syft/BuildKit generators are absent.
    """
    result = runner.run(
        (
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            expectations.immutable_image,
            "--format",
            "{{json .SBOM.SPDX}}",
        ),
        stage="digest-bound SPDX inspection",
        timeout_seconds=SBOM_TIMEOUT_SECONDS,
    )
    spdx = _require_object(
        _strict_json_loads(result.stdout, stage="SPDX document"),
        stage="SPDX document",
    )
    _require_exact(spdx, "spdxVersion", "SPDX-2.3", stage="SPDX document")
    _require_exact(spdx, "SPDXID", "SPDXRef-DOCUMENT", stage="SPDX document")
    packages = _require_list(spdx.get("packages"), stage="SPDX packages")
    if not packages:
        raise ConsumerVerificationError("SPDX packages are empty or malformed")
    package_ids: set[str] = set()
    for raw_package in packages:
        package = _require_object(raw_package, stage="SPDX package")
        _require_string(package.get("name"), stage="SPDX package name")
        package_id = _require_string(
            package.get("SPDXID"),
            stage="SPDX package identifier",
        )
        if (
            SPDX_ID_PATTERN.fullmatch(package_id) is None
            or package_id == "SPDXRef-DOCUMENT"
            or package_id in package_ids
        ):
            raise ConsumerVerificationError(
                "SPDX package identifier is invalid or duplicated"
            )
        package_ids.add(package_id)
    creation_info = _require_object(
        spdx.get("creationInfo"),
        stage="SPDX creationInfo",
    )
    creators = tuple(
        _require_string(creator, stage="SPDX creator")
        for creator in _require_list(
            creation_info.get("creators"),
            stage="SPDX creators",
        )
    )
    generators = tuple(
        creator for creator in creators if GENERATOR_PATTERN.fullmatch(creator)
    )
    if not any(generator.startswith("Tool: syft-") for generator in generators):
        raise ConsumerVerificationError("SPDX Syft generator is missing")
    if not any(generator.startswith("Tool: buildkit-") for generator in generators):
        raise ConsumerVerificationError("SPDX BuildKit generator is missing")
    return len(packages), generators


def _verify_one_provenance(
    raw_result: object,
    expectations: ConsumerExpectations,
) -> None:
    """Require exact certificate and statement fields in one verified result.

    Parameters
    ----------
    raw_result : object
        One ``gh attestation verify`` result.
    expectations : ConsumerExpectations
        Independent source and image identities.

    Raises
    ------
    ConsumerVerificationError
        If certificate, runner, subject, or predicate evidence differs.
    """
    result = _require_object(raw_result, stage="provenance result")
    verification = _require_object(
        result.get("verificationResult"),
        stage="provenance verificationResult",
    )
    signature = _require_object(
        verification.get("signature"),
        stage="provenance signature",
    )
    certificate = _require_object(
        signature.get("certificate"),
        stage="provenance certificate",
    )
    expected_certificate: dict[str, object] = {
        "subjectAlternativeName": (
            f"https://github.com/{expectations.repository}/{RELEASE_WORKFLOW}"
            f"@{MAIN_REF}"
        ),
        "githubWorkflowRepository": expectations.repository,
        "githubWorkflowRef": MAIN_REF,
        "githubWorkflowSHA": expectations.source_commit,
        "runnerEnvironment": "github-hosted",
        "sourceRepositoryURI": f"https://github.com/{expectations.repository}",
        "sourceRepositoryDigest": expectations.source_commit,
        "sourceRepositoryRef": MAIN_REF,
    }
    for field, expected in expected_certificate.items():
        _require_exact(certificate, field, expected, stage="provenance certificate")
    verified_identity = _require_object(
        verification.get("verifiedIdentity"),
        stage="verified provenance identity",
    )
    _require_exact(
        verified_identity,
        "runnerEnvironment",
        "github-hosted",
        stage="verified provenance identity",
    )
    timestamps = _require_list(
        verification.get("verifiedTimestamps"),
        stage="verified provenance timestamps",
    )
    if not timestamps:
        raise ConsumerVerificationError("verified provenance timestamp is missing")
    statement = _require_object(
        verification.get("statement"),
        stage="provenance statement",
    )
    _require_exact(
        statement,
        "predicateType",
        SLSA_PREDICATE,
        stage="provenance statement",
    )
    subjects = _require_list(statement.get("subject"), stage="provenance subjects")
    if len(subjects) != 1:
        raise ConsumerVerificationError("provenance subject set differs")
    subject = _require_object(subjects[0], stage="provenance subject")
    _require_exact(subject, "name", expectations.image_name, stage="provenance subject")
    digest = _require_object(subject.get("digest"), stage="provenance subject digest")
    _require_exact(
        digest,
        "sha256",
        expectations.image_digest.removeprefix("sha256:"),
        stage="provenance subject digest",
    )


def _verify_provenance(
    expectations: ConsumerExpectations,
    runner: CommandRunner,
) -> int:
    """Verify digest-bound, exact-workflow, hosted-runner SLSA provenance.

    Parameters
    ----------
    expectations : ConsumerExpectations
        Independent source and image identities.
    runner : CommandRunner
        Explicit-argv command runner.

    Returns
    -------
    int
        Number of exact verified provenance results.

    Raises
    ------
    ConsumerVerificationError
        If the command or any returned result differs from the strict policy.
    """
    result = runner.run(
        (
            "gh",
            "attestation",
            "verify",
            f"oci://{expectations.immutable_image}",
            "--repo",
            expectations.repository,
            "--hostname",
            GITHUB_HOST,
            "--signer-workflow",
            f"{expectations.github_repository}/{RELEASE_WORKFLOW}",
            "--source-ref",
            MAIN_REF,
            "--source-digest",
            expectations.source_commit,
            "--predicate-type",
            SLSA_PREDICATE,
            "--deny-self-hosted-runners",
            "--format",
            "json",
        ),
        stage="strict digest-bound provenance verification",
    )
    results = _require_list(
        _strict_json_loads(result.stdout, stage="provenance results"),
        stage="provenance results",
    )
    if not results:
        raise ConsumerVerificationError("no exact provenance result was verified")
    for raw_result in results:
        _verify_one_provenance(raw_result, expectations)
    return len(results)


def verify_release_consumer(
    expectations: ConsumerExpectations,
    *,
    runner: CommandRunner | None = None,
) -> VerificationSummary:
    """Verify the complete immutable release-consumer evidence chain.

    Parameters
    ----------
    expectations : ConsumerExpectations
        Independent release, source, and image identities.
    runner : CommandRunner | None, default=None
        Optional explicit-argv runner for tests.

    Returns
    -------
    VerificationSummary
        Sanitized evidence counts after every check passes.

    Raises
    ------
    ConsumerVerificationError
        If any prerequisite, identity, byte, relationship, or attestation
        differs. Partial local downloads are preserved for inspection.
    """
    active_runner = runner or CommandRunner()
    _verify_prerequisites(active_runner)
    initial_release = _release_api_payload(expectations, active_runner)
    remote_digests = _verify_release_payload(initial_release, expectations)
    release_attestation = active_runner.run(
        (
            "gh",
            "release",
            "verify",
            expectations.tag,
            "--repo",
            expectations.github_repository,
            "--format",
            "json",
        ),
        stage="immutable release attestation",
    )
    _verify_nonempty_json_result(
        release_attestation.stdout,
        stage="release attestation",
    )

    _create_download_directory(expectations.download_directory)
    active_runner.run(
        (
            "gh",
            "release",
            "download",
            expectations.tag,
            "--repo",
            expectations.github_repository,
            "--dir",
            str(expectations.download_directory),
        ),
        stage="complete release asset download",
        timeout_seconds=DOWNLOAD_TIMEOUT_SECONDS,
    )
    local_digests = _downloaded_asset_inventory(
        expectations.download_directory,
        expectations.expected_assets,
    )
    if local_digests != remote_digests:
        raise ConsumerVerificationError(
            "downloaded asset digests differ from immutable release records"
        )

    verification_order = (
        CHECKSUMS_NAME,
        *sorted(expectations.expected_assets - {CHECKSUMS_NAME}),
    )
    for asset_name in verification_order:
        asset_attestation = active_runner.run(
            (
                "gh",
                "release",
                "verify-asset",
                expectations.tag,
                str(expectations.download_directory / asset_name),
                "--repo",
                expectations.github_repository,
                "--format",
                "json",
            ),
            stage=f"release asset attestation: {asset_name}",
        )
        _verify_nonempty_json_result(
            asset_attestation.stdout,
            stage=f"release asset attestation: {asset_name}",
        )

    checksum_inventory = _verify_checksums(
        expectations.download_directory,
        expectations.expected_assets,
    )
    try:
        manifest_text = (expectations.download_directory / MANIFEST_NAME).read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError) as error:
        raise ConsumerVerificationError(
            "release manifest could not be read as UTF-8"
        ) from error
    manifest_merged_at = _verify_manifest(manifest_text, expectations)
    pull_request = _pull_request_payload(expectations, active_runner)
    _verify_pull_request(pull_request, expectations, manifest_merged_at)

    _verify_tag_source(expectations, active_runner)
    _verify_image_identity(expectations, active_runner)
    package_count, generators = _inspect_spdx(expectations, active_runner)
    provenance_count = _verify_provenance(expectations, active_runner)
    _verify_image_identity(expectations, active_runner)
    final_release = _release_api_payload(expectations, active_runner)
    if _verify_release_payload(final_release, expectations) != remote_digests:
        raise ConsumerVerificationError("immutable release changed during verification")
    final_local_digests = _downloaded_asset_inventory(
        expectations.download_directory,
        expectations.expected_assets,
    )
    if final_local_digests != local_digests or final_local_digests != remote_digests:
        raise ConsumerVerificationError("downloaded assets changed during verification")
    return VerificationSummary(
        assets=len(final_local_digests),
        checksum_payloads=len(checksum_inventory),
        sbom_packages=package_count,
        sbom_generators=generators,
        provenance_attestations=provenance_count,
    )


def _argument_parser() -> argparse.ArgumentParser:
    """Build the release-consumer command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser requiring every independent trust input.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--download-directory", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run release-consumer verification from command-line inputs.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Optional arguments; process arguments are used when omitted.

    Returns
    -------
    int
        Zero after the complete chain passes; one on a sanitized failure.
    """
    namespace = _argument_parser().parse_args(list(argv) if argv is not None else None)
    try:
        expectations = ConsumerExpectations.from_inputs(
            repository=namespace.repository,
            tag=namespace.tag,
            source_commit=namespace.source_commit,
            image=namespace.image,
            image_digest=namespace.image_digest,
            download_directory=namespace.download_directory,
        )
        summary = verify_release_consumer(expectations)
    except ConsumerVerificationError as error:
        print(f"Release consumer verification failed: {error}")
        return 1
    generators = ", ".join(summary.sbom_generators)
    print(
        "Release consumer verification passed: "
        f"repository={expectations.repository}; tag={expectations.tag}; "
        f"source={expectations.source_commit}; assets={summary.assets}; "
        f"checksum_payloads={summary.checksum_payloads}; "
        f"image_digest={expectations.image_digest}; "
        f"SPDX=2.3; packages={summary.sbom_packages}; "
        f"generators={generators}; "
        f"provenance={summary.provenance_attestations}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
