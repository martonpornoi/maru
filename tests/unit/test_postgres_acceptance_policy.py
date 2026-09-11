from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
from coverage import Coverage
from coverage.results import should_fail_under
from scripts import nightly_ci
from scripts import run_postgres_acceptance as runner
from scripts.ci_changes import ChangedFile, classify_changes
from scripts.ci_test_policy import (
    MANIFEST,
    RECOVERY_SMOKE,
    ROOT,
    TIMINGS,
    HistoricalFile,
    affected_migration_owners,
    build_groups,
    case_group,
    load_history_inventory,
    partition_groups,
    select_groups,
)
from scripts.ci_test_policy import TestGroup as WorkGroup
from scripts.nightly_ci import completed_full_gate, nightly_decision
from scripts.run_postgres_acceptance import CollectionBoundary, resolve_scope


def _change(path: str, status: str = "M") -> ChangedFile:
    return ChangedFile(PurePosixPath(path), status)


@pytest.mark.parametrize(
    ("path", "history"),
    [
        ("src/maru/programme/commands.py", "current"),
        ("frontends/staff-console/src/main.tsx", "current"),
        ("src/maru/programme/models.py", "affected"),
        ("src/maru/programme/migrations/0009_new.py", "affected"),
        ("tests/integration/test_programme_hosts.py", "affected"),
        ("src/maru/authorization/policy.py", "all"),
        ("src/maru/audit/services.py", "all"),
        ("src/maru/identity/commands.py", "all"),
        ("src/maru/settings/test.py", "all"),
        ("scripts/ci_test_policy.py", "all"),
        ("scripts/ci_historical_tests.json", "all"),
        (".github/workflows/_full-ci.yml", "all"),
        ("tests/support/migrations.py", "all"),
        ("tests/conftest.py", "all"),
        ("uv.lock", "all"),
        ("Dockerfile", "all"),
    ],
)
def test_code_changes_keep_current_postgres_and_select_reviewed_history(
    path: str, history: str
) -> None:
    plan = classify_changes((_change(path),))
    assert plan.integration == "full"
    assert plan.history == history
    assert plan.github_outputs()["history"] == history


def test_docs_remain_database_free_and_deletions_cannot_narrow_history() -> None:
    assert classify_changes((_change("docs/product/vision.md"),)).integration == "none"
    assert (
        classify_changes((_change("tests/integration/test_old.py", "D"),)).history
        == "all"
    )


def _synthetic_inventory(root: Path) -> tuple[Path, str]:
    file = "tests/integration/test_example.py"
    path = root / file
    path.parent.mkdir(parents=True)
    path.write_text(
        "def test_old(): pass\ndef test_current(): pass\n", encoding="utf-8"
    )
    (root / "src/maru/example/migrations").mkdir(parents=True)
    manifest = root / MANIFEST
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                file: {
                    "owners": ["example"],
                    "tests": ["test_old"],
                    "shared_baseline": False,
                }
            }
        ),
        encoding="utf-8",
    )
    (root / TIMINGS).write_text(
        json.dumps({file + "::current": 1, file + "::test_old": 9}), encoding="utf-8"
    )
    return manifest, file


@pytest.mark.parametrize(
    "bad", [[], None, True, ["test_old", "test_old"], ["test_missing"]]
)
def test_missing_duplicate_and_malformed_historical_names_fail(
    tmp_path: Path, bad: object
) -> None:
    manifest, file = _synthetic_inventory(tmp_path)
    value = json.loads(manifest.read_text())
    value[file]["tests"] = bad
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match=r"inventory|historical"):
        load_history_inventory(tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_file",
        "bad_path",
        "unknown_owner",
        "unknown_key",
        "bad_flag",
        "duplicate_json",
    ],
)
def test_inventory_fails_closed_on_unknown_boundaries(
    tmp_path: Path, mutation: str
) -> None:
    manifest, file = _synthetic_inventory(tmp_path)
    value = json.loads(manifest.read_text())
    if mutation == "missing_file":
        (tmp_path / file).unlink()
    elif mutation == "bad_path":
        value["../outside.py"] = value.pop(file)
    elif mutation == "unknown_owner":
        value[file]["owners"] = ["unknown"]
    elif mutation == "unknown_key":
        value[file]["exclude_everything"] = True
    elif mutation == "bad_flag":
        value[file]["shared_baseline"] = "false"
    else:
        manifest.write_text('{"same": {}, "same": {}}')
        with pytest.raises(ValueError, match="duplicate"):
            load_history_inventory(tmp_path)
        return
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match=r"historical|migration|inventory|baseline"):
        load_history_inventory(tmp_path)


