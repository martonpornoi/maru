from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest
import yaml
from scripts import ci_changes
from scripts import ci_development_policy as policy

from maru.events.adoption import ADOPTION_PROFILES

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mode", ["required", "deferred"])
def test_policy_has_one_reviewed_mode_and_restoration_owner(tmp_path, mode):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps({"schema_version": 1, "mode": mode, "restoration_issue": 48})
    )
    assert policy.postgresql_policy_mode(path) == mode


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        True,
        {"schema_version": True, "mode": "deferred", "restoration_issue": 48},
        {"schema_version": 2, "mode": "deferred", "restoration_issue": 48},
        {"schema_version": 1, "mode": "skip", "restoration_issue": 48},
        {"schema_version": 1, "mode": "deferred", "restoration_issue": True},
        {"schema_version": 1, "mode": "deferred", "restoration_issue": 49},
        {
            "schema_version": 1,
            "mode": "deferred",
            "restoration_issue": 48,
            "bypass": True,
        },
    ],
)
def test_invalid_policy_fails_closed(tmp_path, value):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Unsupported"):
        policy.postgresql_policy_mode(path)


def test_missing_or_malformed_policy_does_not_assume_deferral(tmp_path):
    path = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        policy.postgresql_policy_mode(path)
    path.write_text("{broken")
    with pytest.raises(json.JSONDecodeError):
        policy.postgresql_policy_mode(path)


@pytest.mark.parametrize("mode", ["required", "deferred"])
@pytest.mark.parametrize("integration", ["none", "targeted", "full"])
def test_effective_plan_preserves_risk_and_unrelated_protections(
    monkeypatch, mode, integration
):
    monkeypatch.setattr(policy, "postgresql_policy_mode", lambda: mode)
    original = {
        "integration": integration,
        "history": "all",
        "destructive": "true",
        "deleted_count": "25",
        "dependency_review": "true",
        "python": "false",
    }
    result = policy.apply_development_policy(original)
    deferred = mode == "deferred" and integration != "none"
    assert result["integration"] == ("deferred" if deferred else integration)
    assert result["required_integration"] == integration
    assert result["postgresql_deferred"] == str(deferred).lower()
    assert original["integration"] == integration
    for key in ("history", "destructive", "deleted_count", "dependency_review"):
        assert result[key] == original[key]
    if deferred:
        for key in ("documentation", "frontend", "python", "packaging", "security"):
            assert result[key] == "true"
    else:
        assert result["python"] == "false"


def test_unknown_original_route_cannot_be_hidden_by_deferral():
    with pytest.raises(ValueError, match="Unknown"):
        policy.apply_development_policy({"integration": "broken"})


@pytest.mark.parametrize(
    ("mode", "command", "exit_code"),
    [
        ("deferred", "mode", 0),
        ("required", "mode", 0),
        ("deferred", "require-full", 1),
        ("required", "require-full", 0),
    ],
)
def test_full_acceptance_fence_and_restoration(
    monkeypatch, capsys, mode, command, exit_code
):
    monkeypatch.setattr(policy, "postgresql_policy_mode", lambda: mode)
    monkeypatch.setattr("sys.argv", ["policy", command])
    assert policy.main() == exit_code
    assert ("Restore" if exit_code else mode) in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["required", "deferred"])
def test_real_plan_entrypoint_keeps_destructive_review_separate(
    monkeypatch, capsys, mode
):
    monkeypatch.setattr(policy, "postgresql_policy_mode", lambda: mode)
    monkeypatch.setattr(
        ci_changes,
        "git_changes",
        lambda *_: (
            ci_changes.ChangedFile(
                PurePosixPath("src/maru/authorization/catalog.py"), "D"
            ),
        ),
    )
    assert ci_changes.main(["plan", "--base", "base", "--head", "head"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["integration"] == ("full" if mode == "required" else "deferred")
    assert result["required_integration"] == "full"
    assert result["history"] == "all"
    assert result["destructive_approved"] == "false"


def test_workflows_keep_non_database_acceptance_and_fence_database_startup():
    workflows = ROOT / ".github/workflows"
    pr = yaml.safe_load((workflows / "ci.yml").read_text())["jobs"]
    assert "integration != 'full'" in pr["quality"]["if"]
    assert "integration != 'full'" in pr["unit"]["if"]
    assert "integration == 'full'" in pr["full"]["if"]
    assert "integration == 'targeted'" in pr["targeted-integration"]["if"]
    gate = next(
        step
        for step in pr["pr-gate"]["steps"]
        if step["name"] == "Require the selected acceptance path"
    )
    for contract in (
        "needs.quality.result != 'success'",
        "needs.unit.result != 'success'",
        "postgresql-deferred != 'true'",
        "!contains(fromJSON",
    ):
        assert contract in gate["if"]
    full = yaml.safe_load((workflows / "_full-ci.yml").read_text())["jobs"]
    preflight = full["preflight"]["steps"]
    fence = next(
        index
        for index, step in enumerate(preflight)
        if "require-full" in step.get("run", "")
    )
    plan = next(
        index
        for index, step in enumerate(preflight)
        if step.get("id") == "database-plan"
    )
    assert fence < plan
    nightly = (workflows / "full-ci.yml").read_text()
    assert (
        "POSTGRESQL_POLICY=$(python scripts/ci_development_policy.py mode)" in nightly
    )
    assert nightly.index('"$POSTGRESQL_POLICY" == "deferred"') < nightly.index(
        '"$EVENT_NAME" == "workflow_dispatch"'
    )
    assert 'echo "run_full=false"' in nightly


def test_local_default_does_not_resolve_docker_or_claim_combined_coverage():
    dispatcher = (ROOT / "scripts/certify.ps1").read_text()
    assert dispatcher.index('if ($PolicyMode -eq "deferred")') < dispatcher.index(
        "$Docker ="
    )
    assert 'if ($Mode -ne "Auto")' in dispatcher
    fast = (ROOT / "scripts/certify_deferred.ps1").read_text()
    assert '"pytest", "tests/unit"' in fast
    assert 'result = "postgresql_deferred"' in fast
    assert "postgresql_executed = $false" in fast
    assert "combined_branch_coverage = $null" in fast
    assert "isolated_postgres_instances = 0" in fast
    assert "run_postgres" not in fast
    assert '"docker"' not in fast
    assert 'check.ps1") -SkipPythonTests' in fast


def test_programme_activation_cannot_be_introduced_while_acceptance_is_deferred():
    if policy.postgresql_policy_mode() == "deferred":
        assert all(
            code != "programme_operations" for code, _version in ADOPTION_PROFILES
        )
