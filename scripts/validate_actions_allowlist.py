"""Validate immutable workflow references against the exact Actions allowlist."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from collections.abc import Collection

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"
ACTIONS_ALLOWLIST_PATH = REPOSITORY_ROOT / ".github" / "actions-allowlist.json"
IMMUTABLE_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")


def _workflow_action_references(document: object) -> tuple[str, ...]:
    """Collect every ``uses`` value from a parsed workflow document.

    Parameters
    ----------
    document : object
        Parsed YAML node to inspect recursively.

    Returns
    -------
    tuple[str, ...]
        Action references found in mappings at any depth.

    Raises
    ------
    ValueError
        If a ``uses`` value is not a string.
    """
    references: list[str] = []
    if isinstance(document, dict):
        for key, value in document.items():
            if key == "uses":
                if not isinstance(value, str):
                    raise ValueError("workflow uses value must be a string")
                references.append(value)
            references.extend(_workflow_action_references(value))
    elif isinstance(document, list):
        for value in document:
            references.extend(_workflow_action_references(value))
    return tuple(references)


def external_action_references(workflow_directory: Path) -> frozenset[str]:
    """Collect external action references from every workflow.

    Parameters
    ----------
    workflow_directory : Path
        Directory containing GitHub Actions YAML workflows.

    Returns
    -------
    frozenset[str]
        Unique non-local action references found in the workflows.

    Raises
    ------
    ValueError
        If no workflow exists or a reference is not pinned to a commit SHA.
    """
    workflow_paths = tuple(
        sorted(
            (*workflow_directory.glob("*.yml"), *workflow_directory.glob("*.yaml")),
            key=lambda path: path.as_posix(),
        )
    )
    if not workflow_paths:
        raise ValueError(f"no workflows found in {workflow_directory}")

    references: set[str] = set()
    for path in workflow_paths:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise ValueError(f"workflow is not valid YAML: {path}") from error
        for reference in _workflow_action_references(document):
            if reference.startswith("./"):
                continue
            _, separator, revision = reference.rpartition("@")
            if (
                separator != "@"
                or IMMUTABLE_REVISION_PATTERN.fullmatch(revision) is None
            ):
                raise ValueError(
                    f"workflow action is not immutable: {path}: {reference}"
                )
            references.add(reference)
    return frozenset(references)


def validate_actions_allowlist(
    workflow_directory: Path = WORKFLOW_DIRECTORY,
    allowlist_path: Path = ACTIONS_ALLOWLIST_PATH,
) -> frozenset[str]:
    """Require the checked-in allowlist to equal all workflow references.

    Parameters
    ----------
    workflow_directory : Path, default=WORKFLOW_DIRECTORY
        Directory containing GitHub Actions YAML workflows.
    allowlist_path : Path, default=ACTIONS_ALLOWLIST_PATH
        JSON file defining the repository's selected Actions policy.

    Returns
    -------
    frozenset[str]
        Validated external action references.

    Raises
    ------
    ValueError
        If broad trust is enabled, the allowlist is malformed, or references drift.
    """
    references = external_action_references(workflow_directory)
    allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    if allowlist.get("github_owned_allowed") is not False:
        raise ValueError("github_owned_allowed must remain false")
    if allowlist.get("verified_allowed") is not False:
        raise ValueError("verified_allowed must remain false")

    allowed_value = allowlist.get("patterns_allowed")
    if not isinstance(allowed_value, list) or not all(
        isinstance(reference, str) for reference in allowed_value
    ):
        raise ValueError("patterns_allowed must be a list of strings")
    if len(allowed_value) != len(set(allowed_value)):
        raise ValueError("patterns_allowed must not contain duplicate references")
    allowed = frozenset(allowed_value)
    if allowed != references:
        raise ValueError(_drift_message(references=references, allowed=allowed))
    return references


def _drift_message(*, references: Collection[str], allowed: Collection[str]) -> str:
    """Describe exact workflow and allowlist drift.

    Parameters
    ----------
    references : Collection[str]
        External actions referenced by workflow files.
    allowed : Collection[str]
        External actions in the repository allowlist.

    Returns
    -------
    str
        Stable diagnostic containing missing and unused entries.
    """
    missing = sorted(set(references) - set(allowed))
    unused = sorted(set(allowed) - set(references))
    return f"Actions allowlist drift: missing={missing!r}; unused={unused!r}"


def main() -> int:
    """Validate the repository Actions policy.

    Returns
    -------
    int
        Zero when every external action is exactly allowlisted.
    """
    references = validate_actions_allowlist()
    print(f"Actions allowlist valid: {len(references)} immutable references.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