def test_shared_fixture_cannot_be_silently_split_or_hide_current_cases(
    tmp_path: Path,
) -> None:
    manifest, file = _synthetic_inventory(tmp_path)
    with (tmp_path / file).open("a") as output:
        output.write("\n@pytest.fixture(scope='module')\ndef history(): pass\n")
    with pytest.raises(ValueError, match="cannot be split"):
        load_history_inventory(tmp_path)
    value = json.loads(manifest.read_text())
    value[file]["shared_baseline"] = True
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="unclassified"):
        load_history_inventory(tmp_path)
    value[file]["tests"].append("test_current")
    manifest.write_text(json.dumps(value))
    assert load_history_inventory(tmp_path)[file].shared_baseline


@pytest.mark.parametrize("value", [True, -1, 0, float("nan"), float("inf"), "9"])
def test_invalid_cost_evidence_is_rejected(tmp_path: Path, value: object) -> None:
    _manifest, file = _synthetic_inventory(tmp_path)
    (tmp_path / TIMINGS).write_text(json.dumps({file + "::current": value}))
    with pytest.raises(ValueError, match="positive finite"):
        build_groups(tmp_path)


def test_new_unlisted_test_defaults_to_current_and_stale_costs_fail(
    tmp_path: Path,
) -> None:
    _manifest, file = _synthetic_inventory(tmp_path)
    with (tmp_path / file).open("a") as output:
        output.write("def test_new(): pass\n")
    inventory = load_history_inventory(tmp_path)
    assert case_group(file, "test_new", inventory) == file + "::current"
    (tmp_path / TIMINGS).write_text(json.dumps({"stale": 10}))
    with pytest.raises(ValueError, match="stale"):
        build_groups(tmp_path)


def test_repository_current_and_history_partitions_are_complete_and_disjoint() -> None:
    inventory = load_history_inventory()
    groups = build_groups()
    current = select_groups(groups, inventory, "current")
    complete = select_groups(groups, inventory, "all")
    assert complete == tuple(sorted(groups, key=lambda group: group.key))
    assert current
    assert all(not group.historical for group in current)
    assert {group.file for group in groups} == {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests/integration").glob("test_*.py")
    }
    for count in (8, 16):
        partition = partition_groups(complete, count)
        assert partition == partition_groups(tuple(reversed(complete)), count)
        assert Counter(group.key for shard in partition for group in shard) == Counter(
            group.key for group in complete
        )
    shared = "tests/integration/test_registration_profile_extension_value_history.py"
    assert len([group for group in groups if group.file == shared]) == 1
    mixed = "tests/integration/test_authority_provenance_migration_fences.py"
    assert mixed + "::current" in {group.key for group in current}
    assert RECOVERY_SMOKE not in {group.key for group in current}


def test_affected_selection_adds_real_recovery_and_directly_changed_history() -> None:
    inventory = load_history_inventory()
    groups = build_groups()
    changed = "tests/integration/test_invitation_token_digest_key_migration.py"
    selected = select_groups(
        groups, inventory, "affected", frozenset({"programme"}), frozenset({changed})
    )
    keys = {group.key for group in selected}
    assert RECOVERY_SMOKE in keys
    assert all(
        group.key in keys
        for group in groups
        if not group.historical or group.file == changed
    )
    assert all(
        group.key in keys
        for group in groups
        if group.historical and "programme" in inventory[group.file].owners
    )
    assert (
        "tests/integration/test_registration_profile_audience_migration.py::test_profile_audience_backfill_and_compatible_reverse_are_exact"
        not in keys
    )
    with pytest.raises(ValueError, match="recovery"):
        select_groups(
            [group for group in groups if group.key != RECOVERY_SMOKE],
            inventory,
            "affected",
            frozenset({"programme"}),
        )
    assert select_groups(groups, inventory, "affected") == select_groups(
        groups, inventory, "current"
    )


def test_real_graph_resolves_dependents_and_refuses_unknown_or_deleted() -> None:
    owners = affected_migration_owners((_change("src/maru/programme/models.py"),))
    assert {"programme", "scheduling", "venues"} <= owners
    for change in (
        _change("src/maru/programme/migrations/0000_missing.py"),
        _change("src/maru/programme/models.py", "D"),
    ):
        with pytest.raises(ValueError, match=r"migration|schema"):
            affected_migration_owners((change,))


