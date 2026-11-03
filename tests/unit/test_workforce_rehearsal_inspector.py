"""Adversarial checks for minimized synthetic rehearsal reports."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from scripts import inspect_workforce_rehearsal as inspector

CHECKS = (
    "only_reserved_synthetic_accounts",
    "platform_has_no_membership",
    "platform_has_no_position_assignment",
    "platform_has_no_role_assignment",
    "platform_has_no_participation",
    "no_organizations",
    "no_editions",
    "no_workforce_rows",
)


def _baseline():
    return {
        "format_version": 1,
        "phase": "baseline",
        "checker_identity": "a" * 64,
        "fixture_identity": "b" * 64,
        "unadopted_modules": ["knowledge", "participation"],
        "model_counts": {"knowledge.guidanceitem": 0, "participation.participation": 0},
        "checks": dict.fromkeys(CHECKS, True),
        "status": "passed",
        "failures": [],
    }


def _final():
    result = _baseline()
    result["phase"] = "final"
    result["checks"] = {"assignment_ended": True, "completion_after_real_end": True}
    return result


def test_matching_zero_inventory_is_accepted():
    assert inspector.evaluate(_baseline(), None) == []
    assert inspector.evaluate(_final(), _baseline()) == []


@pytest.mark.parametrize("value", [1, -1, None, False, "0", 0.0])
def test_missing_or_nonzero_count_never_becomes_absence(value):
    report = _final()
    report["model_counts"]["participation.participation"] = value
    assert "nonzero:participation.participation" in inspector.evaluate(
        report, _baseline()
    )


@pytest.mark.parametrize(
    "key",
    ["format_version", "checker_identity", "fixture_identity", "unadopted_modules"],
)
def test_a_different_fixture_checker_or_catalog_cannot_reuse_baseline(key):
    baseline = _baseline()
    baseline[key] = "different"
    assert "baseline_mismatch:" + key in inspector.evaluate(_final(), baseline)


def test_new_or_removed_model_requires_a_fresh_complete_baseline():
    baseline = _baseline()
    baseline["model_counts"].pop("knowledge.guidanceitem")
    assert "baseline_mismatch:model_counts" in inspector.evaluate(_final(), baseline)


@pytest.mark.parametrize("missing", CHECKS)
def test_truncated_baseline_checks_are_rejected(missing):
    baseline = _baseline()
    del baseline["checks"][missing]
    assert "invalid_baseline_checks" in inspector.evaluate(_final(), baseline)


def test_false_lifecycle_or_missing_baseline_cannot_pass():
    report = _final()
    report["checks"]["completion_after_real_end"] = False
    failed = inspector.evaluate(report, None)
    assert "completion_after_real_end" in failed
    assert "missing_passed_baseline" in failed


def test_unavailable_query_is_blocked_without_secret_exception_text(
    monkeypatch, tmp_path, capsys
):
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "inspect",
            "baseline",
            "--confirm-dedicated-synthetic",
            "--platform-email",
            "platform@example.invalid",
            "--output",
            str(output),
        ],
    )

    def unavailable(**_kwargs):
        raise RuntimeError("private-connection-material-must-not-appear")

    monkeypatch.setattr(inspector, "_read_snapshot", unavailable)
    assert inspector.main() == 1
    report = json.loads(output.read_text())
    assert report["status"] == "blocked"
    assert "model_counts" not in report
    assert (
        "private-connection-material"
        not in output.read_text() + capsys.readouterr().out
    )


def test_existing_evidence_is_not_overwritten(monkeypatch, tmp_path):
    output = tmp_path / "report.json"
    original = json.dumps(deepcopy(_baseline()))
    output.write_text(original)
    monkeypatch.setattr(
        "sys.argv",
        [
            "inspect",
            "baseline",
            "--confirm-dedicated-synthetic",
            "--platform-email",
            "platform@example.invalid",
            "--output",
            str(output),
        ],
    )
    with pytest.raises(FileExistsError):
        inspector.main()
    assert output.read_text() == original
