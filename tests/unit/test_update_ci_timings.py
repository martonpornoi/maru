from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from scripts.update_ci_timings import collect_file_timings, write_timing_map

if TYPE_CHECKING:
    from pathlib import Path


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
