"""Build file-level scheduling weights from complete JUnit timing evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

CLASSNAME_PART_COUNT = 3
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class _FileMeasurement:
    """Retain one file's measured duration and exact collected case identities."""

    seconds: float
    cases: frozenset[tuple[str, str]]


def _complete_integration_reports(
    xml_paths: Iterable[Path],
) -> tuple[dict[str, _FileMeasurement], ...]:
    """Validate completed JUnit suites and retain unsplit integration files.

    Parameters
    ----------
    xml_paths : Iterable[Path]
        Local or hosted reports from one independently verified revision.

    Returns
    -------
    tuple[dict[str, _FileMeasurement], ...]
        Whole-file durations and exact case identities grouped by execution job.

    Raises
    ------
    ValueError
        If reports are incomplete, duplicated, unsuccessful, or malformed.
    """
    reports: list[dict[str, _FileMeasurement]] = []
    seen_files: set[str] = set()
    for path in sorted(xml_paths, key=lambda item: item.as_posix()):
        root = ET.parse(path).getroot()  # noqa: S314
        suites = tuple(root.iter("testsuite"))
        if len(suites) != 1:
            raise ValueError(
                "calibration requires one completed pytest suite per report"
            )
        suite = suites[0]
        cases = tuple(suite.iter("testcase"))
        if (
            any(
                int(suite.get(key, "-1")) != 0
                for key in ("errors", "failures", "skipped")
            )
            or int(suite.get("tests", "-1")) != len(cases)
            or not cases
            or any(
                child.tag in {"failure", "error", "skipped"}
                for case in cases
                for child in case
            )
        ):
            raise ValueError(
                "calibration requires complete passing reports without skips"
            )
        durations: defaultdict[str, float] = defaultdict(float)
        identities: defaultdict[str, set[tuple[str, str]]] = defaultdict(set)
        for case in cases:
            classname = case.get("classname", "")
            parts = classname.split(".")
            if len(parts) < CLASSNAME_PART_COUNT or parts[:2] != [
                "tests",
                "integration",
            ]:
                continue
            name = case.get("name", "")
            seconds = float(case.get("time", "nan"))
            if not name or not math.isfinite(seconds) or seconds < 0:
                raise ValueError(
                    "calibration requires named cases with finite durations"
                )
            file_key = f"tests/integration/{parts[2]}.py"
            identity = (classname, name)
            if identity in identities[file_key]:
                raise ValueError("calibration cannot count a testcase twice")
            identities[file_key].add(identity)
            durations[file_key] += seconds
        if seen_files.intersection(durations):
            raise ValueError(
                "calibration requires each whole file in exactly one report"
            )
        if any(
            not math.isfinite(seconds) or seconds <= 0 for seconds in durations.values()
        ):
            raise ValueError("calibration requires positive whole-file durations")
        seen_files.update(durations)
        if durations:
            reports.append(
                {
                    key: _FileMeasurement(seconds, frozenset(identities[key]))
                    for key, seconds in durations.items()
                }
            )
    if not reports:
        raise ValueError("calibration requires integration timing evidence")
    return tuple(reports)


