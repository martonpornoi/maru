"""Verify Python distribution metadata, legal files, and package assets."""

from __future__ import annotations

import argparse
import email
import tarfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

DEFAULT_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCE_DIRECTORY = PurePosixPath("src/maru")
PACKAGE_ASSET_DIRECTORIES = frozenset({"static", "templates"})
CACHE_DIRECTORY_NAMES = frozenset(
    {
        ".doctrees",
        ".hypothesis",
        ".mypy_cache",
        ".pip-audit-cache",
        ".pnpm-store",
        ".pytest_cache",
        ".ruff_cache",
        ".uv-cache",
        "__pycache__",
        "doctrees",
        "node_modules",
    }
)
CACHE_FILE_SUFFIXES = (".doctree", ".pyc", ".pyo")
MINIMUM_PEP639_METADATA_VERSION = (2, 4)


class ArtifactVerificationError(ValueError):
    """Report a Python distribution contract violation."""


@dataclass(frozen=True, slots=True)
class VerificationSummary:
    """Summarize a successful wheel and source-distribution verification.

    Attributes
    ----------
    wheel_path : Path
        The verified wheel path.
    sdist_path : Path
        The verified gzipped source-distribution path.
    license_file_count : int
        Number of PEP 639 legal files required in each artifact.
    package_asset_count : int
        Number of current templates and static assets required in each artifact.
    """

    wheel_path: Path
    sdist_path: Path
    license_file_count: int
    package_asset_count: int


def verify_distribution_directory(  # noqa: DOC502 - composed checks own failures
    distribution_directory: Path,
    *,
    repository_root: Path = DEFAULT_REPOSITORY_ROOT,
) -> VerificationSummary:
    """Verify the sole wheel and source distribution in a directory.

    Parameters
    ----------
    distribution_directory : Path
        Directory containing exactly one ``.whl`` and one ``.tar.gz`` file.
    repository_root : Path, default=DEFAULT_REPOSITORY_ROOT
        Repository whose project metadata and package assets define the contract.

    Returns
    -------
    VerificationSummary
        Verified artifact paths and contract cardinalities.

    Raises
    ------
    ArtifactVerificationError
        If artifact selection, metadata, legal files, package assets, or cache
        exclusions violate the repository contract.
    """
    wheel_path, sdist_path = _select_distribution_artifacts(distribution_directory)
    license_expression, license_files = _project_license_contract(repository_root)
    package_assets = _expected_package_assets(repository_root)

    _verify_wheel(
        wheel_path,
        license_expression=license_expression,
        license_files=license_files,
        package_assets=package_assets,
    )
    _verify_sdist(
        sdist_path,
        license_expression=license_expression,
        license_files=license_files,
        package_assets=package_assets,
    )
    return VerificationSummary(
        wheel_path=wheel_path,
        sdist_path=sdist_path,
        license_file_count=len(license_files),
        package_asset_count=len(package_assets),
    )


def _select_distribution_artifacts(
    distribution_directory: Path,
) -> tuple[Path, Path]:
    """Select one wheel and one source distribution.

    Parameters
    ----------
    distribution_directory : Path
        Directory to inspect without recursion.

    Returns
    -------
    tuple[Path, Path]
        Wheel and gzipped source-distribution paths.

    Raises
    ------
    ArtifactVerificationError
        If the directory is absent or does not contain exactly one artifact of
        each required type.
    """
    if not distribution_directory.is_dir():
        raise ArtifactVerificationError(
            f"distribution directory does not exist: {distribution_directory}"
        )
    wheels = sorted(
        path for path in distribution_directory.glob("*.whl") if path.is_file()
    )
    sdists = sorted(
        path for path in distribution_directory.glob("*.tar.gz") if path.is_file()
    )
    if len(wheels) != 1 or len(sdists) != 1:
        raise ArtifactVerificationError(
            "distribution directory must contain exactly one .whl and one .tar.gz: "
            f"wheels={len(wheels)}; sdists={len(sdists)}"
        )
    return wheels[0], sdists[0]


