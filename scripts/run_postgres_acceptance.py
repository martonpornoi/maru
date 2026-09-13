"""Execute one validated risk-selected PostgreSQL shard with collection evidence."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from scripts.ci_changes import classify_changes, git_changes
from scripts.ci_test_budget import execution_plan
from scripts.ci_test_policy import (
    ROOT,
    HistoricalFile,
    TestGroup,
    affected_migration_owners,
    build_groups,
    case_group,
    load_history_inventory,
    partition_groups,
    select_groups,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


class CollectionBoundary:
    """Verify actual collection and retain only the exact assigned work groups.

    Parameters
    ----------
    inventory : dict[str, HistoricalFile]
        Validated historical function membership.
    groups : Sequence[TestGroup]
        Complete source-derived inventory, before risk selection.
    selected : Sequence[TestGroup]
        Unique groups assigned to this isolated shard.
    evidence : Path | None
        Optional JSON destination for diagnostic selection evidence.

    Attributes
    ----------
    selected_count : int
        Collected cases required to pass in this shard.
    passed_count : int
        Successful call reports observed during execution.
    skipped : bool
        Whether any required case skipped instead of being verified.
    """

    def __init__(
        self,
        inventory: dict[str, HistoricalFile],
        groups: Sequence[TestGroup],
        selected: Sequence[TestGroup],
        evidence: Path | None,
    ) -> None:
        self.inventory = inventory
        self.expected = {group.key for group in groups}
        self.selected = {group.key for group in selected}
        self.evidence = evidence
        self.selected_count = 0
        self.passed_count = 0
        self.skipped = False
        self.timing_path = evidence.with_suffix(".timings.jsonl") if evidence else None
        if self.timing_path is not None:
            self.timing_path.parent.mkdir(parents=True, exist_ok=True)
            with self.timing_path.open("x", encoding="utf-8") as stream:
                stream.write(
                    json.dumps({"event": "start", "unix_time": time.time()}) + "\n"
                )

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(
        self, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        """Match every collected case to one group before applying risk selection.

        Parameters
        ----------
        config : pytest.Config
            Active pytest configuration and diagnostic hooks.
        items : list[pytest.Item]
            Actual complete integration collection, filtered in place.

        Raises
        ------
        pytest.UsageError
            If source membership and actual collection disagree.
        """
        collected: dict[str, list[str]] = {}
        retained = []
        deselected = []
        for item in items:
            file = item.path.resolve().relative_to(ROOT).as_posix()
            function = getattr(item, "originalname", None) or item.name.split("[", 1)[0]
            # Only explicitly named top-level functions belong to historical groups.
            containers = item.nodeid.removesuffix("::" + item.name).split("::")[1:]
            function = "::".join([*containers, function])
            key = case_group(file, function, self.inventory)
            collected.setdefault(key, []).append(item.nodeid)
            (retained if key in self.selected else deselected).append(item)
        if set(collected) != self.expected or not self.selected <= set(collected):
            missing = sorted(self.expected - set(collected))
            extra = sorted(set(collected) - self.expected)
            raise pytest.UsageError(
                f"test inventory/collection mismatch: missing={missing}, extra={extra}"
            )
        if not retained or len({item.nodeid for item in items}) != len(items):
            raise pytest.UsageError(
                "empty selection or duplicate collected test identity"
            )
        self.selected_count = len(retained)
        if self.evidence is not None:
            self.evidence.parent.mkdir(parents=True, exist_ok=True)
            self.evidence.write_text(
                json.dumps(
                    {
                        "collected": len(items),
                        "selected": self.selected_count,
                        "groups": {
                            key: collected[key] for key in sorted(self.selected)
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        items[:] = retained
        config.hook.pytest_deselected(items=deselected)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Count successful case calls and reject skipped acceptance evidence.

        Parameters
        ----------
        report : pytest.TestReport
            One setup, call or teardown report.
        """
        if self.timing_path is not None:
            with self.timing_path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "event": "phase",
                            "nodeid": report.nodeid,
                            "phase": report.when,
                            "duration": report.duration,
                            "outcome": report.outcome,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
        if report.skipped:
            self.skipped = True
        if report.when == "call" and report.passed:
            self.passed_count += 1

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        """Refuse successful acceptance when selected tests did not all pass.

        Parameters
        ----------
        session : pytest.Session
            Session whose exit status can be made fail-closed.
        exitstatus : int
            Existing pytest result, never changed from failure to success.
        """
        if (
            not session.config.option.collectonly
            and exitstatus == 0
            and (self.skipped or self.passed_count != self.selected_count)
        ):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        if self.timing_path is not None:
            with self.timing_path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "event": "finish",
                            "unix_time": time.time(),
                            "selected": self.selected_count,
                            "passed": self.passed_count,
                            "exitstatus": int(session.exitstatus),
                        }
                    )
                    + "\n"
                )


