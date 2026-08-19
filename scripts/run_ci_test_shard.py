"""Run one deterministic, file-level shard of the integration test suite.

Integration test files stay whole because several Maru tests intentionally alter
database state.  Until measured test durations are available, source-file byte
size is the repository-owned weight proxy: larger files are assigned first to
the currently lightest shard, with stable path and shard-index tie-breaks.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_TEST_DIRECTORY = REPOSITORY_ROOT / "tests" / "integration"


@dataclass(frozen=True, slots=True)
class WeightedTestFile:
    """An integration test file and its positive scheduling weight.

    Attributes
    ----------
    path
        The filesystem path to read, validate, or write.
    weight
        The weight retained in this immutable projection.
    """

    path: Path
    weight: int

    def __post_init__(self) -> None:
        """Implement `__post_init__` for WeightedTestFile.

        Raises
        ------
        ValueError
            If the requested operation violates this domain contract.
        """
        if self.weight < 1:
            raise ValueError("test-file weight must be positive")


def _path_key(path: Path) -> str:
    return path.as_posix()


def discover_integration_tests(directory: Path) -> tuple[Path, ...]:
    """Return every direct ``test_*.py`` integration file in stable order.

    Parameters
    ----------
    directory : Path
        The filesystem path for directory.

    Returns
    -------
    tuple[Path, ...]
        The matching discover integration tests records in deterministic order.
    """
    return tuple(
        sorted(
            (path for path in directory.glob("test_*.py") if path.is_file()),
            key=_path_key,
        )
    )


def weigh_test_files(test_files: Sequence[Path]) -> tuple[WeightedTestFile, ...]:
    """Weigh files by byte size, using one byte for a possible empty file.

    Parameters
    ----------
    test_files : Sequence[Path]
        The selected test files to validate in deterministic order.

    Returns
    -------
    tuple[WeightedTestFile, ...]
        The matching weigh test files records in deterministic order.
    """
    return tuple(
        WeightedTestFile(path=path, weight=max(path.stat().st_size, 1))
        for path in test_files
    )


def validate_shard_inputs(
    *, shard_index: int, shard_count: int, test_count: int
) -> None:
    """Reject shard selections that could skip or accidentally broaden tests.

    Parameters
    ----------
    shard_index : int
        The shard index evaluated while validate shard inputs.
    shard_count : int
        The bounded number of shard records.
    test_count : int
        The bounded number of test records.

    Raises
    ------
    ValueError
        If the supplied value cannot satisfy the documented contract.
    """
    if test_count < 1:
        raise ValueError("no integration test files were discovered")
    if shard_count < 1:
        raise ValueError("shard count must be at least 1")
    if shard_count > test_count:
        raise ValueError("shard count cannot exceed the integration test file count")
    if shard_index < 1 or shard_index > shard_count:
        raise ValueError(f"shard index must be between 1 and {shard_count}")


def partition_test_files(
    test_files: Sequence[WeightedTestFile], shard_count: int
) -> tuple[tuple[Path, ...], ...]:
    """Greedily partition weighted files with deterministic stable tie-breaks.

    Parameters
    ----------
    test_files : Sequence[WeightedTestFile]
        The selected test files to validate in deterministic order.
    shard_count : int
        The bounded number of shard records.

    Returns
    -------
    tuple[tuple[Path, ...], ...]
        The matching partition test files records in deterministic order.

    Raises
    ------
    ValueError
        If the supplied value cannot satisfy the documented contract.
    """
    validate_shard_inputs(
        shard_index=1,
        shard_count=shard_count,
        test_count=len(test_files),
    )
    paths = [test_file.path for test_file in test_files]
    if len(paths) != len(set(paths)):
        raise ValueError("integration test files must be unique")

    buckets: list[list[WeightedTestFile]] = [[] for _ in range(shard_count)]
    bucket_weights = [0] * shard_count
    ordered_files = sorted(
        test_files,
        key=lambda test_file: (-test_file.weight, _path_key(test_file.path)),
    )

    for test_file in ordered_files:
        bucket_index = min(
            range(shard_count),
            key=lambda index: (bucket_weights[index], index),
        )
        buckets[bucket_index].append(test_file)
        bucket_weights[bucket_index] += test_file.weight

    return tuple(
        tuple(
            test_file.path
            for test_file in sorted(bucket, key=lambda item: _path_key(item.path))
        )
        for bucket in buckets
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one deterministic file-level integration-test shard."
    )
    parser.add_argument(
        "--shard-index",
        required=True,
        type=int,
        help="1-based shard index to run",
    )
    parser.add_argument(
        "--shard-count",
        required=True,
        type=int,
        help="total number of file-level shards",
    )
    return parser


def invoke_pytest(arguments: Sequence[str]) -> int:
    """Invoke pytest in-process and normalize its exit status to an integer.

    Parameters
    ----------
    arguments : Sequence[str]
        The arguments evaluated while invoke pytest.

    Returns
    -------
    int
        The resolved int for invoke pytest.
    """
    return int(pytest.main(list(arguments)))


def main(argv: Sequence[str] | None = None) -> int:
    """Select one shard and invoke pytest in this Python process.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        The argv evaluated while main.

    Returns
    -------
    int
        The process exit status; zero indicates success.
    """
    parser = _argument_parser()
    namespace, pytest_arguments = parser.parse_known_args(
        list(argv) if argv is not None else None
    )
    shard_index = int(namespace.shard_index)
    shard_count = int(namespace.shard_count)
    if pytest_arguments[:1] == ["--"]:
        pytest_arguments = pytest_arguments[1:]

    test_files = discover_integration_tests(INTEGRATION_TEST_DIRECTORY)
    try:
        validate_shard_inputs(
            shard_index=shard_index,
            shard_count=shard_count,
            test_count=len(test_files),
        )
    except ValueError as error:
        parser.error(str(error))

    weighted_files = weigh_test_files(test_files)
    shards = partition_test_files(weighted_files, shard_count)
    selected_files = shards[shard_index - 1]
    weights_by_path = {test_file.path: test_file.weight for test_file in weighted_files}
    selected_weight = sum(weights_by_path[path] for path in selected_files)
    print(
        f"Integration shard {shard_index}/{shard_count}: "
        f"{len(selected_files)} files, {selected_weight} weighted bytes."
    )

    return invoke_pytest(
        [
            *pytest_arguments,
            *(str(path) for path in selected_files),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