def _project_license_contract(
    repository_root: Path,
) -> tuple[str, tuple[PurePosixPath, ...]]:
    """Read and resolve the project's PEP 639 license contract.

    Parameters
    ----------
    repository_root : Path
        Repository containing ``pyproject.toml`` and declared legal files.

    Returns
    -------
    tuple[str, tuple[PurePosixPath, ...]]
        SPDX license expression and sorted repository-relative legal files.

    Raises
    ------
    ArtifactVerificationError
        If project license metadata is missing, malformed, unsafe, or unmatched.
    """
    configuration_path = repository_root / "pyproject.toml"
    if not configuration_path.is_file():
        raise ArtifactVerificationError(
            f"project configuration does not exist: {configuration_path}"
        )
    configuration = cast(
        "dict[str, object]",
        tomllib.loads(configuration_path.read_text(encoding="utf-8")),
    )
    project_value = configuration.get("project")
    if not isinstance(project_value, dict):
        raise ArtifactVerificationError("pyproject.toml has no [project] table")
    project = cast("dict[str, object]", project_value)

    expression = project.get("license")
    if not isinstance(expression, str) or not expression.strip():
        raise ArtifactVerificationError(
            "[project].license must be a non-empty PEP 639 SPDX expression"
        )
    patterns_value = project.get("license-files")
    if not isinstance(patterns_value, list) or not patterns_value:
        raise ArtifactVerificationError(
            "[project].license-files must contain at least one pattern"
        )
    if not all(isinstance(pattern, str) and pattern for pattern in patterns_value):
        raise ArtifactVerificationError(
            "[project].license-files patterns must be non-empty strings"
        )

    repository = repository_root.resolve()
    resolved_files: set[PurePosixPath] = set()
    for pattern in cast("list[str]", patterns_value):
        pattern_path = PurePosixPath(pattern.replace("\\", "/"))
        if pattern_path.is_absolute() or ".." in pattern_path.parts:
            raise ArtifactVerificationError(
                f"license-files pattern must remain inside the repository: {pattern}"
            )
        matches = sorted(path for path in repository.glob(pattern) if path.is_file())
        if not matches:
            raise ArtifactVerificationError(
                f"license-files pattern matches no repository file: {pattern}"
            )
        for path in matches:
            try:
                relative = path.resolve().relative_to(repository)
            except ValueError as error:
                raise ArtifactVerificationError(
                    f"declared legal file resolves outside the repository: {path}"
                ) from error
            resolved_files.add(PurePosixPath(relative.as_posix()))
    return expression, tuple(sorted(resolved_files))


def _expected_package_assets(repository_root: Path) -> tuple[PurePosixPath, ...]:
    """Collect every current package template and static asset.

    Parameters
    ----------
    repository_root : Path
        Repository containing the ``src/maru`` package tree.

    Returns
    -------
    tuple[PurePosixPath, ...]
        Sorted wheel-relative package asset paths.

    Raises
    ------
    ArtifactVerificationError
        If the package source directory or its asset inventory is absent.
    """
    source_directory = repository_root / Path(PACKAGE_SOURCE_DIRECTORY.as_posix())
    if not source_directory.is_dir():
        raise ArtifactVerificationError(
            f"package source directory does not exist: {source_directory}"
        )

    assets = {
        PurePosixPath("maru")
        / PurePosixPath(path.relative_to(source_directory).as_posix())
        for path in source_directory.rglob("*")
        if path.is_file()
        and PACKAGE_ASSET_DIRECTORIES.intersection(
            path.relative_to(source_directory).parts
        )
    }
    if not assets:
        raise ArtifactVerificationError(
            "src/maru contains no files below a templates or static directory"
        )
    return tuple(sorted(assets))