def calibrate_file_timings(
    local_xml_paths: Iterable[Path],
    hosted_xml_paths: Iterable[Path],
    *,
    local_commit: str,
    hosted_commit: str,
    excluded_hosted_files: frozenset[str] = frozenset(),
) -> tuple[dict[str, float], float]:
    """Conservatively calibrate complete local evidence with same-head hosted jobs.

    The caller verifies the successful full local certification and the hosted
    run's exact head and successful observed jobs. These unsigned measurements
    estimate scheduling cost; they never attest acceptance. Every observed file
    must contain exactly its baseline cases. Missing or explicitly excluded
    hosted observations receive the largest ratio of matched complete file
    groups within a hosted job, bounded below by one.

    Parameters
    ----------
    local_xml_paths : Iterable[Path]
        Complete reports from successful exact-head local certification.
    hosted_xml_paths : Iterable[Path]
        Reports from completed successful hosted jobs at the same exact head.
    local_commit : str
        Verified local certification's full lower-case Git commit identifier.
    hosted_commit : str
        Independently verified hosted run's full lower-case Git commit identifier.
    excluded_hosted_files : frozenset[str], default=frozenset()
        Exact paths whose hosted observations cannot be matched reliably. Their
        complete baseline measurements remain; no test is excluded from execution.

    Returns
    -------
    tuple[dict[str, float], float]
        Conservative millisecond-rounded file weights and the observed fallback
        ratio. Observed weights never fall below either measured file duration.

    Raises
    ------
    ValueError
        If heads differ, evidence is incomplete, cases differ, or values are invalid.
    """
    if (
        not isinstance(local_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", local_commit) is None
        or local_commit != hosted_commit
    ):
        raise ValueError("calibration requires the same exact verified commit")
    local_reports = _complete_integration_reports(local_xml_paths)
    hosted_reports = _complete_integration_reports(hosted_xml_paths)
    baseline = {key: value for report in local_reports for key, value in report.items()}
    hosted_files = {key for report in hosted_reports for key in report}
    if not excluded_hosted_files <= baseline.keys() & hosted_files:
        raise ValueError(
            "excluded hosted observations must exist in both evidence sets"
        )
    observed: dict[str, _FileMeasurement] = {}
    factor = 1.0
    for complete_report in hosted_reports:
        report = {
            key: value
            for key, value in complete_report.items()
            if key not in excluded_hosted_files
        }
        if not report:
            continue
        for key, measurement in report.items():
            if key not in baseline or measurement.cases != baseline[key].cases:
                raise ValueError(
                    "hosted observations must match complete baseline files"
                )
        factor = max(
            factor,
            sum(value.seconds for value in report.values())
            / sum(baseline[key].seconds for key in report),
        )
        observed.update(report)
    if not observed:
        raise ValueError("calibration requires at least one matched hosted observation")
    return (
        {
            key: round(
                max(value.seconds, observed[key].seconds)
                if key in observed
                else value.seconds * factor,
                3,
            )
            for key, value in sorted(baseline.items())
        },
        factor,
    )


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
            if not math.isfinite(duration) or duration < 0:
                raise ValueError(
                    f"testcase in {xml_path} has non-finite or negative duration"
                )
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
    if not timings or any(
        not math.isfinite(duration) or duration <= 0 for duration in timings.values()
    ):
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
    parser.add_argument("--hosted-artifact-directory", type=Path)
    parser.add_argument("--local-commit")
    parser.add_argument("--hosted-commit")
    parser.add_argument("--exclude-hosted-file", action="append", default=[])
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

    Raises
    ------
    ValueError
        If reports or weights are invalid, or calibration inventory is incomplete.
    """
    parser = _argument_parser()
    namespace = parser.parse_args(list(argv) if argv is not None else None)
    if namespace.hosted_artifact_directory is not None:
        if namespace.local_commit is None or namespace.hosted_commit is None:
            parser.error("hosted calibration requires both verified commit identifiers")
        timings, factor = calibrate_file_timings(
            namespace.artifact_directory.rglob("*.xml"),
            namespace.hosted_artifact_directory.rglob("*.xml"),
            local_commit=namespace.local_commit,
            hosted_commit=namespace.hosted_commit,
            excluded_hosted_files=frozenset(namespace.exclude_hosted_file),
        )
        expected = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in (REPOSITORY_ROOT / "tests" / "integration").glob("test_*.py")
            if path.is_file()
        }
        if set(timings) != expected:
            raise ValueError("local calibration baseline must cover the full inventory")
        print(
            f"Calibrated {len(timings)} files; unobserved hosted factor {factor:.6f}; "
            f"excluded {len(set(namespace.exclude_hosted_file))} hosted observations."
        )
    else:
        if (
            namespace.local_commit is not None
            or namespace.hosted_commit is not None
            or namespace.exclude_hosted_file
        ):
            parser.error(
                "commit identifiers and exclusions require hosted calibration evidence"
            )
        timings = collect_file_timings(namespace.artifact_directory.rglob("*.xml"))
    write_timing_map(timings, namespace.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
