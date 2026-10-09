"""Budget growth, immutable assignment and incremental timing safeguards."""

import json
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import pytest
from scripts import ci_test_budget as budget
from scripts import run_postgres_acceptance as runner
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