def _verify_wheel(
    wheel_path: Path,
    *,
    license_expression: str,
    license_files: Sequence[PurePosixPath],
    package_assets: Sequence[PurePosixPath],
) -> None:
    """Verify a wheel against project metadata and package assets.

    Parameters
    ----------
    wheel_path : Path
        Wheel archive to inspect.
    license_expression : str
        Required PEP 639 SPDX expression.
    license_files : Sequence[PurePosixPath]
        Required repository-relative legal files.
    package_assets : Sequence[PurePosixPath]
        Required wheel-relative templates and static assets.

    Raises
    ------
    ArtifactVerificationError
        If the wheel is malformed or violates the distribution contract.
    """
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            members: dict[PurePosixPath, zipfile.ZipInfo] = {}
            for information in archive.infolist():
                member = _normalize_member_name(information.filename, wheel_path)
                if member is None:
                    continue
                if member in members:
                    raise ArtifactVerificationError(
                        f"wheel has duplicate normalized member: {member.as_posix()}"
                    )
                members[member] = information

            _verify_no_cache_leaks(members, wheel_path)
            metadata_member = _unique_wheel_metadata_member(members, wheel_path)
            _verify_metadata(
                archive.read(members[metadata_member]),
                artifact_path=wheel_path,
                license_expression=license_expression,
                license_files=license_files,
            )
            legal_members = {
                metadata_member.parent / "licenses" / license_file
                for license_file in license_files
            }
            _require_members(
                required=legal_members,
                observed=members,
                artifact_path=wheel_path,
                contract="PEP 639 legal file",
            )
            _require_members(
                required=set(package_assets),
                observed=members,
                artifact_path=wheel_path,
                contract="package asset",
            )
    except (OSError, zipfile.BadZipFile) as error:
        raise ArtifactVerificationError(
            f"unable to read wheel archive {wheel_path}: {error}"
        ) from error


def _verify_sdist(
    sdist_path: Path,
    *,
    license_expression: str,
    license_files: Sequence[PurePosixPath],
    package_assets: Sequence[PurePosixPath],
) -> None:
    """Verify a source distribution against metadata and package assets.

    Parameters
    ----------
    sdist_path : Path
        Gzipped source-distribution archive to inspect.
    license_expression : str
        Required PEP 639 SPDX expression.
    license_files : Sequence[PurePosixPath]
        Required repository-relative legal files.
    package_assets : Sequence[PurePosixPath]
        Required wheel-relative templates and static assets.

    Raises
    ------
    ArtifactVerificationError
        If the source distribution is malformed or violates the contract.
    """
    try:
        with tarfile.open(sdist_path, mode="r:gz") as archive:
            members: dict[PurePosixPath, tarfile.TarInfo] = {}
            for information in archive.getmembers():
                member = _normalize_member_name(information.name, sdist_path)
                if member is None:
                    continue
                if member in members:
                    raise ArtifactVerificationError(
                        f"sdist has duplicate normalized member: {member.as_posix()}"
                    )
                members[member] = information

            _verify_no_cache_leaks(members, sdist_path)
            root = _sdist_root(members, sdist_path)
            metadata_member = root / "PKG-INFO"
            _require_members(
                required={metadata_member},
                observed=members,
                artifact_path=sdist_path,
                contract="root PKG-INFO",
            )
            metadata_stream = archive.extractfile(members[metadata_member])
            if metadata_stream is None:
                raise ArtifactVerificationError(
                    "sdist metadata is not a regular file: "
                    f"{metadata_member.as_posix()}"
                )
            _verify_metadata(
                metadata_stream.read(),
                artifact_path=sdist_path,
                license_expression=license_expression,
                license_files=license_files,
            )
            _require_members(
                required={root / license_file for license_file in license_files},
                observed=members,
                artifact_path=sdist_path,
                contract="PEP 639 legal file",
            )
            _require_members(
                required={
                    root / "src" / package_asset for package_asset in package_assets
                },
                observed=members,
                artifact_path=sdist_path,
                contract="package asset",
            )
    except (OSError, tarfile.TarError) as error:
        raise ArtifactVerificationError(
            f"unable to read source-distribution archive {sdist_path}: {error}"
        ) from error


