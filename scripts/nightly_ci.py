"""Deduplicate exact-main nightly acceptance without hiding earlier failures."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

MAX_HISTORY = 100


def nightly_decision(
    runs: Sequence[dict[str, object]], commit: str, current_run: int
) -> str:
    """Choose one exact-revision nightly action from authenticated run metadata.

    Parameters
    ----------
    runs : Sequence[dict[str, object]]
        Runs returned for the default-branch full-acceptance workflow.
    commit : str
        Exact default-branch revision being considered.
    current_run : int
        This scheduling run, excluded from its own deduplication.

    Returns
    -------
    str
        ``run``, ``passed``, ``active`` or ``blocked``; failures are not retried.

    Raises
    ------
    ValueError
        If the candidate revision or run metadata is malformed.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or current_run < 1:
        raise ValueError("nightly acceptance requires an exact commit and run ID")
    previous = []
    for run in runs:
        if not {
            "id",
            "head_sha",
            "head_branch",
            "status",
            "conclusion",
            "event",
        } <= set(run):
            raise ValueError("incomplete full-acceptance run metadata")
        if (
            run["id"] == current_run
            or run["head_sha"] != commit
            or run["head_branch"] != "main"
        ):
            continue
        if run["event"] not in {"schedule", "workflow_dispatch"}:
            continue
        previous.append(run)
    if any(
        run["status"] == "completed" and run["conclusion"] == "success"
        for run in previous
    ):
        return "passed"
    if any(
        run["status"] in {"queued", "in_progress", "waiting", "pending", "requested"}
        for run in previous
    ):
        return "active"
    return "blocked" if previous else "run"


def main() -> int:
    """Read one bounded exact-revision history page and emit safe workflow outputs.

    Returns
    -------
    int
        Zero for an actionable or already-covered revision; nonzero after failure.

    Raises
    ------
    ValueError
        If repository, revision or run history cannot be validated completely.
    """
    repository = os.environ["GITHUB_REPOSITORY"]
    commit = os.environ["GITHUB_SHA"]
    run_id = int(os.environ["GITHUB_RUN_ID"])
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or run_id < 1:
        raise ValueError("nightly acceptance requires an exact commit and run ID")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository identity")
    gh = shutil.which("gh")
    if gh is None:
        raise ValueError("GitHub CLI is required for authenticated read-only history")
    # Fixed read-only API, validated repository and argument array; no shell.
    response = subprocess.run(  # noqa: S603
        [
            gh,
            "api",
            "--method",
            "GET",
            f"repos/{repository}/actions/workflows/full-ci.yml/runs",
            "-f",
            f"head_sha={commit}",
            "-f",
            "branch=main",
            "-f",
            f"per_page={MAX_HISTORY}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    history = json.loads(response.stdout)
    if (
        type(history.get("total_count")) is not int
        or history["total_count"] >= MAX_HISTORY
    ):
        raise ValueError("nightly history is incomplete; manual inspection is required")
    runs = history.get("workflow_runs")
    if not isinstance(runs, list) or len(runs) != history["total_count"]:
        raise ValueError("nightly history count does not match its complete page")
    decision = nightly_decision(runs, commit, run_id)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"run_full={str(decision == 'run').lower()}\n")
    print(f"Exact-main nightly acceptance: {commit}: {decision}.")
    if decision == "blocked":
        print(
            "::error::An earlier exact-revision full run did not pass. "
            "Repair or inspect it; nightly checks do not blindly retry."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
