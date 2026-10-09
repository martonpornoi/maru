"""Budget growth, immutable assignment and incremental timing safeguards."""

import json
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import pytest
from scripts import ci_test_budget as budget
from scripts import run_postgres_acceptance as runner
from scripts.ci_test_policy import ROOT, HistoricalFile
from scripts.ci_test_policy import TestGroup as Group


def groups(count, cost=500):
    return tuple(
        Group(f"test-{index}", f"test-{index}.py", historical=True, weight=cost)
        for index in range(count)
    )


def test_growth_adds_shards_without_changing_tests_or_database_concurrency():
    small = groups(24)
    large = groups(100)
    before = budget.budget_partition(small)
    after = budget.budget_partition(large)
    assert len(after) > len(before)
    assert budget.MAX_WORKERS == 8
    assert all(budget.predicted_seconds(bucket) <= 3600 for bucket in after)
    assert Counter(group.key for bucket in after for group in bucket) == Counter(
        group.key for group in large
    )
    assert after == budget.budget_partition(tuple(reversed(large)))


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_costs_fail_before_execution(value):
    with pytest.raises(ValueError, match="duration"):
        budget.budget_partition((replace(groups(1)[0], weight=value),))


def test_indivisible_or_total_over_budget_cannot_be_hidden_by_more_shards():
    with pytest.raises(ValueError, match="indivisible"):
        budget.budget_partition(groups(1, 2001))
    with pytest.raises(ValueError, match="capacity"):
        budget.budget_partition(groups(129, 2000))
    with pytest.raises(ValueError, match="empty"):
        budget.budget_partition(())
    assert len(budget.budget_partition(groups(128, 2000))) == 128
    assert len(budget.budget_partition(groups(65, 2000))) == 65
    assert budget.MAX_WORKERS == 8
    assert budget.TARGET_SECONDS == 3600
    assert budget.MEASURED_CEILING_SECONDS == 5400


@pytest.mark.parametrize(
    ("seconds", "allowed"),
    [
        (1, True),
        (3200, True),
        (3200.01, False),
        (0, False),
        (-1, False),
        (True, False),
        (float("nan"), False),
        (float("inf"), False),
    ],
)
def test_local_measured_headroom_keeps_thirty_minutes_beyond_slowdown(seconds, allowed):
    assert budget.measured_headroom(seconds) is allowed