def _normalize_member_name(
    raw_name: str,
    artifact_path: Path,
) -> PurePosixPath | None:
    """Normalize one archive member and reject unsafe paths.

    Parameters
    ----------
    raw_name : str
        Archive-supplied member name.
    artifact_path : Path
        Artifact used to contextualize validation failures.

    Returns
    -------
    PurePosixPath | None
        Normalized relative path, or ``None`` for an empty root entry.

    Raises
    ------
    ArtifactVerificationError
        If a member is absolute or attempts parent traversal.
    """
    member = PurePosixPath(raw_name.replace("\\", "/"))
    if member.is_absolute() or ".." in member.parts:
        raise ArtifactVerificationError(
            f"artifact contains unsafe member path: {artifact_path}: {raw_name}"
        )
    if not member.parts:
        return None
    return member


def _verify_no_cache_leaks(
    members: Mapping[PurePosixPath, object],
    artifact_path: Path,
) -> None:
    """Reject Python, test, linter, and Sphinx cache artifacts.

    Parameters
    ----------
    members : Mapping[PurePosixPath, object]
        Normalized artifact members.
    artifact_path : Path
        Artifact used to contextualize failures.

    Raises
    ------
    ArtifactVerificationError
        If an archive member is a known cache directory or cache file.
    """
    leaked = sorted(
        member
        for member in members
        if CACHE_DIRECTORY_NAMES.intersection(member.parts)
        or member.name.endswith(CACHE_FILE_SUFFIXES)
    )
    if leaked:
        raise ArtifactVerificationError(
            f"artifact contains cache or doctree members: {artifact_path}: "
            f"{[member.as_posix() for member in leaked]!r}"
        )


def _unique_wheel_metadata_member(
    members: Mapping[PurePosixPath, object],
    wheel_path: Path,
) -> PurePosixPath:
    """Find the wheel's sole ``.dist-info/METADATA`` member.

    Parameters
    ----------
    members : Mapping[PurePosixPath, object]
        Normalized wheel members.
    wheel_path : Path
        Wheel used to contextualize failures.

    Returns
    -------
    PurePosixPath
        Unique core-metadata member.

    Raises
    ------
    ArtifactVerificationError
        If the wheel does not contain exactly one metadata member.
    """
    candidates = sorted(
        member
        for member in members
        if member.name == "METADATA" and member.parent.name.endswith(".dist-info")
    )
    if len(candidates) != 1:
        raise ArtifactVerificationError(
            f"wheel must contain one .dist-info/METADATA member: {wheel_path}: "
            f"found={len(candidates)}"
        )
    return candidates[0]


def _sdist_root(
    members: Mapping[PurePosixPath, object],
    sdist_path: Path,
) -> PurePosixPath:
    """Require one common top-level source-distribution directory.

    Parameters
    ----------
    members : Mapping[PurePosixPath, object]
        Normalized source-distribution members.
    sdist_path : Path
        Source distribution used to contextualize failures.

    Returns
    -------
    PurePosixPath
        Sole top-level archive directory.

    Raises
    ------
    ArtifactVerificationError
        If the source distribution is empty or has multiple roots.
    """
    roots = {member.parts[0] for member in members if member.parts}
    if len(roots) != 1:
        raise ArtifactVerificationError(
            f"sdist must contain one top-level directory: {sdist_path}: "
            f"roots={sorted(roots)!r}"
        )
    return PurePosixPath(next(iter(roots)))


