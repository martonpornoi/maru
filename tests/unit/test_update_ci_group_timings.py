"""Timing reports cannot hide missing, failed, skipped or mismatched cases."""

import json
from xml.etree import ElementTree as ET

import pytest
from scripts import update_ci_group_timings as timing


def evidence(tmp_path, *, node="test_example[a::b]", duration="2.5", tag=None):
    file = "tests/integration/test_example.py"
    selection = tmp_path / "selection-1.json"
    selection.write_text(
        json.dumps(
            {
                "collected": 1,
                "selected": 1,
                "groups": {file + "::current": [file + "::" + node]},
            }
        )
    )
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root, "testsuite", tests="1", errors="0", failures="0", skipped="0"
    )
    classname, name = timing._identity(file + "::" + node)
    case = ET.SubElement(
        suite, "testcase", classname=classname, name=name, time=duration
    )
    if tag is not None:
        ET.SubElement(case, tag)
    report = tmp_path / "integration-1.xml"
    ET.ElementTree(root).write(report, encoding="unicode")
    return report, selection


@pytest.mark.parametrize(
    "name", ["test_x[a::b]", "TestCurrent::test_x", "test_x[\nSELECT 0::smallint\n]"]
)
def test_group_evidence_preserves_classes_parameter_colons_and_multiline_ids(
    tmp_path, name
):
    report, selection = evidence(tmp_path, node=name)
    groups, nodes = timing.report_costs(report, selection)
    assert groups == {"tests/integration/test_example.py::current": 2.5}
    assert nodes == {"tests/integration/test_example.py::" + name}


@pytest.mark.parametrize("tag", ["failure", "error", "skipped"])
def test_failed_or_skipped_case_is_never_cost_calibration(tmp_path, tag):
    report, selection = evidence(tmp_path, tag=tag)
    with pytest.raises(ValueError, match="nonpassing"):
        timing.report_costs(report, selection)


@pytest.mark.parametrize("duration", ["-1", "nan", "inf", "0"])
def test_nonfinite_negative_or_zero_group_duration_is_rejected(tmp_path, duration):
    report, selection = evidence(tmp_path, duration=duration)
    with pytest.raises(ValueError, match=r"duration|nonpositive"):
        timing.report_costs(report, selection)


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "wrong_name", "suite_count", "selection_count"]
)
def test_missing_extra_and_inconsistent_reports_cannot_refresh_weights(
    tmp_path, mutation
):
    report, selection = evidence(tmp_path)
    tree = ET.parse(report)  # noqa: S314 - fixture generated above in this test
    suite = tree.find("testsuite")
    case = suite.find("testcase")
    if mutation == "missing":
        suite.remove(case)
    elif mutation == "duplicate":
        suite.append(case)
    elif mutation == "wrong_name":
        case.set("name", "test_other")
    elif mutation == "suite_count":
        suite.set("tests", "2")
    else:
        value = json.loads(selection.read_text())
        value["selected"] = 2
        selection.write_text(json.dumps(value))
    tree.write(report, encoding="unicode")
    with pytest.raises(ValueError, match=r"incomplete|identity|count"):
        timing.report_costs(report, selection)


def test_hosted_cost_never_lowers_local_and_unusable_comparison_does_not_drop_tests(
    tmp_path,
):
    report, selection = evidence(tmp_path)
    groups, nodes = timing.report_costs(report, selection)
    measured = dict.fromkeys(groups, 5.0)
    inputs = []
    observed = timing._merge_hosted_costs(tmp_path, set(), measured, set(nodes), inputs)
    assert measured == dict.fromkeys(groups, 5.0)
    assert observed == set(groups)
    assert inputs == [report, selection]
    with pytest.raises(ValueError, match="no usable"):
        timing._merge_hosted_costs(
            tmp_path, {"tests/integration/test_example.py"}, measured, set(nodes), []
        )
    assert measured == dict.fromkeys(groups, 5.0)


def test_cross_environment_identity_difference_needs_explicit_diagnostic_exclusion(
    tmp_path,
):
    report, selection = evidence(tmp_path)
    groups, _nodes = timing.report_costs(report, selection)
    with pytest.raises(ValueError, match="differ"):
        timing._merge_hosted_costs(tmp_path, set(), groups, {"different"}, [])
    with pytest.raises(ValueError, match="require hosted"):
        timing._merge_hosted_costs(None, {"x"}, groups, set(), [])