def test_source_fingerprint_is_cross_platform_but_detects_code_and_policy_changes(
    tmp_path,
):
    for directory in ("src", "tests/integration", "tests/support", "scripts"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    for file in ("tests/conftest.py", "pyproject.toml", "uv.lock", "src/example.py"):
        (tmp_path / file).write_bytes(b"a\r\nb\r\n")
    windows = budget.source_fingerprint(tmp_path)
    (tmp_path / "src/example.py").write_bytes(b"a\nb\n")
    assert budget.source_fingerprint(tmp_path) == windows
    (tmp_path / "src/example.py").write_text("changed")
    assert budget.source_fingerprint(tmp_path) != windows
    previous = budget.source_fingerprint(tmp_path)
    (tmp_path / "scripts/certify.ps1").write_text("changed harness")
    assert budget.source_fingerprint(tmp_path) != previous
    previous = budget.source_fingerprint(tmp_path)
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/_full-ci.yml").write_text("changed workflow")
    assert budget.source_fingerprint(tmp_path) != previous


def test_manifest_detects_mutation_and_cli_cannot_force_a_different_partition(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(budget, "source_fingerprint", lambda _: "a" * 64)
    selected = groups(12)
    first = budget.execution_plan(selected, history="all", base="b" * 40)
    assert first == budget.execution_plan(
        tuple(reversed(selected)), history="all", base="b" * 40
    )
    assert first != budget.execution_plan(selected, history="current", base="b" * 40)
    parser = runner.argparse.ArgumentParser()
    manifest = tmp_path / "plan.json"
    manifest.write_text(json.dumps(first))
    args = SimpleNamespace(
        base="b" * 40,
        shard_count=None,
        plan_file=manifest,
        expected_plan=first["fingerprint"],
        write_plan=None,
        plan_only=True,
    )
    assert runner._resolve_plan(args, parser, selected, "all") == first
    args.shard_count = 1
    with pytest.raises(SystemExit):
        runner._resolve_plan(args, parser, selected, "all")
    args.shard_count = None
    first["shards"][0].pop()
    manifest.write_text(json.dumps(first))
    with pytest.raises(SystemExit):
        runner._resolve_plan(args, parser, selected, "all")


def test_incremental_phases_survive_without_a_successful_final_report(tmp_path):
    evidence = tmp_path / "selection.json"
    boundary = runner.CollectionBoundary({}, (), (), evidence)
    boundary.pytest_runtest_logreport(
        SimpleNamespace(
            nodeid="tests/integration/test_x.py::test_x[a::b]",
            when="setup",
            duration=1.5,
            outcome="passed",
            skipped=False,
            passed=True,
        )
    )
    records = [
        json.loads(line)
        for line in evidence.with_suffix(".timings.jsonl").read_text().splitlines()
    ]
    assert [record["event"] for record in records] == ["start", "phase"]
    assert records[1]["duration"] == 1.5
    assert not evidence.exists()
    with pytest.raises(FileExistsError):
        runner.CollectionBoundary({}, (), (), evidence)


def test_historical_density_is_bounded_even_when_cost_estimates_are_small():
    selected = groups(33, 1) + tuple(
        replace(group, key="current-" + group.key, historical=False, weight=300)
        for group in groups(20)
    )
    shards = budget.budget_partition(selected)
    assert budget.MAX_HISTORICAL_GROUPS_PER_SHARD == 2
    assert all(sum(group.historical for group in shard) <= 2 for shard in shards)
    assert Counter(group.key for shard in shards for group in shard) == Counter(
        group.key for group in selected
    )
    assert shards == budget.budget_partition(tuple(reversed(selected)))
    assert all(shards)
    assert all(budget.predicted_seconds(shard) <= 3600 for shard in shards)


def test_historical_density_cannot_exceed_total_bounded_shard_capacity():
    with pytest.raises(ValueError, match="capacity"):
        budget.budget_partition(groups(257, 1))
    assert len(budget.budget_partition(groups(256, 1))) == 128
    assert budget.MAX_WORKERS == 8


def test_current_only_inventory_retains_the_existing_budgeted_assignments():
    selected = tuple(replace(group, historical=False) for group in groups(24))
    shards = budget.budget_partition(selected)
    assert shards == budget.partition_groups(selected, 8)


def test_historical_density_is_bound_into_the_frozen_manifest(monkeypatch):
    monkeypatch.setattr(budget, "source_fingerprint", lambda _: "a" * 64)
    selected = groups(4, 1)
    before = budget.execution_plan(selected, history="all", base="b" * 40)
    assert before["max_historical_groups_per_shard"] == 2
    monkeypatch.setattr(budget, "MAX_HISTORICAL_GROUPS_PER_SHARD", 1)
    after = budget.execution_plan(selected, history="all", base="b" * 40)
    assert before["shards"] == after["shards"]
    assert before["fingerprint"] != after["fingerprint"]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2"])
def test_invalid_historical_capacity_fails_before_execution(limit):
    with pytest.raises(ValueError, match="historical group capacity"):
        budget.partition_groups(groups(2), 2, max_historical_groups=limit)


def test_capacity_preserves_indivisible_shared_baselines_and_parameter_groups():
    shared = Group(
        "tests/integration/test_shared.py::history",
        "tests/integration/test_shared.py",
        historical=True,
        weight=400,
    )
    selected = (shared, *groups(5, 100))
    shards = budget.partition_groups(selected, 3, max_historical_groups=2)
    assert sum(group is shared for shard in shards for group in shard) == 1
    assert Counter(group.key for shard in shards for group in shard) == Counter(
        group.key for group in selected
    )
    with pytest.raises(ValueError, match="historical group capacity"):
        budget.partition_groups(selected, 2, max_historical_groups=2)


def test_main_executes_every_exact_density_constrained_manifest_assignment(
    monkeypatch, tmp_path, capsys
):
    history_file = "tests/integration/test_plan_history.py"
    functions = tuple(f"test_history_{index}" for index in range(17))
    inventory = {
        history_file: HistoricalFile(
            frozenset({"events"}), frozenset(functions), shared_baseline=False
        )
    }
    required = tuple(
        Group(f"{history_file}::{function}", history_file, historical=True, weight=1)
        for function in functions
    ) + tuple(
        Group(
            f"tests/integration/test_plan_current_{index}.py::current",
            f"tests/integration/test_plan_current_{index}.py",
            historical=False,
            weight=300,
        )
        for index in range(4)
    )
    monkeypatch.setattr(budget, "source_fingerprint", lambda _: "a" * 64)
    monkeypatch.setattr(runner, "load_history_inventory", lambda: inventory)
    monkeypatch.setattr(runner, "build_groups", lambda: required)
    plan = budget.execution_plan(required, history="all", base=None)
    unconstrained = budget.partition_groups(required, len(plan["shards"]))
    assert [[group.key for group in shard] for shard in unconstrained] != plan["shards"]
    assert any(sum(group.historical for group in shard) > 2 for shard in unconstrained)
    manifest = tmp_path / "plan.json"
    manifest.write_text(json.dumps(plan), encoding="utf-8")

    # All shards still collect the complete inventory, including both variants.
    complete_items = []
    for group in required:
        function = group.key.split("::", 1)[1] if group.historical else "test_current"
        variants = ("[first]", "[second]") if group == required[0] else ("",)
        for variant in variants:
            name = function + variant
            complete_items.append(
                SimpleNamespace(
                    path=ROOT / group.file,
                    originalname=function,
                    name=name,
                    nodeid=f"{group.file}::{name}",
                )
            )
    selected_cases = []
    selected_groups = []

    def execute_collection(arguments, *, plugins):
        assert arguments == [str(ROOT / "tests/integration"), "--strict-markers"]
        assert len(plugins) == 1
        boundary = plugins[0]
        assert boundary.expected == {group.key for group in required}
        items = list(complete_items)
        deselected = []
        config = SimpleNamespace(
            hook=SimpleNamespace(
                pytest_deselected=lambda *, items: deselected.extend(items)
            )
        )
        boundary.pytest_collection_modifyitems(config, items)
        assert boundary.selected_count == len(items)
        assert len(items) + len(deselected) == len(complete_items)
        selected_cases.extend(item.nodeid for item in items)
        selected_groups.extend(boundary.selected)
        assert boundary.selected == set(plan["shards"][shard_index - 1])
        return 0

    monkeypatch.setattr(runner.pytest, "main", execute_collection)
    for shard_index, assignment in enumerate(plan["shards"], 1):
        evidence = tmp_path / f"selection-{shard_index}.json"
        assert (
            runner.main(
                [
                    "--history",
                    "all",
                    "--shard-index",
                    str(shard_index),
                    "--shard-count",
                    str(len(plan["shards"])),
                    "--plan-file",
                    str(manifest),
                    "--expected-plan",
                    plan["fingerprint"],
                    "--evidence",
                    str(evidence),
                    "--",
                    "--strict-markers",
                ]
            )
            == 0
        )
        summary = json.loads(capsys.readouterr().out)
        selection = json.loads(evidence.read_text(encoding="utf-8"))
        assert summary["groups"] == assignment
        assert sorted(selection["groups"]) == sorted(assignment)
        assert selection["collected"] == len(complete_items)
        assert summary["plan_fingerprint"] == plan["fingerprint"]
        assert summary["predicted_seconds"] == plan["estimated_seconds"]
        weights = {group.key: group.weight for group in required}
        assert summary["estimated_seconds"] == [
            round(sum(weights[key] for key in shard), 3) for shard in plan["shards"]
        ]
        assert sum(key.startswith(history_file + "::") for key in assignment) <= 2
    assert Counter(selected_groups) == Counter(group.key for group in required)
    assert Counter(selected_cases) == Counter(item.nodeid for item in complete_items)
