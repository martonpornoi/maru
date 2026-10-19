"""Timing reports cannot hide missing, failed, skipped or mismatched cases."""

import json
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest
from scripts import update_ci_group_timings as timing
from scripts.ci_test_policy import TestGroup as Group


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


@pytest.fixture
def calibration_cli(tmp_path, monkeypatch):
    """Exercise the CLI against complete synthetic reports and bound source inputs."""
    file = "tests/integration/test_example.py"
    current = file + "::current"
    historical = file + "::test_old"
    reports = tmp_path / "reports"
    reports.mkdir()
    evidence(reports)
    receipt = {
        "result": "success",
        "commit": "a" * 40,
        "base_commit": "b" * 40,
        "historical_scope": "affected",
        "integration_shards": 1,
    }
    receipt_path = tmp_path / "certification.json"
    receipt_path.write_text(json.dumps(receipt))
    baseline = tmp_path / timing.TIMINGS
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps({current: 9.0004, historical: 12.0004}))
    baseline.with_suffix(".provenance.json").write_text('{"schema_version": 1}')
    inventory = tmp_path / timing.MANIFEST
    inventory.write_text('{"reviewed": true}')
    test_file = tmp_path / file
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_example(): pass\ndef test_old(): pass\n")
    originals = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (
            baseline,
            baseline.with_suffix(".provenance.json"),
            inventory,
            test_file,
        )
    }
    monkeypatch.setattr(timing, "ROOT", tmp_path)
    monkeypatch.setattr(
        timing,
        "build_groups",
        lambda: (
            Group(current, file, historical=False, weight=9.0004),
            Group(historical, file, historical=True, weight=12.0004),
        ),
    )
    monkeypatch.setattr(timing.shutil, "which", lambda _name: "git")

    def show(arguments, **kwargs):
        assert arguments[:2] == ["git", "show"]
        assert arguments[2].startswith("a" * 40 + ":")
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(
            arguments, 0, stdout=originals[arguments[2].split(":", 1)[1]]
        )

    monkeypatch.setattr(timing.subprocess, "run", show)
    output = tmp_path / "output.json"
    arguments = [
        "update_ci_group_timings",
        "--local-evidence",
        str(tmp_path),
        "--commit",
        "a" * 40,
        "--base",
        "b" * 40,
        "--destination",
        str(output),
        "--current-only",
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    return {
        "root": tmp_path,
        "output": output,
        "receipt": receipt,
        "receipt_path": receipt_path,
        "baseline": baseline,
        "originals": originals,
        "arguments": arguments,
        "current": current,
        "historical": historical,
    }


@pytest.mark.parametrize("scope", ["current", "affected"])
def test_complete_current_calibration_preserves_exact_historical_and_known_costs(
    calibration_cli, scope
):
    cli = calibration_cli
    cli["receipt"]["historical_scope"] = scope
    cli["receipt_path"].write_text(json.dumps(cli["receipt"]))
    assert timing.main() == 0
    assert json.loads(cli["output"].read_text()) == {
        cli["current"]: 9.0004,
        cli["historical"]: 12.0004,
    }
    provenance = json.loads(cli["output"].with_suffix(".provenance.json").read_text())
    assert provenance["historical_scope"] == scope
    assert provenance["calibration_scope"] == "current"
    assert provenance["local_groups"] == 1
    assert provenance["preserved_groups"] == 1
    assert provenance["baseline"]["commit"] == "a" * 40


def test_complete_current_calibration_adds_measured_missing_group(calibration_cli):
    cli = calibration_cli
    cli["baseline"].write_text(json.dumps({cli["historical"]: 12.0004}))
    cli["originals"][timing.TIMINGS] = cli["baseline"].read_bytes()
    assert timing.main() == 0
    assert json.loads(cli["output"].read_text()) == {
        cli["current"]: 2.5,
        cli["historical"]: 12.0004,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("result", "failed"),
        ("result", "diagnostic_success"),
        ("commit", "c" * 40),
        ("base_commit", "c" * 40),
        ("historical_scope", "all"),
        ("historical_scope", "unknown"),
        ("integration_shards", 2),
    ],
)
def test_current_calibration_rejects_wrong_receipt_without_writing(
    calibration_cli, field, value
):
    cli = calibration_cli
    cli["receipt"][field] = value
    cli["receipt_path"].write_text(json.dumps(cli["receipt"]))
    with pytest.raises(ValueError, match=r"receipt|shard inventory"):
        timing.main()
    assert not cli["output"].exists()


@pytest.mark.parametrize("input_name", ["test", "inventory", "baseline", "provenance"])
def test_current_calibration_binds_inherited_inputs_to_measured_commit(
    calibration_cli, input_name
):
    cli = calibration_cli
    path = {
        "test": cli["root"] / "tests/integration/test_example.py",
        "inventory": cli["root"] / timing.MANIFEST,
        "baseline": cli["baseline"],
        "provenance": cli["baseline"].with_suffix(".provenance.json"),
    }[input_name]
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="source changed"):
        timing.main()
    assert not cli["output"].exists()


def test_current_calibration_rejects_historical_group_in_place_of_current(
    calibration_cli,
):
    cli = calibration_cli
    selection = cli["root"] / "reports/selection-1.json"
    data = json.loads(selection.read_text())
    data["groups"][cli["historical"]] = data["groups"].pop(cli["current"])
    selection.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="exact required group scope"):
        timing.main()
    assert not cli["output"].exists()


def test_default_calibration_still_requires_exhaustive_receipt(calibration_cli):
    cli = calibration_cli
    cli["arguments"].remove("--current-only")
    with pytest.raises(ValueError, match="receipt"):
        timing.main()
    cli["receipt"]["historical_scope"] = "all"
    cli["receipt_path"].write_text(json.dumps(cli["receipt"]))
    with pytest.raises(ValueError, match="exact required group scope"):
        timing.main()
    assert not cli["output"].exists()


def test_exhaustive_calibration_still_consumes_both_current_and_history(
    calibration_cli,
):
    cli = calibration_cli
    cli["arguments"].remove("--current-only")
    cli["receipt"].update(historical_scope="all", integration_shards=2)
    cli["receipt_path"].write_text(json.dumps(cli["receipt"]))
    extra = cli["root"] / "extra"
    extra.mkdir()
    report, selection = evidence(extra, node="test_old", duration="7")
    data = json.loads(selection.read_text())
    data["groups"][cli["historical"]] = data["groups"].pop(cli["current"])
    (cli["root"] / "reports/selection-2.json").write_text(json.dumps(data))
    (cli["root"] / "reports/integration-2.xml").write_bytes(report.read_bytes())
    assert timing.main() == 0
    assert json.loads(cli["output"].read_text()) == {
        cli["current"]: 2.5,
        cli["historical"]: 7,
    }


@pytest.mark.parametrize("hosted_duration", ["3", "11"])
def test_current_calibration_keeps_largest_known_local_or_hosted_cost(
    calibration_cli, hosted_duration
):
    cli = calibration_cli
    evidence(cli["root"] / "reports", duration="10")
    hosted = cli["root"] / "hosted"
    hosted.mkdir()
    evidence(hosted, duration=hosted_duration)
    cli["arguments"].extend(["--hosted-evidence", str(hosted)])
    assert timing.main() == 0
    assert json.loads(cli["output"].read_text()) == {
        cli["current"]: max(10, float(hosted_duration)),
        cli["historical"]: 12.0004,
    }
    provenance = json.loads(cli["output"].with_suffix(".provenance.json").read_text())
    assert provenance["hosted_observed_groups"] == 1
    assert len(provenance["inputs"]) == 5
