from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from scripts.validate_actions_allowlist import (
    external_action_references,
    validate_actions_allowlist,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"
PR_WORKFLOW = WORKFLOW_DIRECTORY / "ci.yml"
FULL_WORKFLOW = WORKFLOW_DIRECTORY / "_full-ci.yml"
RELEASE_WORKFLOW = WORKFLOW_DIRECTORY / "release.yml"
LOCAL_CHECK_PATH = REPOSITORY_ROOT / "scripts" / "check.ps1"
LOCAL_CERTIFICATION_PATH = REPOSITORY_ROOT / "scripts" / "certify.ps1"
PRE_PUSH_HOOK_PATH = REPOSITORY_ROOT / ".githooks" / "pre-push"
ACTIONS_ALLOWLIST_PATH = REPOSITORY_ROOT / ".github" / "actions-allowlist.json"


def _workflow(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_workflow_parses_and_external_action_is_immutable() -> None:
    workflow_paths = tuple(
        sorted(
            (*WORKFLOW_DIRECTORY.glob("*.yml"), *WORKFLOW_DIRECTORY.glob("*.yaml")),
            key=lambda path: path.as_posix(),
        )
    )
    assert workflow_paths
    for path in workflow_paths:
        workflow = _workflow(path)
        assert yaml.safe_load(workflow)

    external_references = external_action_references(WORKFLOW_DIRECTORY)
    for reference in external_references:
        _, separator, revision = reference.rpartition("@")
        assert separator == "@", reference
        assert re.fullmatch(r"[0-9a-f]{40}", revision), reference

    allowlist = json.loads(ACTIONS_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert allowlist["github_owned_allowed"] is False
    assert allowlist["verified_allowed"] is False
    assert set(allowlist["patterns_allowed"]) == external_references
    assert validate_actions_allowlist() == external_references


def test_actions_allowlist_validator_finds_quoted_and_flow_mapping_keys(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    quoted_reference = f"example/quoted@{'a' * 40}"
    flow_reference = f"example/flow@{'b' * 40}"
    (workflows / "check.yml").write_text(
        "name: Check\n"
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        f'      - "uses": {quoted_reference}\n'
        f"      - {{uses: {flow_reference}}}\n",
        encoding="utf-8",
    )
    allowlist = tmp_path / "actions-allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "github_owned_allowed": False,
                "verified_allowed": False,
                "patterns_allowed": [quoted_reference, flow_reference],
            }
        ),
        encoding="utf-8",
    )

    assert validate_actions_allowlist(workflows, allowlist) == frozenset(
        {quoted_reference, flow_reference}
    )


def test_actions_allowlist_validator_rejects_missing_and_unused_entries(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    reference = f"example/action@{'a' * 40}"
    (workflows / "check.yml").write_text(
        f"name: Check\njobs:\n  test:\n    steps:\n      - uses: {reference}\n",
        encoding="utf-8",
    )
    allowlist = tmp_path / "actions-allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "github_owned_allowed": False,
                "verified_allowed": False,
                "patterns_allowed": [f"unused/action@{'b' * 40}"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match=r"missing=.*example/action.*unused=.*unused/action"
    ):
        validate_actions_allowlist(workflows, allowlist)


def test_actions_allowlist_validator_rejects_mutable_references(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "check.yml").write_text(
        "name: Check\njobs:\n  test:\n    steps:\n      - uses: example/action@v1\n",
        encoding="utf-8",
    )
    allowlist = tmp_path / "actions-allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "github_owned_allowed": False,
                "verified_allowed": False,
                "patterns_allowed": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="workflow action is not immutable"):
        validate_actions_allowlist(workflows, allowlist)


def test_actions_allowlist_validator_rejects_duplicate_entries(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    reference = f"example/action@{'a' * 40}"
    (workflows / "check.yaml").write_text(
        f"name: Check\njobs:\n  test:\n    steps:\n      - uses: {reference}\n",
        encoding="utf-8",
    )
    allowlist = tmp_path / "actions-allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "github_owned_allowed": False,
                "verified_allowed": False,
                "patterns_allowed": [reference, reference],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate references"):
        validate_actions_allowlist(workflows, allowlist)


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
    assert "self-hosted" not in workflow


def test_full_workflow_parallelizes_quality_and_uses_eight_measured_shards() -> None:
    workflow = _workflow(FULL_WORKFLOW)

    assert "workflow_call:" in workflow
    for job in ("preflight", "static", "documentation", "contracts", "security"):
        assert re.search(rf"^  {job}:$", workflow, re.MULTILINE)
    assert "name: Locked inputs and Actions policy" in workflow
    assert "python -m pip install uv==0.11.29 PyYAML==6.0.3" in workflow
    assert "uv lock --check" in workflow
    assert "python scripts/validate_actions_allowlist.py" in workflow
    assert workflow.count("needs: preflight") == 4
    assert workflow.count("needs: security") == 2
    assert "shard: [1, 2, 3, 4, 5, 6, 7, 8]" in workflow
    assert "--shard-count 8" in workflow
    assert "scripts/run_ci_test_shard.py" in workflow
    assert "coverage combine .ci-artifacts/coverage-parts" in workflow
    assert "coverage report --fail-under=90" in workflow
    assert "name: Full CI gate" in workflow
    assert workflow.count("image: postgres:17.11-alpine@sha256:") == 2
    assert "self-hosted" not in workflow


def test_dependabot_creates_only_grouped_security_updates() -> None:
    configuration = yaml.safe_load(
        (REPOSITORY_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )
    updates = configuration["updates"]

    assert {update["package-ecosystem"] for update in updates} == {
        "uv",
        "npm",
        "github-actions",
    }
    for update in updates:
        assert update["open-pull-requests-limit"] == 0
        assert update["schedule"]["interval"] == "monthly"
        assert len(update["groups"]) == 1
        group = next(iter(update["groups"].values()))
        assert group == {
            "applies-to": "security-updates",
            "patterns": ["*"],
        }


def test_documentation_contract_matches_local_and_full_acceptance() -> None:
    workflow = _workflow(FULL_WORKFLOW)
    local_check = LOCAL_CHECK_PATH.read_text(encoding="utf-8")

    for workflow_command, local_fragment in (
        ("uv run pydoclint src scripts", '"run", "pydoclint", "src", "scripts"'),
        (
            "uv run python scripts/validate_python_docstrings.py src scripts",
            (
                '"run", "python", "scripts/validate_python_docstrings.py", '
                '"src", "scripts"'
            ),
        ),
        (
            "uv run sphinx-build -W --keep-going --fresh-env -j auto -b html "
            "docs docs/_build/html",
            '"run", "sphinx-build", "-W", "--keep-going", "--fresh-env"',
        ),
    ):
        assert workflow_command in workflow
        assert local_fragment in local_check

    assert "name: contributor-documentation" in workflow
    assert "retention-days: 7" in workflow


def test_local_certification_preserves_database_isolation_and_total_coverage() -> None:
    certification = LOCAL_CERTIFICATION_PATH.read_text(encoding="utf-8")

    for required in (
        "[int] $IntegrationShards = 8",
        "postgres:17.11-alpine@sha256:",
        '"maru-cert-unit-$RunToken"',
        '"maru-cert-integration-$Shard-$RunToken"',
        '"scripts/run_ci_test_shard.py"',
        '"coverage", "combine"',
        '"coverage", "report", "--fail-under=90"',
        "Certification requires a clean working tree",
        'result = "success"',
    ):
        assert required in certification

    assert '"--shard-count", "$IntegrationShards"' in certification
    assert "isolated_postgres_instances = $IntegrationShards + 1" in certification


def test_repository_push_guard_blocks_main_deletion_and_non_fast_forward() -> None:
    hook = PRE_PUSH_HOOK_PATH.read_text(encoding="utf-8")

    assert 'remote_ref" = "refs/heads/main' in hook
    assert "blocks branch deletion" in hook
    assert "git merge-base --is-ancestor" in hook


def test_release_requires_exact_source_unique_calver_and_evidence() -> None:
    workflow = _workflow(RELEASE_WORKFLOW)

    for required in (
        "uses: ./.github/workflows/_full-ci.yml",
        "scripts/release_metadata.py",
        "release_immutability_verified",
        "CURRENT_MAIN=$(git ls-remote --exit-code origin refs/heads/main",
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
        "--draft",
        "scripts/verify_release_evidence.py",
        "--expected-state draft",
        'gh release edit "$RELEASE_TAG" --draft=false',
        "--expected-state immutable",
        'gh release verify "$RELEASE_TAG"',
        "gh release verify-asset",
        "docker buildx imagetools inspect",
        "gh attestation verify",
        '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml"',
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
    assert status_rule["parameters"]["strict_required_status_checks_policy"] is True
    code_scanning_rule = next(
        rule for rule in main_rules["rules"] if rule["type"] == "code_scanning"
    )
    assert code_scanning_rule["parameters"]["code_scanning_tools"] == [
        {
            "tool": "CodeQL",
            "alerts_threshold": "errors",
            "security_alerts_threshold": "medium_or_higher",
        }
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
