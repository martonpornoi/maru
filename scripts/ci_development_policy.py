"""Expose the explicit temporary Programme PostgreSQL acceptance deferral.

This is repository policy, not an environment-variable or contributor-label
bypass. The original risk plan remains visible and full acceptance stays blocked
until the maintainer restores the tracked policy through review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

POLICY_FILE = Path(__file__).with_name("ci_postgresql_policy.json")
RESTORATION_ISSUE = 48


def postgresql_policy_mode(path: Path = POLICY_FILE) -> str:
    """Read one strictly validated repository-owned acceptance policy.

    Parameters
    ----------
    path : Path, default=POLICY_FILE
        Tracked policy input; alternate paths support isolated contract tests.

    Returns
    -------
    str
        Either required or explicitly deferred PostgreSQL acceptance.

    Raises
    ------
    ValueError
        If policy shape, version, mode or restoration ownership is unsupported.
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        type(value) is not dict
        or set(value) != {"schema_version", "mode", "restoration_issue"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["mode"] not in ("required", "deferred")
        or type(value["restoration_issue"]) is not int
        or value["restoration_issue"] != RESTORATION_ISSUE
    ):
        raise ValueError("Unsupported PostgreSQL acceptance policy")
    return str(value["mode"])


def apply_development_policy(outputs: dict[str, str]) -> dict[str, str]:
    """Retain risk selection while explicitly deferring database execution.

    Parameters
    ----------
    outputs : dict[str, str]
        Original classifier output, including deletion and dependency review.

    Returns
    -------
    dict[str, str]
        Fresh effective output; deferred code requires every non-database gate.

    Raises
    ------
    ValueError
        If the original acceptance path or tracked policy is unsupported.
    """
    original = outputs["integration"]
    if original not in {"none", "targeted", "full"}:
        raise ValueError("Unknown required integration path")
    deferred = postgresql_policy_mode() == "deferred" and original != "none"
    result = dict(outputs)
    result["required_integration"] = original
    result["postgresql_deferred"] = str(deferred).lower()
    if deferred:
        result["integration"] = "deferred"
        for key in ("documentation", "frontend", "python", "packaging", "security"):
            result[key] = "true"
    return result


def main() -> int:
    """Print policy state or fence full acceptance before database startup.

    Returns
    -------
    int
        Zero for valid policy inspection or restored full acceptance; one when
        a caller requests full acceptance while PostgreSQL remains deferred.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("mode", "require-full"))
    args = parser.parse_args()
    mode = postgresql_policy_mode()
    if args.command == "require-full" and mode != "required":
        print(
            "PostgreSQL is deferred under #48. Restore required policy "
            "before full acceptance or release."
        )
        return 1
    print(mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
