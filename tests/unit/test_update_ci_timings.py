from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import pytest
from scripts import update_ci_timings
from scripts.update_ci_timings import (
    calibrate_file_timings,
    collect_file_timings,
    write_timing_map,
)

if TYPE_CHECKING:
    from pathlib import Path

COMMIT = "d" * 40
ALPHA = "tests/integration/test_alpha.py"
BRAVO = "tests/integration/test_bravo.py"
CHARLIE = "tests/integration/test_charlie.py"


def _report(
    directory: Path,
    filename: str,
    cases: tuple[tuple[str, str, str], ...],
    *,
    attributes: dict[str, str] | None = None,
    failure_child: str | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    suite = ET.Element(
        "testsuite",
        {"tests": str(len(cases)), "errors": "0", "failures": "0", "skipped": "0"}
        | (attributes or {}),
    )
    for module, name, seconds in cases:
        case = ET.SubElement(
            suite, "testcase", classname=module, name=name, time=seconds
        )
        if failure_child is not None:
            ET.SubElement(case, failure_child)
    path = directory / filename
    ET.ElementTree(suite).write(path, encoding="utf-8")
    return path


def _calibrate(
    local: tuple[Path, ...],
    hosted: tuple[Path, ...],
    excluded: frozenset[str] = frozenset(),
) -> tuple[dict[str, float], float]:
    return calibrate_file_timings(
        local,
        hosted,
        local_commit=COMMIT,
        hosted_commit=COMMIT,
        excluded_hosted_files=excluded,
    )


def test_calibration_uses_complete_job_groups_and_never_decreases_weights(
    tmp_path: Path,
) -> None:
    local = _report(
        tmp_path,
        "local.xml",
        (
            ("tests.integration.test_alpha", "a", "10"),
            ("tests.integration.test_bravo", "b", "10"),
            ("tests.integration.test_charlie", "c", "3"),
        ),
    )
    hosted = _report(
        tmp_path,
        "hosted.xml",
        (
            ("tests.integration.test_alpha", "a", "30"),
            ("tests.integration.test_bravo", "b", "5"),
        ),
    )

    timings, factor = _calibrate((local,), (hosted,))

    assert factor == 1.75  # Complete group ratio, not the 3x individual outlier.
    assert timings == {ALPHA: 30.0, BRAVO: 10.0, CHARLIE: 5.25}


def test_calibration_is_order_independent_and_ignores_unit_only_reports(
    tmp_path: Path,
) -> None:
    local = _report(
        tmp_path,
        "local.xml",
        (
            ("tests.integration.test_alpha", "a", "10"),
            ("tests.integration.test_bravo", "b", "10"),
            ("tests.integration.test_charlie", "c", "0.3333"),
        ),
    )
    first = _report(
        tmp_path, "hosted1.xml", (("tests.integration.test_alpha", "a", "5"),)
    )
    second = _report(
        tmp_path, "hosted2.xml", (("tests.integration.test_bravo", "b", "20"),)
    )
    unit = _report(tmp_path, "unit.xml", (("tests.unit.test_other", "u", "999"),))

    expected = ({ALPHA: 10.0, BRAVO: 20.0, CHARLIE: 0.667}, 2.0)
    assert _calibrate((local, unit), (first, second)) == expected
    assert _calibrate((unit, local), (second, first)) == expected
    assert _calibrate((local,), (first,))[1] == 1.0


def test_explicit_hosted_exclusion_preserves_baseline_file_and_conservative_cost(
    tmp_path: Path,
) -> None:
    local = _report(
        tmp_path,
        "local.xml",
        (
            ("tests.integration.test_alpha", "a", "10"),
            ("tests.integration.test_bravo", "random-local-id", "4"),
        ),
    )
    hosted = _report(
        tmp_path,
        "hosted.xml",
        (
            ("tests.integration.test_alpha", "a", "20"),
            ("tests.integration.test_bravo", "random-hosted-id", "999"),
        ),
    )

    with pytest.raises(ValueError, match="complete baseline"):
        _calibrate((local,), (hosted,))
    assert _calibrate((local,), (hosted,), frozenset({BRAVO})) == (
        {ALPHA: 20.0, BRAVO: 8.0},
        2.0,
    )
    with pytest.raises(ValueError, match="both evidence"):
        _calibrate((local,), (hosted,), frozenset({CHARLIE}))
    with pytest.raises(ValueError, match="at least one"):
        _calibrate((local,), (hosted,), frozenset({ALPHA, BRAVO}))


@pytest.mark.parametrize(
    "hosted_cases",
    [
        (("tests.integration.test_alpha", "a", "1"),),
        (
            ("tests.integration.test_alpha.OtherClass", "a", "1"),
            ("tests.integration.test_alpha", "b", "1"),
        ),
        (("tests.integration.test_unknown", "a", "1"),),
    ],
)
def test_calibration_rejects_partial_or_different_case_identity(
    tmp_path: Path,
    hosted_cases: tuple[tuple[str, str, str], ...],
) -> None:
    local = _report(
        tmp_path,
        "local.xml",
        (
            ("tests.integration.test_alpha", "a", "1"),
            ("tests.integration.test_alpha", "b", "1"),
        ),
    )
    hosted = _report(tmp_path, "hosted.xml", hosted_cases)
    with pytest.raises(ValueError, match="complete baseline"):
        _calibrate((local,), (hosted,))


@pytest.mark.parametrize(
    ("local_commit", "hosted_commit"),
    [
        (COMMIT, "e" * 40),
        ("d22a267", "d22a267"),
        ("D" * 40, "D" * 40),
        ("g" * 40, "g" * 40),
    ],
)
def test_calibration_requires_same_full_verified_head(
    local_commit: str, hosted_commit: str
) -> None:
    with pytest.raises(ValueError, match="same exact verified commit"):
        calibrate_file_timings(
            (), (), local_commit=local_commit, hosted_commit=hosted_commit
        )


@pytest.mark.parametrize(
    "attributes",
    [
        {"tests": "2"},
        {"tests": "bad"},
        {"failures": "1"},
        {"errors": "1"},
        {"skipped": "1"},
    ],
)
def test_calibration_rejects_incomplete_reports_even_when_file_is_excluded(
    tmp_path: Path,
    attributes: dict[str, str],
) -> None:
    local = _report(
        tmp_path, "local.xml", (("tests.integration.test_alpha", "a", "1"),)
    )
    hosted = _report(
        tmp_path,
        "hosted.xml",
        (("tests.integration.test_alpha", "a", "1"),),
        attributes=attributes,
    )
    with pytest.raises(ValueError, match=r"complete passing|invalid literal"):
        _calibrate((local,), (hosted,), frozenset({ALPHA}))


@pytest.mark.parametrize("child", ["failure", "error", "skipped"])
def test_calibration_rejects_failure_children_despite_zero_summary_counts(
    tmp_path: Path, child: str
) -> None:
    report = _report(
        tmp_path,
        "report.xml",
        (("tests.integration.test_alpha", "a", "1"),),
        failure_child=child,
    )
    with pytest.raises(ValueError, match="complete passing"):
        _calibrate((report,), (report,))


@pytest.mark.parametrize("seconds", ["0", "-1", "nan", "inf", "-inf", "bad"])
def test_calibration_rejects_nonpositive_or_invalid_file_measurements(
    tmp_path: Path, seconds: str
) -> None:
    report = _report(
        tmp_path, "report.xml", (("tests.integration.test_alpha", "a", seconds),)
    )
    with pytest.raises(
        ValueError, match=r"finite durations|positive whole-file|could not convert"
    ):
        _calibrate((report,), (report,))


def test_calibration_rejects_duplicate_cases_or_files(tmp_path: Path) -> None:
    case = ("tests.integration.test_alpha", "a", "1")
    duplicate = _report(tmp_path, "duplicate.xml", (case, case))
    with pytest.raises(ValueError, match="twice"):
        _calibrate((duplicate,), (duplicate,))
    first = _report(tmp_path, "first.xml", (case,))
    second = _report(
        tmp_path, "second.xml", (("tests.integration.test_alpha", "b", "1"),)
    )
    with pytest.raises(ValueError, match="whole file"):
        _calibrate((first, second), (first,))
    with pytest.raises(ValueError, match="whole file"):
        _calibrate((first,), (first, second))


def test_calibration_rejects_empty_evidence_and_ambiguous_suites(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="integration timing"):
        _calibrate((), ())
    report = _report(tmp_path, "empty.xml", ())
    with pytest.raises(ValueError, match="complete passing"):
        _calibrate((report,), (report,))
    report.write_text(
        "<testsuites><testsuite/><testsuite/></testsuites>", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="one completed"):
        _calibrate((report,), (report,))


@pytest.mark.parametrize(
    "extra",
    [
        ["--hosted-artifact-directory", "hosted"],
        ["--hosted-artifact-directory", "hosted", "--local-commit", COMMIT],
        ["--local-commit", COMMIT],
        ["--hosted-commit", COMMIT],
        ["--exclude-hosted-file", ALPHA],
    ],
)
def test_calibration_cli_rejects_incomplete_or_orphaned_options(
    tmp_path: Path, extra: list[str]
) -> None:
    destination = tmp_path / "result.json"
    with pytest.raises(SystemExit) as error:
        update_ci_timings.main([str(tmp_path), str(destination), *extra])
    assert error.value.code == 2
    assert not destination.exists()


def test_calibration_cli_checks_exact_inventory_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "local"
    hosted = tmp_path / "hosted"
    _report(local, "report.xml", (("tests.integration.test_alpha", "a", "1"),))
    _report(hosted, "report.xml", (("tests.integration.test_alpha", "a", "2"),))
    inventory = tmp_path / "tests" / "integration"
    inventory.mkdir(parents=True)
    (inventory / "test_alpha.py").touch()
    monkeypatch.setattr(update_ci_timings, "REPOSITORY_ROOT", tmp_path)
    destination = tmp_path / "result.json"
    args = [
        str(local),
        str(destination),
        "--hosted-artifact-directory",
        str(hosted),
        "--local-commit",
        COMMIT,
        "--hosted-commit",
        COMMIT,
    ]
    assert update_ci_timings.main(args) == 0
    assert json.loads(destination.read_text(encoding="utf-8")) == {ALPHA: 2.0}
    (inventory / "test_bravo.py").touch()
    with pytest.raises(ValueError, match="full inventory"):
        update_ci_timings.main(args)
    assert json.loads(destination.read_text(encoding="utf-8")) == {ALPHA: 2.0}
    assert update_ci_timings.main([str(local), str(destination)]) == 0
    assert json.loads(destination.read_text(encoding="utf-8")) == {ALPHA: 1.0}


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_collector_and_writer_reject_nonfinite_or_negative_durations(
    tmp_path: Path, duration: float
) -> None:
    report = _report(
        tmp_path, "report.xml", (("tests.integration.test_alpha", "a", str(duration)),)
    )
    with pytest.raises(ValueError, match="duration"):
        collect_file_timings((report,))
    with pytest.raises(ValueError, match="positive"):
        write_timing_map({ALPHA: duration}, tmp_path / "result.json")


def test_junit_timings_are_summed_by_file(tmp_path: Path) -> None:
    report = tmp_path / "report.xml"
    report.write_text(
        """<?xml version="1.0"?>
<testsuites><testsuite>
<testcase classname="tests.integration.test_alpha" name="a" time="1.25" />
<testcase classname="tests.integration.test_alpha" name="b" time="0.75" />
<testcase classname="tests.unit.test_other" name="c" time="99" />
</testsuite></testsuites>
""",
        encoding="utf-8",
    )

    assert collect_file_timings((report,)) == {"tests/integration/test_alpha.py": 2.0}


def test_timing_map_writer_is_sorted_and_rejects_empty_input(tmp_path: Path) -> None:
    destination = tmp_path / "timings.json"

    write_timing_map({"test_b.py": 2.0, "test_a.py": 1.0}, destination)

    assert list(json.loads(destination.read_text(encoding="utf-8"))) == [
        "test_a.py",
        "test_b.py",
    ]
    with pytest.raises(ValueError, match="positive"):
        write_timing_map({}, destination)
