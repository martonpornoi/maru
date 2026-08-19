from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"
PR_WORKFLOW = WORKFLOW_DIRECTORY / "ci.yml"
FULL_WORKFLOW = WORKFLOW_DIRECTORY / "_full-ci.yml"
RELEASE_WORKFLOW = WORKFLOW_DIRECTORY / "release.yml"
LOCAL_CHECK_PATH = REPOSITORY_ROOT / "scripts" / "check.ps1"


def _workflow(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_workflow_parses_and_external_action_is_immutable() -> None:
    workflow_paths = tuple(sorted(WORKFLOW_DIRECTORY.glob("*.yml")))

    assert workflow_paths
    for path in workflow_paths:
        workflow = _workflow(path)
        assert yaml.safe_load(workflow)
        references = re.findall(r"^\s*- uses: ([^\s#]+)", workflow, re.MULTILINE)
        for reference in references:
            if reference.startswith("./"):
                continue
            _, separator, revision = reference.rpartition("@")
            assert separator == "@", (path, reference)
            assert re.fullmatch(r"[0-9a-f]{40}", revision), (path, reference)


def test_pull_request_workflow_is_change_aware_with_one_stable_gate() -> None:
    workflow = _workflow(PR_WORKFLOW)

    for job in (
        "changes",
        "repository-safety",
        "quality",
        "unit",
        "targeted-integration",
        "full",
        "pr-gate",
    ):
        assert re.search(rf"^  {re.escape(job)}:$", workflow, re.MULTILINE)

    assert "name: PR gate" in workflow
    assert "scripts/ci_changes.py plan" in workflow
    assert "destructive-change-reviewed" in workflow
    assert "needs.changes.outputs.integration == 'targeted'" in workflow
    assert "uses: ./.github/workflows/_full-ci.yml" in workflow
    assert workflow.count("image: postgres:17.11-alpine@sha256:") == 2


def test_full_workflow_parallelizes_quality_and_uses_eight_measured_shards() -> None:
    workflow = _workflow(FULL_WORKFLOW)

    assert "workflow_call:" in workflow
    for job in ("static", "documentation", "contracts", "security"):
        assert re.search(rf"^  {job}:$", workflow, re.MULTILINE)
    assert workflow.count("needs: security") == 2
    assert "shard: [1, 2, 3, 4, 5, 6, 7, 8]" in workflow
    assert "--shard-count 8" in workflow
    assert "scripts/run_ci_test_shard.py" in workflow
    assert "coverage combine .ci-artifacts/coverage-parts" in workflow
    assert "coverage report --fail-under=90" in workflow
    assert "name: Full CI gate" in workflow
    assert workflow.count("image: postgres:17.11-alpine@sha256:") == 2


def test_documentation_contract_matches_local_and_full_acceptance() -> None:
    workflow = _workflow(FULL_WORKFLOW)
    local_check = LOCAL_CHECK_PATH.read_text(encoding="utf-8")

    for command in (
        "uv run pydoclint src scripts",
        "uv run python scripts/validate_python_docstrings.py src scripts",
        (
            "uv run sphinx-build -W --keep-going --fresh-env -j auto -b html "
            "docs docs/_build/html"
        ),
    ):
        assert command in workflow
        assert command in local_check

    assert "name: contributor-documentation" in workflow
    assert "retention-days: 7" in workflow


def test_release_requires_exact_source_unique_calver_and_evidence() -> None:
    workflow = _workflow(RELEASE_WORKFLOW)

    for required in (
        "uses: ./.github/workflows/_full-ci.yml",
        "scripts/release_metadata.py",
        'MERGE_SHA" != "$GITHUB_SHA',
        "pyproject.toml version",
        "Git tag $TAG already exists",
        "Container image $IMAGE already exists",
        "provenance: mode=max",
        "sbom: true",
        "actions/attest-build-provenance@",
        "release-manifest.json",
        "SHA256SUMS",
        "gh release create",
    ):
        assert required in workflow


def test_rulesets_and_public_collaboration_files_are_present() -> None:
    main_rules = json.loads(
        (REPOSITORY_ROOT / ".github" / "rulesets" / "main.json").read_text(
            encoding="utf-8"
        )
    )
    tag_rules = json.loads(
        (REPOSITORY_ROOT / ".github" / "rulesets" / "release-tags.json").read_text(
            encoding="utf-8"
        )
    )

    assert main_rules["enforcement"] == "active"
    assert main_rules["bypass_actors"] == []
    status_rule = next(
        rule for rule in main_rules["rules"] if rule["type"] == "required_status_checks"
    )
    assert status_rule["parameters"]["required_status_checks"] == [
        {"context": "PR gate"}
    ]
    assert {rule["type"] for rule in tag_rules["rules"]} >= {
        "deletion",
        "update",
    }

    for relative_path in (
        "LICENSE",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "SUPPORT.md",
        "GOVERNANCE.md",
        "CHANGELOG.md",
        ".github/CODEOWNERS",
        ".github/pull_request_template.md",
        ".github/dependabot.yml",
        ".github/release.yml",
    ):
        assert (REPOSITORY_ROOT / relative_path).is_file(), relative_path
