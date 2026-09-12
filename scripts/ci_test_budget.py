"""Deterministic runtime budgets and source-bound PostgreSQL execution plans."""

from __future__ import annotations

import hashlib
import json
import math
from typing import TYPE_CHECKING

from scripts.ci_test_policy import ROOT, partition_groups

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from scripts.ci_test_policy import TestGroup

MAX_WORKERS = 8
MAX_SHARDS = 64
TARGET_SECONDS = 3600
OVERHEAD_SECONDS = 600
SLOWDOWN_FACTOR = 1.5
MEASURED_CEILING_SECONDS = 5400


def budget_partition(
    groups: Sequence[TestGroup],
) -> tuple[tuple[TestGroup, ...], ...]:
    """Choose the smallest bounded partition with substantial timeout headroom.

    Parameters
    ----------
    groups : Sequence[TestGroup]
        Complete selected indivisible groups with positive measured costs.

    Returns
    -------
    tuple[tuple[TestGroup, ...], ...]
        Deterministic shards, each below the conservative one-hour target.

    Raises
    ------
    ValueError
        If costs, membership or an indivisible group's budget are invalid.
    """
    if not groups:
        raise ValueError("cannot budget an empty acceptance scope")
    # Validate even when a single large group makes every partition infeasible.
    partition_groups(groups, 1)
    oversized = [
        group.key
        for group in groups
        if group.weight * SLOWDOWN_FACTOR + OVERHEAD_SECONDS > TARGET_SECONDS
    ]
    if oversized:
        raise ValueError(f"indivisible groups exceed the runtime budget: {oversized}")
    minimum = min(MAX_WORKERS, len(groups))
    maximum = min(MAX_SHARDS, len(groups))
    for count in range(minimum, maximum + 1):
        shards = partition_groups(groups, count)
        if all(predicted_seconds(shard) <= TARGET_SECONDS for shard in shards):
            return shards
    raise ValueError(
        "selected scope exceeds the bounded shard capacity; remeasure or optimize"
    )


def predicted_seconds(groups: Sequence[TestGroup]) -> float:
    """Return a conservative cost including slowdown and job overhead.

    Parameters
    ----------
    groups : Sequence[TestGroup]
        Complete indivisible groups assigned to one job.

    Returns
    -------
    float
        Estimated seconds, not an execution or acceptance claim.
    """
    return round(
        sum(group.weight for group in groups) * SLOWDOWN_FACTOR + OVERHEAD_SECONDS, 3
    )


def measured_headroom(elapsed_seconds: float) -> bool:
    """Require measured local work to remain below a conservative hosted ceiling.

    Parameters
    ----------
    elapsed_seconds : float
        Observed subprocess duration including collection and database setup.

    Returns
    -------
    bool
        Whether a fifty-percent slowdown plus ten minutes stays within ninety
        minutes, retaining another thirty minutes before GitHub's kill limit.
    """
    return (
        type(elapsed_seconds) in {float, int}
        and math.isfinite(elapsed_seconds)
        and elapsed_seconds > 0
        and elapsed_seconds * SLOWDOWN_FACTOR + OVERHEAD_SECONDS
        <= MEASURED_CEILING_SECONDS
    )


def source_fingerprint(root: Path = ROOT) -> str:
    """Bind assignments to normalized code, test support and policy inputs.

    Parameters
    ----------
    root : Path, default=ROOT
        Candidate repository, normalized across Windows and Linux checkouts.

    Returns
    -------
    str
        SHA-256 digest; metadata only, never contributor authentication.
    """
    files = set()
    for directory in ("src", "tests/integration", "tests/support", "scripts"):
        files.update((root / directory).rglob("*.py"))
    files.update((root / "scripts").glob("ci_*.json"))
    files.update((root / "scripts").glob("*.ps1"))
    files.update((root / ".github/workflows").glob("*.yml"))
    files.update(
        root / name for name in ("tests/conftest.py", "pyproject.toml", "uv.lock")
    )
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def execution_plan(
    groups: Sequence[TestGroup], *, history: str, base: str | None, root: Path = ROOT
) -> dict[str, object]:
    """Build the complete independently reproducible budgeted shard manifest.

    Parameters
    ----------
    groups : Sequence[TestGroup]
        Exact policy-selected group inventory.
    history : str
        Already resolved current, affected or all historical scope.
    base : str | None
        Exact comparison base when required by the policy.
    root : Path, default=ROOT
        Repository whose source fingerprint binds the plan.

    Returns
    -------
    dict[str, object]
        Closed serializable manifest with every assignment and budget.
    """
    shards = budget_partition(groups)
    plan = {
        "schema_version": 1,
        "history": history,
        "base": base or None,
        "source_fingerprint": source_fingerprint(root),
        "max_workers": MAX_WORKERS,
        "target_seconds": TARGET_SECONDS,
        "overhead_seconds": OVERHEAD_SECONDS,
        "slowdown_factor": SLOWDOWN_FACTOR,
        "shards": [[group.key for group in shard] for shard in shards],
        "estimated_seconds": [predicted_seconds(shard) for shard in shards],
    }
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return {**plan, "fingerprint": digest}
