"""Classify repository changes for Maru's change-aware CI policy.

The module intentionally uses only the Python standard library so the first CI
job can make a decision before installing project dependencies. High-risk
paths fail closed to the full acceptance workflow; ordinary module changes run
a bounded PostgreSQL selection, and documentation-only changes use no database.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

FULL_INTEGRATION_PARTS = {
    ".github",
    "migrations",
    "settings",
}
FULL_INTEGRATION_FILES = {
    "compose.yaml",
    "Dockerfile",
    "pyproject.toml",
    "uv.lock",
    "tests/conftest.py",
    "scripts/ci_changes.py",
    "scripts/run_ci_test_shard.py",
}
FULL_INTEGRATION_PREFIXES = (
    ".githooks/",
    "scripts/",
    "src/maru/audit/",
    "src/maru/authorization/",
    "src/maru/identity/",
)
PROTECTED_DELETION_PREFIXES = (
    ".github/",
    ".githooks/",
    "docs/architecture/decisions/",
    "docs/checkpoints/",
    "docs/project/",
    "docs/security/",
    "frontends/",
    "scripts/",
    "src/",
    "tests/",
)
PROTECTED_DELETION_FILES = {
    "AGENTS.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "Dockerfile",
    "GOVERNANCE.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
    "compose.yaml",
    "docs/development/repository-governance.md",
    "docs/product/requirements.md",
    "pyproject.toml",
    "uv.lock",
}
CRITICAL_TARGETED_TESTS = (
    "tests/integration/test_api_documentation.py",
    "tests/integration/test_health_readiness.py",
)
MASS_DELETION_THRESHOLD = 25
NAME_STATUS_FIELD_COUNT = 2
RENAMED_NAME_STATUS_FIELD_COUNT = 3
MODULE_PATH_PART_COUNT = 3
TARGETED_INTEGRATION_MAX_SECONDS = 1_800.0
STAFF_CONSOLE_STATIC_PREFIX = "src/maru/core/static/staff-console/"
CROSS_CUTTING_DJANGO_ASSET_PREFIXES = (
    "src/maru/static/",
    "src/maru/templates/",
)
DEPENDENCY_REVIEW_FILES = {
    "frontends/staff-console/package.json",
    "frontends/staff-console/pnpm-lock.yaml",
    "pyproject.toml",
    "uv.lock",
}


@dataclass(frozen=True, slots=True)
class ChangedFile:
    """A normalized path and its Git change status.

    Parameters
    ----------
    path : PurePosixPath
        Repository-relative path represented by this change entry.
    status : str
        Git name-status token such as ``M``, ``A``, or ``D``.

    Attributes
    ----------
    path : PurePosixPath
        Repository-relative path represented by this change entry.
    status : str
        Git name-status token such as ``M``, ``A``, or ``D``.
    """

    path: PurePosixPath
    status: str


@dataclass(frozen=True, slots=True)
class CIPlan:
    """The checks required for a set of repository changes.

    Parameters
    ----------
    documentation : bool
        Whether contributor documentation must be validated and built.
    frontend : bool
        Whether the Staff Console contract and build must be checked.
    python : bool
        Whether Python unit and framework checks are relevant.
    packaging : bool
        Whether Python distribution artifacts must be built and inspected.
    security : bool
        Whether dependency vulnerability checks are relevant.
    dependency_review : bool
        Whether GitHub's pull-request dependency comparison is relevant.
    integration : str
        PostgreSQL policy: ``none``, ``targeted``, or ``full``.
    destructive : bool
        Whether the pull request needs explicit destructive-change review.
    deleted_count : int
        Number of deleted repository paths.

    Attributes
    ----------
    documentation : bool
        Whether contributor documentation must be validated and built.
    frontend : bool
        Whether the Staff Console contract and build must be checked.
    python : bool
        Whether Python unit and framework checks are relevant.
    packaging : bool
        Whether Python distribution artifacts must be built and inspected.
    security : bool
        Whether dependency vulnerability checks are relevant.
    dependency_review : bool
        Whether GitHub's pull-request dependency comparison is relevant.
    integration : str
        PostgreSQL policy: ``none``, ``targeted``, or ``full``.
    destructive : bool
        Whether the pull request needs explicit destructive-change review.
    deleted_count : int
        Number of deleted repository paths.
    """

    documentation: bool
    frontend: bool
    python: bool
    packaging: bool
    security: bool
    dependency_review: bool
    integration: str
    destructive: bool
    deleted_count: int

    def github_outputs(self) -> dict[str, str]:
        """Return lowercase values suitable for ``GITHUB_OUTPUT``.

        Returns
        -------
        dict[str, str]
            Stable workflow output names and serialized scalar values.
        """
        return {
            "documentation": str(self.documentation).lower(),
            "frontend": str(self.frontend).lower(),
            "python": str(self.python).lower(),
            "packaging": str(self.packaging).lower(),
            "security": str(self.security).lower(),
            "dependency_review": str(self.dependency_review).lower(),
            "integration": self.integration,
            "destructive": str(self.destructive).lower(),
            "deleted_count": str(self.deleted_count),
        }


def parse_name_status(output: str) -> tuple[ChangedFile, ...]:
    """Parse ``git diff --name-status`` output into normalized changes.

    Parameters
    ----------
    output : str
        Newline-delimited Git name-status output.

    Returns
    -------
    tuple[ChangedFile, ...]
        Changes in the order reported by Git. Renames produce a deletion entry
        for the source followed by a rename entry for the destination.

    Raises
    ------
    ValueError
        If a non-empty line does not contain a status and path.
    """
    changes: list[ChangedFile] = []
    for line in output.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) < NAME_STATUS_FIELD_COUNT:
            raise ValueError(f"invalid git name-status line: {line!r}")
        raw_status = fields[0]
        status = raw_status[:1]
        if status == "R":
            if len(fields) != RENAMED_NAME_STATUS_FIELD_COUNT:
                raise ValueError(f"invalid git rename line: {line!r}")
            source = PurePosixPath(fields[1].replace("\\", "/"))
            destination = PurePosixPath(fields[2].replace("\\", "/"))
            changes.extend(
                (
                    ChangedFile(source, "D"),
                    ChangedFile(destination, "R"),
                )
            )
            continue
        path = fields[-1]
        changes.append(ChangedFile(PurePosixPath(path.replace("\\", "/")), status))
    return tuple(changes)


def classify_changes(changes: Sequence[ChangedFile]) -> CIPlan:
    """Classify changes using Maru's fail-closed CI routing policy.

    Parameters
    ----------
    changes : Sequence[ChangedFile]
        Repository changes to classify.

    Returns
    -------
    CIPlan
        Required checks and destructive-change signal.
    """
    paths = tuple(change.path.as_posix() for change in changes)
    deleted = tuple(change for change in changes if change.status == "D")
    python = any(_is_python_related(path) for path in paths)
    frontend = any(_is_frontend_related(path) for path in paths)
    packaging = any(_is_packaging_related(path) for path in paths)
    documentation = python or any(_is_documentation_related(path) for path in paths)
    security = any(_is_security_related(path) for path in paths)
    dependency_review = any(_is_dependency_review_related(path) for path in paths)
    full = any(_requires_full_integration(path) for path in paths)
    targeted = python and any(
        path.startswith(("src/", "tests/integration/")) for path in paths
    )
    protected_deletion = any(_is_protected_deletion(change.path) for change in deleted)
    destructive = protected_deletion or len(deleted) >= MASS_DELETION_THRESHOLD
    integration = "full" if full or destructive else "targeted" if targeted else "none"
    return CIPlan(
        documentation=documentation,
        frontend=frontend,
        python=python,
        packaging=packaging,
        security=security,
        dependency_review=dependency_review,
        integration=integration,
        destructive=destructive,
        deleted_count=len(deleted),
    )


def select_targeted_integration_tests(
    changes: Sequence[ChangedFile], integration_directory: Path
) -> tuple[Path, ...]:
    """Select bounded whole-file integration tests for ordinary changes.

    Directly changed integration tests are always selected. For a changed
    ``src/maru/<module>`` path, tests named for that module or importing its
    package are included. Two small platform smoke tests make an empty module
    match useful without silently expanding to the complete suite.

    Parameters
    ----------
    changes : Sequence[ChangedFile]
        Repository changes used to infer affected modules.
    integration_directory : Path
        Directory containing integration test files.

    Returns
    -------
    tuple[Path, ...]
        Stable, unique repository test paths.
    """
    repository_root = integration_directory.parents[1]
    candidates = tuple(sorted(integration_directory.glob("test_*.py")))
    modules = {
        change.path.parts[2]
        for change in changes
        if len(change.path.parts) >= MODULE_PATH_PART_COUNT
        and change.path.parts[:2] == ("src", "maru")
    }
    direct = {
        repository_root / change.path.as_posix()
        for change in changes
        if change.status != "D"
        and change.path.as_posix().startswith("tests/integration/test_")
    }
    selected = set(direct)
    for candidate in candidates:
        content = candidate.read_text(encoding="utf-8")
        if any(
            f"test_{module}" in candidate.name or f"maru.{module}" in content
            for module in modules
        ):
            selected.add(candidate)
    selected.update(
        repository_root / relative_path
        for relative_path in CRITICAL_TARGETED_TESTS
        if (repository_root / relative_path).is_file()
    )
    return tuple(sorted(selected, key=lambda path: path.as_posix()))


def enforce_targeted_time_budget(
    plan: CIPlan,
    changes: Sequence[ChangedFile],
    integration_directory: Path,
    timing_file: Path,
) -> CIPlan:
    """Route an oversized or unmeasurable targeted selection to full acceptance.

    Parameters
    ----------
    plan : CIPlan
        Initial path-based acceptance plan.
    changes : Sequence[ChangedFile]
        Repository changes used to select affected integration files.
    integration_directory : Path
        Directory containing integration test files.
    timing_file : Path
        Accepted file-duration map used by full sharding.

    Returns
    -------
    CIPlan
        The original plan when its measured selection fits the targeted budget;
        otherwise, an equivalent plan requiring full acceptance.
    """
    if plan.integration != "targeted":
        return plan
    selected = select_targeted_integration_tests(changes, integration_directory)
    if not selected or not timing_file.is_file():
        return replace(plan, integration="full")
    durations = _load_integration_durations(timing_file)
    repository_root = integration_directory.parents[1].resolve()
    relative_paths = tuple(
        path.resolve().relative_to(repository_root).as_posix() for path in selected
    )
    if any(path not in durations for path in relative_paths):
        return replace(plan, integration="full")
    estimated_seconds = sum(durations[path] for path in relative_paths)
    if estimated_seconds > TARGETED_INTEGRATION_MAX_SECONDS:
        return replace(plan, integration="full")
    return plan


def _load_integration_durations(timing_file: Path) -> dict[str, float]:
    """Load a non-empty positive integration-duration map.

    Parameters
    ----------
    timing_file : Path
        JSON map from repository integration path to measured seconds.

    Returns
    -------
    dict[str, float]
        Normalized positive durations keyed by repository path.

    Raises
    ------
    TypeError
        If the JSON root or an entry has an invalid type.
    ValueError
        If the map is empty or contains a non-positive duration.
    """
    value = json.loads(timing_file.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("integration timing map must be a JSON object")
    durations: dict[str, float] = {}
    for path, seconds in value.items():
        if (
            not isinstance(path, str)
            or isinstance(seconds, bool)
            or not isinstance(seconds, int | float)
        ):
            raise TypeError("integration timing entries need string paths and numbers")
        duration = float(seconds)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("integration timing durations must be finite and positive")
        durations[Path(path).as_posix()] = duration
    if not durations:
        raise ValueError("integration timing map must not be empty")
    return durations


def _is_python_related(path: str) -> bool:
    """Return whether a path affects Python behavior or shipped Django assets.

    Parameters
    ----------
    path : str
        Repository-relative POSIX path.

    Returns
    -------
    bool
        ``True`` when Python checks are relevant.
    """
    pure_path = PurePosixPath(path)
    django_runtime_asset = (
        path.startswith("src/maru/")
        and any(part in {"static", "templates"} for part in pure_path.parts)
        and not path.startswith(STAFF_CONSOLE_STATIC_PREFIX)
    )
    return (
        path.endswith(".py")
        or path in {"pyproject.toml", "uv.lock"}
        or django_runtime_asset
    )


def _is_frontend_related(path: str) -> bool:
    """Return whether a path affects Staff Console source, output, or API contract.

    Parameters
    ----------
    path : str
        Repository-relative POSIX path.

    Returns
    -------
    bool
        ``True`` when frontend checks are relevant.
    """
    return (
        path.startswith(("frontends/", STAFF_CONSOLE_STATIC_PREFIX))
        or path == "openapi.yaml"
    )


def _is_packaging_related(path: str) -> bool:
    """Return whether a path changes a built Python distribution.

    Parameters
    ----------
    path : str
        Repository-relative POSIX path.

    Returns
    -------
    bool
        ``True`` when wheel and source-archive inspection is relevant.
    """
    return path in {
        "LICENSE",
        "README.md",
        "THIRD_PARTY_NOTICES.md",
        "pyproject.toml",
    } or path.startswith(("frontends/staff-console/", "src/maru/"))


def _is_documentation_related(path: str) -> bool:
    """Return whether a path affects maintained or generated documentation.

    Parameters
    ----------
    path : str
        Repository-relative POSIX path.

    Returns
    -------
    bool
        ``True`` when Sphinx checks are relevant.
    """
    return path.startswith("docs/") or path.endswith(".md")


def _is_security_related(path: str) -> bool:
    """Return whether a path changes dependency or automation trust inputs.

    Parameters
    ----------
    path : str
        Repository-relative POSIX path.

    Returns
    -------
    bool
        ``True`` when dependency auditing is relevant.
    """
    return path in {
        "Dockerfile",
        "pyproject.toml",
        "uv.lock",
        "frontends/staff-console/package.json",
        "frontends/staff-console/pnpm-lock.yaml",
    } or path.startswith(".github/workflows/")


def _is_dependency_review_related(path: str) -> bool:
    """Return whether GitHub can compare a changed dependency input.

    Parameters
    ----------
    path : str
        Repository-relative POSIX path.

    Returns
    -------
    bool
        ``True`` for graph-visible manifests, locks, and workflow manifests.

    Notes
    -----
    Container base images remain part of current-tree security auditing but
    are not represented by GitHub's dependency comparison.
    """
    return path in DEPENDENCY_REVIEW_FILES or (
        path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
    )


def _requires_full_integration(path: str) -> bool:
    """Return whether a path crosses a high-risk acceptance boundary.

    Parameters
    ----------
    path : str
        Repository-relative POSIX path.

    Returns
    -------
    bool
        ``True`` when targeted tests are not sufficient evidence.
    """
    pure_path = PurePosixPath(path)
    if path in FULL_INTEGRATION_FILES:
        return True
    if path.startswith(CROSS_CUTTING_DJANGO_ASSET_PREFIXES):
        return True
    if path.startswith(FULL_INTEGRATION_PREFIXES):
        return True
    if any(part in FULL_INTEGRATION_PARTS for part in pure_path.parts):
        return True
    return pure_path.name in {"models.py", "conftest.py"}


def _is_protected_deletion(path: PurePosixPath) -> bool:
    """Return whether deleting a path needs explicit maintainer review.

    Parameters
    ----------
    path : PurePosixPath
        Repository-relative path being deleted.

    Returns
    -------
    bool
        ``True`` for governance, automation, architecture, or source paths.
    """
    normalized = path.as_posix()
    return normalized in PROTECTED_DELETION_FILES or normalized.startswith(
        PROTECTED_DELETION_PREFIXES
    )


def git_changes(base: str, head: str) -> tuple[ChangedFile, ...]:
    """Read name-status changes between two Git revisions.

    Parameters
    ----------
    base : str
        Base revision or merge-base commit.
    head : str
        Head revision to classify.

    Returns
    -------
    tuple[ChangedFile, ...]
        Normalized changes reported by Git.

    Raises
    ------
    FileNotFoundError
        If Git is not installed or available on ``PATH``.
    """
    git_executable = shutil.which("git")
    if git_executable is None:
        raise FileNotFoundError("Git executable is required for CI classification")
    completed = subprocess.run(  # noqa: S603
        [git_executable, "diff", "--name-status", "--find-renames", base, head],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_name_status(completed.stdout)


def write_github_outputs(outputs: dict[str, str], destination: Path) -> None:
    """Append scalar workflow outputs to GitHub's environment file.

    Parameters
    ----------
    outputs : dict[str, str]
        Output names and newline-free values.
    destination : Path
        GitHub-provided output file.

    Raises
    ------
    ValueError
        If a name or value contains a newline.
    """
    lines: list[str] = []
    for name, value in outputs.items():
        if "\n" in name or "\n" in value:
            raise ValueError("GitHub scalar outputs cannot contain newlines")
        lines.append(f"{name}={value}")
    with destination.open("a", encoding="utf-8", newline="\n") as output_file:
        output_file.write("\n".join(lines) + "\n")


def _argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser with ``plan`` and ``tests`` subcommands.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "tests"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--base", required=True)
        subparser.add_argument("--head", required=True)
    plan_parser = subparsers.choices["plan"]
    plan_parser.add_argument("--github-output", type=Path)
    plan_parser.add_argument("--labels-json", default="[]")
    plan_parser.add_argument(
        "--integration-directory",
        type=Path,
        default=Path("tests/integration"),
    )
    plan_parser.add_argument(
        "--timing-file",
        type=Path,
        default=Path("scripts/ci_integration_timings.json"),
    )
    tests_parser = subparsers.choices["tests"]
    tests_parser.add_argument(
        "--integration-directory",
        type=Path,
        default=Path("tests/integration"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Classify changes or print targeted tests for CI.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Optional arguments; process arguments are used when omitted.

    Returns
    -------
    int
        Zero after writing a valid plan or test selection.

    Raises
    ------
    ValueError
        If labels JSON is not a list of strings.
    """
    namespace = _argument_parser().parse_args(list(argv) if argv is not None else None)
    changes = git_changes(namespace.base, namespace.head)
    if namespace.command == "tests":
        selected = select_targeted_integration_tests(
            changes,
            namespace.integration_directory.resolve(),
        )
        print("\n".join(path.as_posix() for path in selected))
        return 0

    labels_value = json.loads(namespace.labels_json)
    if labels_value is None:
        labels_value = []
    if not isinstance(labels_value, list) or not all(
        isinstance(label, str) for label in labels_value
    ):
        raise ValueError("labels JSON must be a list of strings")
    plan = enforce_targeted_time_budget(
        classify_changes(changes),
        changes,
        namespace.integration_directory.resolve(),
        namespace.timing_file.resolve(),
    )
    outputs = plan.github_outputs()
    outputs["destructive_approved"] = str(
        not plan.destructive or "destructive-change-reviewed" in labels_value
    ).lower()
    if namespace.github_output is not None:
        write_github_outputs(outputs, namespace.github_output)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
