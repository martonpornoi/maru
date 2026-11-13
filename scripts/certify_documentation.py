"""Select and check a clean, exact documentation candidate without PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.ci_changes import classify_changes, git_changes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scripts.ci_changes import ChangedFile, CIPlan

ROOT = Path(__file__).resolve().parents[1]
ROOT_DOCUMENTS = frozenset(
    {
        "AGENTS.md",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "GOVERNANCE.md",
        "README.md",
        "SECURITY.md",
        "SUPPORT.md",
        "THIRD_PARTY_NOTICES.md",
    }
)


def classify_documentation_changes(changes: Sequence[ChangedFile]) -> CIPlan | None:
    """Require both a prose-only diff and the existing hosted documentation plan.

    Parameters
    ----------
    changes : Sequence[ChangedFile]
        Complete Git diff, including any deletion or rename source.

    Returns
    -------
    CIPlan | None
        Shared hosted plan when eligible, otherwise retain ordinary certification.
    """
    if not changes or any(
        change.status not in {"A", "M"}
        or not (
            change.path.as_posix() in ROOT_DOCUMENTS
            or (
                change.path.suffix in {".md", ".rst"}
                and change.path.as_posix().startswith(("docs/", ".agents/skills/"))
                and ".." not in change.path.parts
            )
        )
        for change in changes
    ):
        return None

    plan = classify_changes(changes)
    if (
        plan.documentation
        and plan.integration == "none"
        and plan.history == "current"
        and not (
            plan.python
            or plan.frontend
            or plan.security
            or plan.dependency_review
            or plan.destructive
        )
    ):
        return plan
    return None


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    git = shutil.which("git")
    if git is None:
        raise FileNotFoundError("Git is required to verify the exact candidate.")
    return subprocess.run(  # noqa: S603 -- installed Git and literal arguments
        [git, *args], check=check, capture_output=True
    )


def _require_exact_checkout(head: str) -> None:
    if _git("rev-parse", "HEAD").stdout.decode("ascii").strip() != head:
        raise RuntimeError("The documentation candidate HEAD changed.")
    if _git("status", "--porcelain=v1", "--untracked-files=all").stdout:
        raise RuntimeError("Documentation certification requires a clean checkout.")


def _tree_entries(commit: str) -> dict[bytes, bytes]:
    entries = _git("ls-tree", "-rz", "--full-tree", commit).stdout.split(b"\0")
    return {
        path: metadata
        for entry in entries
        if entry
        for metadata, path in [entry.split(b"\t", 1)]
    }


def _candidate_plan(
    base: str, head: str
) -> tuple[CIPlan, tuple[ChangedFile, ...]] | None:
    if base == head:
        return None
    ancestry = _git("merge-base", "--is-ancestor", base, head, check=False)
    if ancestry.returncode == 1:
        return None
    ancestry.check_returncode()
    changes = git_changes(base, head)
    plan = classify_documentation_changes(changes)
    if plan is None:
        return None
    # Reconcile every changed tree entry, including modes, with the diff.
    # Local Git display settings cannot hide a mixed change from this check.
    old, new = _tree_entries(base), _tree_entries(head)
    actual = {
        path for path in old.keys() | new.keys() if old.get(path) != new.get(path)
    }
    planned = {change.path.as_posix().encode("utf-8") for change in changes}
    if actual != planned or any(
        not new.get(path, b"").startswith(b"100644 blob ")
        or (path in old and not old[path].startswith(b"100644 blob "))
        for path in actual
    ):
        return None
    return plan, changes


def _output_directory(root: Path, head: str) -> Path:
    parent = root / ".tools" / "documentation-certification"
    if parent.resolve() != parent:
        raise RuntimeError("Documentation evidence directory must not be redirected.")
    parent.mkdir(parents=True, exist_ok=True)
    if parent.resolve() != parent:
        raise RuntimeError("Documentation evidence directory must not be redirected.")
    return Path(tempfile.mkdtemp(prefix=f"{head[:12]}-", dir=parent))


def _checks(plan: CIPlan, output: Path, uv: Path) -> list[tuple[str, list[str]]]:
    python = sys.executable
    locked = [str(uv), "run", "--all-groups", "--locked"]
    checks = [
        ("locked_inputs", [str(uv), "lock", "--check"]),
        ("actions_policy", [python, "scripts/validate_actions_allowlist.py"]),
        ("format", [*locked, "ruff", "format", "--check", "."]),
        ("lint", [*locked, "ruff", "check", "."]),
        ("typing", [*locked, "mypy", "src"]),
        ("documentation_policy", [python, "scripts/validate_docs.py"]),
        (
            "license_contracts",
            [
                *locked,
                "pytest",
                "tests/unit/test_package_licensing.py",
                "tests/unit/test_release_metadata.py",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--basetemp={output / 'tmp' / 'pytest'}",
                f"--junitxml={output / 'licensing.xml'}",
            ],
        ),
    ]
    if plan.packaging:
        distributions = str(output / "distributions")
        checks.extend(
            [
                ("build_distributions", [str(uv), "build", "--out-dir", distributions]),
                (
                    "inspect_distributions",
                    [
                        python,
                        "scripts/verify_package_artifacts.py",
                        "--distribution-directory",
                        distributions,
                    ],
                ),
            ]
        )
    checks.extend(
        [
            ("docstring_style", [*locked, "pydoclint", "src", "scripts"]),
            (
                "docstring_content",
                [python, "scripts/validate_python_docstrings.py", "src", "scripts"],
            ),
            (
                "sphinx_html",
                [
                    *locked,
                    "sphinx-build",
                    "-W",
                    "--keep-going",
                    "--fresh-env",
                    "-j",
                    "auto",
                    "-d",
                    str(output / "doctrees"),
                    "-b",
                    "html",
                    "docs",
                    str(output / "html"),
                ],
            ),
        ]
    )
    return checks


def _write_json(path: Path, data: dict[str, object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def _certify(
    root: Path,
    base: str,
    head: str,
    plan: CIPlan,
    changes: tuple[ChangedFile, ...],
    uv: Path,
) -> Path:
    started = time.monotonic()
    output = _output_directory(root, head)
    print(f"Checking documentation for {head} (base {base}).", flush=True)
    print(f"Evidence: {output}", flush=True)
    temporary = output / "tmp"
    temporary.mkdir()
    environment = os.environ.copy()
    # Certification runs the entire selected test files regardless of local filters.
    environment.pop("PYTEST_ADDOPTS", None)
    environment.update(
        CI="true",
        MYPY_CACHE_DIR=str(output / "mypy"),
        MARU_DATABASE_URL="postgresql://maru:maru@127.0.0.1:1/maru_unit_no_database",
        TEMP=str(temporary),
        TMP=str(temporary),
        TMPDIR=str(temporary),
    )
    scope: dict[str, object] = {
        "commit": head,
        "base_commit": base,
        "tree": _git("rev-parse", f"{head}^{{tree}}").stdout.decode("ascii").strip(),
        "change_plan": asdict(plan),
        "changed_paths": [
            {"path": change.path.as_posix(), "status": change.status}
            for change in changes
        ],
    }
    _write_json(output / "scope.json", scope)
    gates: list[str] = []
    for name, command in _checks(plan, output, uv):
        log = output / f"{name}.log"
        print(f"  {name}", flush=True)
        with log.open("xb") as stream:
            result = subprocess.run(  # noqa: S603 -- defined local quality commands
                command,
                cwd=root,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if result.returncode:
            raise RuntimeError(f"{name} failed ({result.returncode}); see {log}.")
        gates.append(name)
    _require_exact_checkout(head)
    receipt = output / "certification.json"
    _write_json(
        receipt,
        {
            **scope,
            "schema_version": 1,
            "result": "documentation_success",
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "gates": gates,
            "postgresql": "not_selected",
            "isolated_postgres_instances": 0,
            "combined_branch_coverage": "not_selected",
        },
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    """Select or run the documentation path for an exact local commit.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Arguments; the process arguments are used by default.

    Returns
    -------
    int
        Zero after successful selection or checks; one on an operational failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run"))
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--uv", type=Path)
    args = parser.parse_args(argv)
    if not all(re.fullmatch(r"[0-9a-f]{40}", oid) for oid in (args.base, args.head)):
        parser.error("Base and head must be full commit IDs.")
    if Path.cwd().resolve() != ROOT:
        parser.error("Run from the checkout containing this certifier.")
    try:
        _require_exact_checkout(args.head)
        candidate = _candidate_plan(args.base, args.head)
        if args.action == "plan":
            print("documentation" if candidate is not None else "native")
            return 0
        if candidate is None:
            print("This commit requires ordinary certification.", file=sys.stderr)
            return 1
        if args.uv is None or not args.uv.is_file():
            print("The resolved uv executable is required.", file=sys.stderr)
            return 1
        plan, changes = candidate
        receipt = _certify(ROOT, args.base, args.head, plan, changes, args.uv.resolve())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1
    print(
        "Maru documentation_success; PostgreSQL and combined coverage not selected: "
        f"{receipt}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
