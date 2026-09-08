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
        Runs returned for the default-branch full-acceptance workflow, with
        successful full gates independently verified in ``full_gate_passed``.
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
        run["status"] == "completed"
        and run["conclusion"] == "success"
        and run.get("full_gate_passed") is True
        for run in previous
    ):
        return "passed"
    if any(
        run["status"] in {"queued", "in_progress", "waiting", "pending", "requested"}
        for run in previous
    ):
        return "active"
    return "blocked" if previous else "run"


def completed_full_gate(
    jobs: Sequence[dict[str, object]], commit: str, run_id: int
) -> bool:
    """Require the actual aggregate gate, not selector-only workflow success.

    Parameters
    ----------
    jobs : Sequence[dict[str, object]]
        Complete latest-attempt job metadata from the selected workflow run.
    commit : str
        Exact source revision whose exhaustive evidence is required.
    run_id : int
        Run identity whose jobs were requested through the authenticated API.

    Returns
    -------
    bool
        Whether exactly one matching full gate completed successfully.

    Raises
    ------
    ValueError
        If duplicate aggregate names make the evidence ambiguous.
    """
    gates = [
        job
        for job in jobs
        if isinstance(job.get("name"), str)
        and job["name"].rsplit(" / ", 1)[-1] == "Full CI gate"
    ]
    if len(gates) > 1:
        raise ValueError("duplicate full acceptance gate metadata")
    return bool(
        gates
        and gates[0].get("head_sha") == commit
        and gates[0].get("run_id") == run_id
        and gates[0].get("status") == "completed"
        and gates[0].get("conclusion") == "success"
    )


def _read_page(
    gh: str, endpoint: str, collection: str, filters: dict[str, str]
) -> list[dict[str, object]]:
    arguments = [gh, "api", "--method", "GET", endpoint]
    for key, value in {**filters, "per_page": str(MAX_HISTORY)}.items():
        arguments.extend(["-f", f"{key}={value}"])
    response = subprocess.run(  # noqa: S603
        arguments, check=True, capture_output=True, text=True
    )
    page = json.loads(response.stdout)
    if (
        not isinstance(page, dict)
        or type(page.get("total_count")) is not int
        or not 0 <= page["total_count"] < MAX_HISTORY
    ):
        raise ValueError("nightly history is incomplete; manual inspection is required")
    items = page.get(collection)
    if (
        not isinstance(items, list)
        or len(items) != page["total_count"]
        or any(not isinstance(item, dict) for item in items)
    ):
        raise ValueError("nightly history count does not match its complete page")
    return items


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
    runs = _read_page(
        gh,
        f"repos/{repository}/actions/workflows/full-ci.yml/runs",
        "workflow_runs",
        {"head_sha": commit, "branch": "main"},
    )
    for run in runs:
        # Do not trust this derived field if it appears in the API response.
        run["full_gate_passed"] = False
        if (
            run.get("id") != run_id
            and run.get("head_sha") == commit
            and run.get("head_branch") == "main"
            and run.get("event") in {"schedule", "workflow_dispatch"}
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
        ):
            candidate_id = run["id"]
            if type(candidate_id) is not int or candidate_id < 1:
                raise ValueError("invalid full-acceptance run identity")
            jobs = _read_page(
                gh,
                f"repos/{repository}/actions/runs/{candidate_id}/jobs",
                "jobs",
                {"filter": "latest"},
            )
            run["full_gate_passed"] = completed_full_gate(jobs, commit, candidate_id)
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