def test_new_owner_leaf_cannot_hide_consumers_of_an_older_model_migration(monkeypatch):
    """Model changes retain older consumers; an exact new migration stays precise."""
    earlier = ("programme", "0001_initial")
    newer = ("programme", "0002_new_feature")
    consumer = ("scheduling", "0001_initial")
    graph = SimpleNamespace(
        nodes={earlier, newer, consumer},
        backwards_plan=lambda node: (
            [earlier, newer, consumer] if node == earlier else [node]
        ),
    )
    monkeypatch.setattr(
        "django.db.migrations.loader.MigrationLoader",
        lambda _: SimpleNamespace(graph=graph),
    )
    assert affected_migration_owners(
        (_change("src/maru/programme/models.py"),)
    ) == frozenset({"programme", "scheduling"})
    assert affected_migration_owners(
        (_change("src/maru/programme/migrations/0002_new_feature.py"),)
    ) == frozenset({"programme"})


_NATIVE_SCHEDULING_RECOVERY_OWNERS = frozenset(
    {
        "applications",
        "audit",
        "authorization",
        "events",
        "identity",
        "programme",
        "scheduling",
        "venues",
        "workforce",
    }
)


@pytest.mark.parametrize("owner", sorted(_NATIVE_SCHEDULING_RECOVERY_OWNERS))
def test_joint_scheduling_history_follows_each_native_owner_graph(owner: str) -> None:
    inventory = load_history_inventory()
    groups = build_groups()
    owners = affected_migration_owners((_change(f"src/maru/{owner}/models.py"),))
    assert "scheduling" in owners
    selected = select_groups(groups, inventory, "affected", owners)
    keys = {group.key for group in selected}
    history = "tests/integration/test_scheduling_integrity_migrations.py"
    assert inventory[history].owners == _NATIVE_SCHEDULING_RECOVERY_OWNERS
    assert RECOVERY_SMOKE in keys
    assert all(
        case_group(history, function, inventory) in keys
        for function in inventory[history].tests
    )
    assert all(group.key in keys for group in groups if not group.historical)


def test_current_scheduling_safety_is_not_deferred_with_rollback_history() -> None:
    inventory = load_history_inventory()
    groups = build_groups()
    current = select_groups(groups, inventory, "current")
    keys = {group.key for group in current}
    for file in (
        "test_programme_scheduling_source.py",
        "test_scheduling_database_guards.py",
        "test_scheduling_readiness.py",
        "test_scheduling_reservations.py",
        "test_scheduling_venue_continuity.py",
        "test_venue_scheduling_binding_guards.py",
        "test_venue_scheduling_source.py",
    ):
        assert f"tests/integration/{file}::current" in keys
    historical_file = "tests/integration/test_scheduling_integrity_migrations.py"
    assert not inventory[historical_file].shared_baseline
    assert inventory[historical_file].tests == frozenset(
        {
            "test_empty_joint_graph_reverses_and_recovers_with_normal_migrations",
            "test_planning_history_fences_both_owners_before_any_guard_is_removed",
        }
    )
    history = [group for group in groups if group.file == historical_file]
    assert len(history) == 2
    assert all(group.historical and group.key not in keys for group in history)


@pytest.mark.parametrize("count", [0, -1, 2])
def test_invalid_partitions_fail(count: int) -> None:
    with pytest.raises(ValueError, match="shard count"):
        partition_groups((WorkGroup("key", "file", historical=False, weight=1),), count)


def test_duplicate_groups_and_invalid_scope_fail() -> None:
    group = WorkGroup("key", "file", historical=False, weight=1)
    with pytest.raises(ValueError, match="duplicate"):
        partition_groups((group, group), 1)
    with pytest.raises(ValueError, match="duration"):
        partition_groups((replace(group, weight=float("inf")),), 1)
    with pytest.raises(ValueError, match="scope"):
        select_groups((group,), {}, "ignore")
    for scope in ("auto", "affected"):
        with pytest.raises(ValueError, match="base"):
            resolve_scope(scope, None)


def test_collection_preserves_all_variants_and_refuses_missing_groups(
    tmp_path: Path,
) -> None:
    file = "tests/integration/test_example.py"
    inventory = {
        file: HistoricalFile(
            frozenset({"example"}), frozenset({"test_old"}), shared_baseline=False
        )
    }
    groups = (
        WorkGroup(file + "::current", file, historical=False, weight=1),
        WorkGroup(file + "::test_old", file, historical=True, weight=9),
    )
    items = [
        SimpleNamespace(
            path=ROOT / file,
            originalname=name,
            name=name + suffix,
            nodeid=file + "::" + name + suffix,
        )
        for name, suffix in (
            ("test_old", "[uuid-a]"),
            ("test_old", "[uuid-b]"),
            ("test_now", ""),
        )
    ]
    removed = []

    def record_deselected(*, items: list[object]) -> None:
        removed.extend(items)

    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=record_deselected))
    boundary = CollectionBoundary(
        inventory, groups, groups[1:], tmp_path / "selection.json"
    )
    boundary.pytest_collection_modifyitems(config, items)
    assert len(items) == 2
    assert len(removed) == 1
    assert json.loads((tmp_path / "selection.json").read_text())["selected"] == 2
    with pytest.raises(pytest.UsageError, match="mismatch"):
        boundary.pytest_collection_modifyitems(config, items)


