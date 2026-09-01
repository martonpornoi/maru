from collections import Counter
from pathlib import Path

import pytest
from scripts import run_ci_test_shard
from scripts.run_ci_test_shard import (
    WeightedTestFile,
    discover_integration_tests,
    load_timing_weights,
    partition_test_files,
    validate_shard_inputs,
    weigh_test_files,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_TEST_DIRECTORY = REPOSITORY_ROOT / "tests" / "integration"


def _flatten(shards: tuple[tuple[Path, ...], ...]) -> tuple[Path, ...]:
    return tuple(path for shard in shards for path in shard)


def test_partition_is_deterministic_complete_and_non_overlapping() -> None:
    weighted_files = (
        WeightedTestFile(Path("tests/integration/test_alpha.py"), 10),
        WeightedTestFile(Path("tests/integration/test_bravo.py"), 8),
        WeightedTestFile(Path("tests/integration/test_charlie.py"), 6),
        WeightedTestFile(Path("tests/integration/test_delta.py"), 4),
        WeightedTestFile(Path("tests/integration/test_echo.py"), 2),
    )

    shards = partition_test_files(weighted_files, shard_count=3)
    reversed_shards = partition_test_files(tuple(reversed(weighted_files)), 3)

    assert shards == reversed_shards
    assigned = _flatten(shards)
    expected_paths = tuple(test_file.path for test_file in weighted_files)
    assert Counter(assigned) == Counter(expected_paths)
    assert all(count == 1 for count in Counter(assigned).values())
    assert shards == (
        (Path("tests/integration/test_alpha.py"),),
        (
            Path("tests/integration/test_bravo.py"),
            Path("tests/integration/test_echo.py"),
        ),
        (
            Path("tests/integration/test_charlie.py"),
            Path("tests/integration/test_delta.py"),
        ),
    )


@pytest.mark.parametrize(
    ("shard_index", "shard_count", "test_count", "message"),
    [
        (1, 0, 3, "shard count must be at least 1"),
        (0, 2, 3, "shard index must be between 1 and 2"),
        (3, 2, 3, "shard index must be between 1 and 2"),
        (1, 4, 3, "shard count cannot exceed"),
        (1, 1, 0, "no integration test files"),
    ],
)
def test_invalid_shard_inputs_are_rejected(
    shard_index: int, shard_count: int, test_count: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_shard_inputs(
            shard_index=shard_index,
            shard_count=shard_count,
            test_count=test_count,
        )


def test_duplicate_files_are_rejected() -> None:
    duplicate = WeightedTestFile(Path("tests/integration/test_duplicate.py"), 1)

    with pytest.raises(ValueError, match="unique"):
        partition_test_files((duplicate, duplicate), shard_count=1)


def test_discovery_matches_and_partitions_the_current_repository_inventory() -> None:
    discovered = discover_integration_tests(INTEGRATION_TEST_DIRECTORY)
    expected = tuple(
        sorted(
            (
                path
                for path in INTEGRATION_TEST_DIRECTORY.glob("test_*.py")
                if path.is_file()
            ),
            key=lambda path: path.as_posix(),
        )
    )

    assert discovered
    assert discovered == expected
    weighted_files = weigh_test_files(discovered)
    assert all(test_file.weight > 0 for test_file in weighted_files)
    assigned = _flatten(partition_test_files(weighted_files, shard_count=8))
    assert Counter(assigned) == Counter(discovered)
    assert all(count == 1 for count in Counter(assigned).values())


def test_checked_in_timings_exactly_match_the_current_repository_inventory() -> None:
    discovered = discover_integration_tests(INTEGRATION_TEST_DIRECTORY)
    expected_paths = {
        path.relative_to(REPOSITORY_ROOT).as_posix() for path in discovered
    }

    assert set(load_timing_weights(run_ci_test_shard.TIMING_FILE)) == expected_paths


def test_timing_weights_use_milliseconds_and_reject_invalid_maps(
    tmp_path: Path,
) -> None:
    timing_file = tmp_path / "timings.json"
    timing_file.write_text(
        '{"tests/integration/test_alpha.py": 1.234}\n',
        encoding="utf-8",
    )

    assert load_timing_weights(timing_file) == {"tests/integration/test_alpha.py": 1234}
    assert load_timing_weights(tmp_path / "missing.json") == {}

    timing_file.write_text("[]\n", encoding="utf-8")
    with pytest.raises(TypeError, match="JSON object"):
        load_timing_weights(timing_file)


def test_main_invokes_pytest_in_process_with_only_the_selected_whole_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    integration_directory = tmp_path / "tests" / "integration"
    integration_directory.mkdir(parents=True)
    large_file = integration_directory / "test_large.py"
    small_file = integration_directory / "test_small.py"
    large_file.write_text("x" * 100, encoding="utf-8")
    small_file.write_text("x", encoding="utf-8")
    received_arguments: list[str] = []

    def fake_pytest_main(arguments: list[str]) -> int:
        received_arguments.extend(arguments)
        return 7

    monkeypatch.setattr(
        run_ci_test_shard,
        "INTEGRATION_TEST_DIRECTORY",
        integration_directory,
    )
    monkeypatch.setattr(run_ci_test_shard, "invoke_pytest", fake_pytest_main)

    result = run_ci_test_shard.main(
        [
            "--shard-index",
            "2",
            "--shard-count",
            "2",
            "--",
            "-q",
            "-k",
            "smoke",
        ]
    )

    assert result == 7
    assert received_arguments == ["-q", "-k", "smoke", str(small_file)]
