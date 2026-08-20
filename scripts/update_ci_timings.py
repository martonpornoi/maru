"""Build Maru's file-level integration timing map from accepted JUnit XML."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

CLASSNAME_PART_COUNT = 3


def collect_file_timings(xml_paths: Iterable[Path]) -> dict[str, float]:
    """Aggregate JUnit testcase durations by integration test file.

    Parameters
    ----------
    xml_paths : Iterable[Path]
        JUnit XML reports from every integration shard in one accepted run.

    Returns
    -------
    dict[str, float]
        Stable repository paths mapped to summed duration seconds.

    Raises
    ------
    ValueError
        If a testcase has a missing or malformed duration.
    """
    totals: defaultdict[str, float] = defaultdict(float)
    for xml_path in sorted(xml_paths, key=lambda path: path.as_posix()):
        root = ET.parse(xml_path).getroot()  # noqa: S314
        for testcase in root.iter("testcase"):
            classname = testcase.get("classname", "")
            parts = classname.split(".")
            if len(parts) < CLASSNAME_PART_COUNT or parts[:2] != [
                "tests",
                "integration",
            ]:
                continue
            raw_time = testcase.get("time")
            if raw_time is None:
                raise ValueError(f"testcase in {xml_path} has no duration")
            try:
                duration = float(raw_time)
            except ValueError as error:
                raise ValueError(
                    f"testcase in {xml_path} has invalid duration {raw_time!r}"
                ) from error
            if duration < 0:
                raise ValueError(f"testcase in {xml_path} has negative duration")
            path = f"tests/integration/{parts[2]}.py"
            totals[path] += duration
    return {path: round(totals[path], 3) for path in sorted(totals)}


def write_timing_map(timings: dict[str, float], destination: Path) -> None:
    """Write a deterministic positive timing map.

    Parameters
    ----------
    timings : dict[str, float]
        Repository paths and measured duration seconds.
    destination : Path
        JSON file to replace with the normalized timing map.

    Raises
    ------
    ValueError
        If no positive timings were supplied.
    """
    if not timings or any(duration <= 0 for duration in timings.values()):
        raise ValueError("timing map must contain only positive durations")
    destination.write_text(
        json.dumps(timings, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _argument_parser() -> argparse.ArgumentParser:
    """Build the timing-map command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser for an artifact directory and destination file.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_directory", type=Path)
    parser.add_argument("destination", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate a deterministic timing map from downloaded CI artifacts.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Optional arguments; process arguments are used when omitted.

    Returns
    -------
    int
        Zero after a complete timing map has been written.
    """
    namespace = _argument_parser().parse_args(list(argv) if argv is not None else None)
    timings = collect_file_timings(namespace.artifact_directory.rglob("*.xml"))
    write_timing_map(timings, namespace.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