@pytest.mark.parametrize(
    ("passed", "skipped", "exitstatus", "expected"),
    [(1, False, 0, 1), (2, True, 0, 1), (2, False, 0, 0), (2, False, 2, 2)],
)
def test_incomplete_or_skipped_execution_cannot_pass(
    passed: int, skipped: bool, exitstatus: int, expected: int
) -> None:
    boundary = CollectionBoundary({}, (), (), None)
    boundary.selected_count = 2
    boundary.passed_count = passed
    boundary.skipped = skipped
    session = SimpleNamespace(
        config=SimpleNamespace(option=SimpleNamespace(collectonly=False)),
        exitstatus=exitstatus,
    )
    boundary.pytest_sessionfinish(session, exitstatus)
    assert session.exitstatus == expected


def _run(**updates: object) -> dict[str, object]:
    return {
        "id": 1,
        "head_sha": "a" * 40,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "event": "schedule",
        "full_gate_passed": True,
        **updates,
    }


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([], "run"),
        ([_run()], "passed"),
        ([_run(id=2)], "run"),
        ([_run(head_sha="b" * 40)], "run"),
        ([_run(head_branch="feature")], "run"),
        ([_run(event="pull_request")], "run"),
        ([_run(status="in_progress", conclusion=None)], "active"),
        ([_run(conclusion="failure")], "blocked"),
        ([_run(conclusion="cancelled")], "blocked"),
        ([_run(conclusion="failure"), _run(id=3, event="workflow_dispatch")], "passed"),
    ],
)
def test_nightly_deduplicates_exact_main_without_retrying_failures(
    runs: list[dict[str, object]], expected: str
) -> None:
    assert nightly_decision(runs, "a" * 40, 2) == expected


def test_nightly_rejects_missing_metadata_and_invalid_revision() -> None:
    with pytest.raises(ValueError, match="metadata"):
        nightly_decision([{}], "a" * 40, 2)
    with pytest.raises(ValueError, match="exact commit"):
        nightly_decision([], "main", 2)


def test_selector_success_cannot_hide_failed_or_active_full_acceptance() -> None:
    skipped = _run(full_gate_passed=False)
    assert nightly_decision([skipped], "a" * 40, 3) == "blocked"
    assert (
        nightly_decision([skipped, _run(id=2, conclusion="failure")], "a" * 40, 3)
        == "blocked"
    )
    assert (
        nightly_decision(
            [skipped, _run(id=2, status="in_progress", conclusion=None)], "a" * 40, 3
        )
        == "active"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Select changed-revision nightly acceptance"},
        {"head_sha": "b" * 40},
        {"run_id": 2},
        {"status": "in_progress"},
        {"conclusion": "skipped"},
        {"conclusion": "failure"},
    ],
)
def test_nightly_full_gate_requires_exact_success(changes: dict[str, object]) -> None:
    gate = {
        "name": "Full acceptance / Full CI gate",
        "head_sha": "a" * 40,
        "run_id": 1,
        "status": "completed",
        "conclusion": "success",
    }
    assert completed_full_gate([gate], "a" * 40, 1)
    assert not completed_full_gate([{**gate, **changes}], "a" * 40, 1)
    assert not completed_full_gate([], "a" * 40, 1)
    with pytest.raises(ValueError, match="duplicate"):
        completed_full_gate([gate, gate], "a" * 40, 1)