def resolve_scope(
    history: str, base: str | None
) -> tuple[str, frozenset[str], frozenset[str]]:
    """Resolve automatic local scope and the exact affected migration closure.

    Parameters
    ----------
    history : str
        Requested diagnostic scope or ``auto`` for pre-review evidence.
    base : str | None
        Exact comparison base required by automatic and affected modes.

    Returns
    -------
    tuple[str, frozenset[str], frozenset[str]]
        Resolved scope, affected owners and directly changed paths.

    Raises
    ------
    ValueError
        If a diff-dependent mode has no explicit comparison base.
    """
    changes = ()
    if history in {"auto", "affected"}:
        if not base:
            raise ValueError(
                "automatic or affected acceptance requires an explicit base"
            )
        changes = git_changes(base, "HEAD")
    if history == "auto":
        history = classify_changes(changes).history
    owners = frozenset()
    if history == "affected":
        try:
            owners = affected_migration_owners(changes)
        except ValueError:
            history = "all"
    return history, owners, frozenset(change.path.as_posix() for change in changes)


def _resolve_plan(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    required: Sequence[TestGroup],
    history: str,
) -> dict[str, object]:
    plan = execution_plan(required, history=history, base=args.base)
    count = len(plan["shards"])
    if args.shard_count is not None and args.shard_count != count:
        parser.error("shard count does not match the independently budgeted plan")
    args.shard_count = count
    if args.plan_file is not None:
        supplied = json.loads(args.plan_file.read_text(encoding="utf-8-sig"))
        if supplied != plan:
            parser.error("frozen manifest differs from current source-derived plan")
    if args.expected_plan is not None and args.expected_plan != plan["fingerprint"]:
        parser.error("execution plan fingerprint differs from the preflight")
    if args.write_plan is not None:
        if not args.plan_only:
            parser.error("writing a manifest requires planning without execution")
        args.write_plan.parent.mkdir(parents=True, exist_ok=True)
        args.write_plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    """Validate complete coverage of work groups and execute one serial shard.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Command-line arguments; additional pytest flags cannot narrow selection.

    Returns
    -------
    int
        Pytest's exit code, or a nonzero fail-closed planner result.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history", choices=["auto", "current", "affected", "all"], default="all"
    )
    parser.add_argument("--base")
    parser.add_argument("--shard-index", type=int, default=1)
    parser.add_argument("--shard-count", type=int)
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--write-plan", type=Path)
    parser.add_argument("--expected-plan")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    args, pytest_args = parser.parse_known_args(argv)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    forbidden = (
        "-k",
        "-m",
        "-n",
        "--deselect",
        "--ignore",
        "--lf",
        "--last-failed",
        "--numprocesses",
        "--pyargs",
    )
    if any(arg.startswith(forbidden) for arg in pytest_args):
        parser.error(
            "acceptance arguments cannot filter cases or share a parallel database"
        )
    import os  # noqa: PLC0415

    import django  # noqa: PLC0415

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maru.settings.test")
    django.setup()
    history, owners, changed = resolve_scope(args.history, args.base)
    if args.github_output is not None and not args.plan_only:
        parser.error("workflow outputs require planning without test execution")
    inventory = load_history_inventory()
    groups = build_groups()
    required = select_groups(groups, inventory, history, owners, changed)
    plan = _resolve_plan(args, parser, required, history)
    shards = partition_groups(required, args.shard_count)
    if not 1 <= args.shard_index <= args.shard_count:
        parser.error("shard index is outside the requested partition")
    selected = shards[args.shard_index - 1]
    summary = {
        "history": history,
        "owners": sorted(owners),
        "base": args.base,
        "required_groups": len(required),
        "historical_groups": sum(group.historical for group in required),
        "estimated_seconds": [
            round(sum(group.weight for group in shard), 3) for shard in shards
        ],
        "shard": args.shard_index,
        "shards": args.shard_count,
        "plan_fingerprint": plan["fingerprint"],
        "predicted_seconds": plan["estimated_seconds"],
        "groups": [group.key for group in selected],
    }
    print(json.dumps(summary, sort_keys=True), flush=True)
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"history={history}\nshard_count={args.shard_count}\n")
            output.write(f"plan_fingerprint={plan['fingerprint']}\n")
            output.write(f"matrix={json.dumps(list(range(1, args.shard_count + 1)))}\n")
    if args.plan_only:
        return 0
    boundary = CollectionBoundary(inventory, groups, selected, args.evidence)
    return int(
        pytest.main([str(ROOT / "tests/integration"), *pytest_args], plugins=[boundary])
    )


if __name__ == "__main__":
    raise SystemExit(main())
