"""Validate direct and audited nested actions against the exact allowlist."""

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
ACTIONS_TRANSITIVE_REFERENCES_PATH = (
    REPOSITORY_ROOT / ".github" / "actions-transitive-references.json"
)
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
    transitive_references_path: Path | None = None,
) -> frozenset[str]:
    """Require the allowlist to equal direct and audited transitive references.

    Parameters
    ----------
    workflow_directory : Path, default=WORKFLOW_DIRECTORY
        Directory containing GitHub Actions YAML workflows.
    allowlist_path : Path, default=ACTIONS_ALLOWLIST_PATH
        JSON file defining the repository's selected Actions policy.
    transitive_references_path : Path | None, default=None
        JSON audit map for actions invoked inside directly used composite
        actions. When omitted, use the sibling repository file if it exists.

    Returns
    -------
    frozenset[str]
        Validated direct and audited transitive action references.

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
    if transitive_references_path is None:
        sibling_path = allowlist_path.with_name(ACTIONS_TRANSITIVE_REFERENCES_PATH.name)
        transitive_references_path = sibling_path if sibling_path.is_file() else None
    transitive_value: object = {}
    if transitive_references_path is not None:
        transitive_value = json.loads(
            transitive_references_path.read_text(encoding="utf-8")
        )
    transitive_references = _validate_transitive_references(
        transitive_value,
        direct_references=references,
    )
    required_references = references | transitive_references
    allowed = frozenset(allowed_value)
    if allowed != required_references:
        raise ValueError(
            _drift_message(references=required_references, allowed=allowed)
        )
    return required_references


def _validate_transitive_references(
    value: object,
    *,
    direct_references: Collection[str],
) -> frozenset[str]:
    """Validate explicitly audited actions invoked by composite actions.

    Parameters
    ----------
    value : object
        Mapping from a direct composite-action reference to its audited nested
        action references.
    direct_references : Collection[str]
        Immutable external references found directly in workflow files.

    Returns
    -------
    frozenset[str]
        Unique immutable nested references required by the selected policy.

    Raises
    ------
    ValueError
        If the mapping is malformed, its parent is unused, or a nested
        reference is mutable.
    """
    if not isinstance(value, dict) or not all(
        isinstance(parent, str) and isinstance(children, list)
        for parent, children in value.items()
    ):
        raise ValueError(
            "transitive_action_references must map strings to lists of strings"
        )

    nested_references: set[str] = set()
    for parent, children in value.items():
        if parent not in direct_references:
            raise ValueError(f"transitive action parent is not used directly: {parent}")
        if not children or not all(isinstance(child, str) for child in children):
            raise ValueError(
                "transitive action references must be a non-empty string list: "
                f"{parent}"
            )
        if len(children) != len(set(children)):
            raise ValueError(
                f"transitive action references must not contain duplicates: {parent}"
            )
        for child in children:
            _, separator, revision = child.rpartition("@")
            if (
                child.startswith("./")
                or separator != "@"
                or IMMUTABLE_REVISION_PATTERN.fullmatch(revision) is None
            ):
                raise ValueError(
                    f"transitive action is not immutable: {parent}: {child}"
                )
            nested_references.add(child)
    return frozenset(nested_references)


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
        Zero when every direct and audited nested action is exactly allowlisted.
    """
    references = validate_actions_allowlist()
    print(
        "Actions allowlist valid: "
        f"{len(references)} direct and audited transitive immutable references."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