@pytest.mark.parametrize("conclusion", ["success", "skipped", "failure"])
def test_nightly_reads_actual_job_evidence_before_deduplicating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, conclusion: str
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "synthetic/maru")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "2")
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(nightly_ci.shutil, "which", lambda _name: "gh")
    calls = []

    def read_api(arguments: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(arguments)
        assert arguments[:4] == ["gh", "api", "--method", "GET"]
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        if arguments[4].endswith("full-ci.yml/runs"):
            page = {"total_count": 1, "workflow_runs": [_run()]}
        else:
            assert arguments[4] == "repos/synthetic/maru/actions/runs/1/jobs"
            assert "filter=latest" in arguments
            page = {
                "total_count": 1,
                "jobs": [
                    {
                        "name": "Full acceptance / Full CI gate",
                        "head_sha": "a" * 40,
                        "run_id": 1,
                        "status": "completed",
                        "conclusion": conclusion,
                    }
                ],
            }
        return SimpleNamespace(stdout=json.dumps(page))

    monkeypatch.setattr(nightly_ci.subprocess, "run", read_api)
    assert nightly_ci.main() == (0 if conclusion == "success" else 1)
    assert len(calls) == 2
    assert output.read_text() == "run_full=false\n"


@pytest.mark.parametrize(
    "page",
    [
        [],
        {"total_count": 100, "jobs": []},
        {"total_count": -1, "jobs": []},
        {"total_count": 1, "jobs": []},
        {"total_count": 1, "jobs": [None]},
    ],
)
def test_nightly_refuses_incomplete_or_malformed_job_pages(
    monkeypatch: pytest.MonkeyPatch, page: object
) -> None:
    monkeypatch.setattr(
        nightly_ci.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(page)),
    )
    with pytest.raises(ValueError, match=r"incomplete|count"):
        nightly_ci._read_page(
            "gh", "repos/synthetic/maru/actions/runs/1/jobs", "jobs", {}
        )


def test_same_named_class_case_is_current_and_parameter_colons_do_not_split() -> None:
    file = "tests/integration/test_example.py"
    inventory = {
        file: HistoricalFile(
            frozenset({"example"}), frozenset({"test_old"}), shared_baseline=False
        )
    }
    groups = (
        WorkGroup(file + "::current", file, historical=False, weight=1),
        WorkGroup(file + "::test_old", file, historical=True, weight=9),
    )
    items = [
        SimpleNamespace(
            path=ROOT / file,
            originalname="test_old",
            name="test_old[a::b]",
            nodeid=file + "::test_old[a::b]",
        ),
        SimpleNamespace(
            path=ROOT / file,
            originalname="test_old",
            name="test_old",
            nodeid=file + "::TestCurrent::test_old",
        ),
    ]

    def record_deselected(*, items: list[object]) -> None:
        assert len(items) == 1

    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=record_deselected))
    boundary = CollectionBoundary(inventory, groups, groups[1:], None)
    boundary.pytest_collection_modifyitems(config, items)
    assert len(items) == 1
    assert items[0].name == "test_old[a::b]"


@pytest.mark.parametrize(("resolved", "count"), [("current", 8), ("all", 16)])
def test_hosted_plan_emits_resolved_scope_before_matrix_fanout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, resolved: str, count: int
) -> None:
    monkeypatch.setattr(
        runner, "resolve_scope", lambda *_args: (resolved, frozenset(), frozenset())
    )
    output = tmp_path / "outputs"
    assert (
        runner.main(
            ["--history", "affected", "--plan-only", "--github-output", str(output)]
        )
        == 0
    )
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values["history"] == resolved
    assert json.loads(values["matrix"]) == list(range(1, count + 1))
    assert int(values["shard_count"]) == count


@pytest.mark.parametrize("argument", ["-k", "--deselect=one", "--ignore=tests", "-n2"])
def test_acceptance_cli_refuses_filtered_or_shared_parallel_execution(
    argument: str,
) -> None:
    with pytest.raises(SystemExit, match="2"):
        runner.main(["--", argument])


def test_coverage_starts_before_runner_initializes_django(tmp_path: Path) -> None:
    coverage_file = tmp_path / ".coverage.startup"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "-m",
            "scripts.run_postgres_acceptance",
            "--history",
            "current",
            "--plan-only",
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "COVERAGE_FILE": str(coverage_file),
            "MARU_DATABASE_URL": "postgresql://maru:maru@127.0.0.1:1/no_database",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert "module-not-measured" not in result.stderr
    assert json.loads(result.stdout)["history"] == "current"
    measurement = Coverage(data_file=str(coverage_file))
    measurement.load()
    _file, statements, _excluded, missing, _formatted = measurement.analysis2(
        str(ROOT / "src/maru/programme/apps.py")
    )
    assert statements
    assert not missing


def test_coverage_gate_does_not_round_a_shortfall_to_whole_percent() -> None:
    measurement = Coverage(config_file=str(ROOT / "pyproject.toml"))
    threshold = measurement.get_option("report:fail_under")
    precision = measurement.get_option("report:precision")
    assert threshold == 90
    assert precision == 2
    assert should_fail_under(89.56, threshold, precision)
    assert not should_fail_under(90.01, threshold, precision)