def _verify_metadata(
    payload: bytes,
    *,
    artifact_path: Path,
    license_expression: str,
    license_files: Sequence[PurePosixPath],
) -> None:
    """Verify PEP 639 fields in core metadata.

    Parameters
    ----------
    payload : bytes
        Serialized wheel ``METADATA`` or sdist ``PKG-INFO`` content.
    artifact_path : Path
        Artifact used to contextualize failures.
    license_expression : str
        Required SPDX expression.
    license_files : Sequence[PurePosixPath]
        Exact legal files required by project metadata.

    Raises
    ------
    ArtifactVerificationError
        If metadata predates PEP 639 or its license fields differ.
    """
    metadata = email.message_from_bytes(payload)
    raw_metadata_version = metadata.get("Metadata-Version")
    try:
        version_parts = tuple(
            int(part) for part in (raw_metadata_version or "").split(".")
        )
    except ValueError as error:
        raise ArtifactVerificationError(
            f"artifact has invalid Metadata-Version: {artifact_path}: "
            f"{raw_metadata_version!r}"
        ) from error
    if version_parts < MINIMUM_PEP639_METADATA_VERSION:
        raise ArtifactVerificationError(
            f"artifact metadata predates PEP 639: {artifact_path}: "
            f"{raw_metadata_version!r}"
        )

    observed_expression = metadata.get("License-Expression")
    if observed_expression != license_expression:
        raise ArtifactVerificationError(
            f"artifact License-Expression differs: {artifact_path}: "
            f"expected={license_expression!r}; observed={observed_expression!r}"
        )

    raw_license_files = cast(
        "list[str]",
        metadata.get_all("License-File", failobj=[]),
    )
    observed_files: list[PurePosixPath] = []
    for raw_file in raw_license_files:
        normalized = _normalize_member_name(raw_file, artifact_path)
        if normalized is None:
            raise ArtifactVerificationError(
                f"artifact has an empty License-File field: {artifact_path}"
            )
        observed_files.append(normalized)
    expected_files = tuple(sorted(license_files))
    if tuple(sorted(observed_files)) != expected_files:
        raise ArtifactVerificationError(
            f"artifact License-File fields differ: {artifact_path}: "
            f"expected={[path.as_posix() for path in expected_files]!r}; "
            f"observed={[path.as_posix() for path in sorted(observed_files)]!r}"
        )


def _require_members(
    *,
    required: set[PurePosixPath],
    observed: Mapping[PurePosixPath, object],
    artifact_path: Path,
    contract: str,
) -> None:
    """Require an exact set of named files to be present.

    Parameters
    ----------
    required : set[PurePosixPath]
        Members that must exist.
    observed : Mapping[PurePosixPath, object]
        Normalized artifact members.
    artifact_path : Path
        Artifact used to contextualize failures.
    contract : str
        Human-readable class of required member.

    Raises
    ------
    ArtifactVerificationError
        If any required member is absent.
    """
    missing = sorted(required - observed.keys())
    if missing:
        raise ArtifactVerificationError(
            f"artifact is missing {contract} members: {artifact_path}: "
            f"{[member.as_posix() for member in missing]!r}"
        )


def _argument_parser() -> argparse.ArgumentParser:
    """Build the package-artifact command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser for the distribution directory and repository root.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distribution-directory",
        required=True,
        type=Path,
        help="directory containing exactly one wheel and one .tar.gz sdist",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=DEFAULT_REPOSITORY_ROOT,
        help="repository defining pyproject metadata and src/maru assets",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run package-artifact verification from the command line.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Explicit arguments for tests, or ``None`` to read the process arguments.

    Returns
    -------
    int
        Zero after both artifacts satisfy the contract.
    """
    parser = _argument_parser()
    arguments = parser.parse_args(argv)
    try:
        summary = verify_distribution_directory(
            arguments.distribution_directory,
            repository_root=arguments.repository_root,
        )
    except ArtifactVerificationError as error:
        parser.error(str(error))
    print(
        "Package artifacts valid: "
        f"wheel={summary.wheel_path.name}; sdist={summary.sdist_path.name}; "
        f"legal_files={summary.license_file_count}; "
        f"package_assets={summary.package_asset_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
