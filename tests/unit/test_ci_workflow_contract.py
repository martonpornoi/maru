from __future__ import annotations

import json
import re
import runpy
import tomllib
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
MANUAL_FULL_WORKFLOW = WORKFLOW_DIRECTORY / "full-ci.yml"
DESTRUCTIVE_REVIEW_WORKFLOW = WORKFLOW_DIRECTORY / "destructive-review.yml"
RELEASE_WORKFLOW = WORKFLOW_DIRECTORY / "release.yml"
PAGES_WORKFLOW = WORKFLOW_DIRECTORY / "pages.yml"
LOCAL_CHECK_PATH = REPOSITORY_ROOT / "scripts" / "check.ps1"
LOCAL_CERTIFICATION_PATH = REPOSITORY_ROOT / "scripts" / "certify.ps1"
PRE_PUSH_HOOK_PATH = REPOSITORY_ROOT / ".githooks" / "pre-push"
ACTIONS_ALLOWLIST_PATH = REPOSITORY_ROOT / ".github" / "actions-allowlist.json"
ACTIONS_TRANSITIVE_REFERENCES_PATH = (
    REPOSITORY_ROOT / ".github" / "actions-transitive-references.json"
)
PAGES_SETTINGS_PATH = REPOSITORY_ROOT / ".github" / "pages.json"
PAGES_ENVIRONMENT_PATH = (
    REPOSITORY_ROOT / ".github" / "environments" / "github-pages.json"
)
PAGES_BRANCH_POLICY_PATH = (
    REPOSITORY_ROOT / ".github" / "environments" / "github-pages-main-policy.json"
)


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
    validated_references = validate_actions_allowlist()
    assert set(allowlist["patterns_allowed"]) == validated_references
    assert external_references <= validated_references


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


def test_actions_allowlist_validator_tracks_audited_transitive_actions(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    parent = f"example/composite@{'a' * 40}"
    nested = f"example/nested@{'b' * 40}"
    (workflows / "check.yml").write_text(
        f"name: Check\njobs:\n  test:\n    steps:\n      - uses: {parent}\n",
        encoding="utf-8",
    )
    allowlist = tmp_path / "actions-allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "github_owned_allowed": False,
                "verified_allowed": False,
                "patterns_allowed": [parent, nested],
            }
        ),
        encoding="utf-8",
    )
    transitive_references = tmp_path / "actions-transitive-references.json"
    transitive_references.write_text(
        json.dumps({parent: [nested]}),
        encoding="utf-8",
    )

    assert validate_actions_allowlist(
        workflows,
        allowlist,
        transitive_references,
    ) == frozenset({parent, nested})


def test_actions_allowlist_validator_rejects_unused_transitive_parent(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    direct = f"example/direct@{'a' * 40}"
    unused_parent = f"example/composite@{'b' * 40}"
    nested = f"example/nested@{'c' * 40}"
    (workflows / "check.yml").write_text(
        f"name: Check\njobs:\n  test:\n    steps:\n      - uses: {direct}\n",
        encoding="utf-8",
    )
    allowlist = tmp_path / "actions-allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "github_owned_allowed": False,
                "verified_allowed": False,
                "patterns_allowed": [direct, nested],
            }
        ),
        encoding="utf-8",
    )
    transitive_references = tmp_path / "actions-transitive-references.json"
    transitive_references.write_text(
        json.dumps({unused_parent: [nested]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="parent is not used directly"):
        validate_actions_allowlist(workflows, allowlist, transitive_references)


def test_pull_request_workflow_is_change_aware_with_one_stable_gate() -> None:
    workflow = _workflow(PR_WORKFLOW)
    jobs = yaml.safe_load(workflow)["jobs"]

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
    assert set(jobs) == {
        "changes",
        "repository-safety",
        "quality",
        "unit",
        "targeted-integration",
        "full",
        "pr-gate",
    }

    assert "name: PR gate" in workflow
    assert "ready_for_review" in workflow
    assert "converted_to_draft" in workflow
    assert "Keep drafts outside merge acceptance" in workflow
    assert "Mark the pull request ready to run authoritative acceptance" in workflow
    assert "github.event.pull_request.draft == true" in workflow
    assert "\n  push:" not in workflow
    assert "scripts/ci_changes.py plan" in workflow
    assert jobs["changes"]["outputs"]["packaging"] == (
        "${{ steps.plan.outputs.packaging }}"
    )
    assert jobs["changes"]["outputs"]["dependency-review"] == (
        "${{ steps.plan.outputs.dependency_review }}"
    )
    assert "destructive-change-reviewed" in workflow
    assert "needs.changes.outputs.integration == 'targeted'" in workflow
    for job_name in ("quality", "unit", "targeted-integration", "full"):
        assert jobs[job_name]["needs"] == ["changes", "repository-safety"]
        assert "github.event.pull_request.draft == false" in jobs[job_name]["if"]
    assert jobs["repository-safety"]["needs"] == "changes"
    assert (
        jobs["repository-safety"]["if"]
        == "${{ github.event.pull_request.draft == false }}"
    )
    assert jobs["pr-gate"]["if"] == "${{ always() }}"
    draft_step = next(
        step
        for step in jobs["pr-gate"]["steps"]
        if step.get("name") == "Keep drafts outside merge acceptance"
    )
    assert draft_step["if"] == "${{ github.event.pull_request.draft == true }}"
    assert "exit 1" in draft_step["run"]
    change_steps = jobs["changes"]["steps"]
    setup_index = next(
        index
        for index, step in enumerate(change_steps)
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    )
    plan_index = next(
        index
        for index, step in enumerate(change_steps)
        if step.get("name") == "Build fail-closed CI plan"
    )
    assert setup_index < plan_index
    plan_step = change_steps[plan_index]
    labels_expression = plan_step["env"]["PR_LABELS_JSON"]
    assert "github.event.action == 'labeled'" in labels_expression
    assert "github.event.label.name == 'destructive-change-reviewed'" in (
        labels_expression
    )
    assert "github.actor == github.repository_owner" in labels_expression
    assert "'[]'" in labels_expression
    assert "uses: ./.github/workflows/_full-ci.yml" in workflow
    assert "path: ~/.cache/uv" in workflow
    assert workflow.count("image: postgres:17.11-alpine@sha256:") == 1
    assert "self-hosted" not in workflow
    license_step = next(
        step
        for step in jobs["quality"]["steps"]
        if step.get("name") == "Distribution license contracts"
    )
    assert (
        "uv run pytest tests/unit/test_package_licensing.py \\\n"
        "  tests/unit/test_release_metadata.py -q"
    ) in license_step["run"]
    assert "if" not in license_step
    package_step = next(
        step
        for step in jobs["quality"]["steps"]
        if step.get("name") == "Build and inspect Python distributions"
    )
    assert "uv build --out-dir .ci-distributions" in package_step["run"]
    assert "scripts/verify_package_artifacts.py" in package_step["run"]
    assert package_step["if"] == ("${{ needs.changes.outputs.packaging == 'true' }}")
    assert (
        "git ls-files --others --exclude-standard -- "
        "../../src/maru/core/static/staff-console"
    ) in workflow


def test_dependency_review_is_read_only_conditional_and_fail_fast() -> None:
    workflow_definition = yaml.safe_load(_workflow(PR_WORKFLOW))
    change_steps = workflow_definition["jobs"]["changes"]["steps"]
    plan_index = next(
        index
        for index, step in enumerate(change_steps)
        if step.get("name") == "Build fail-closed CI plan"
    )
    dependency_review_index = next(
        index
        for index, step in enumerate(change_steps)
        if step.get("name") == "Review introduced dependency graph changes"
    )
    dependency_review_step = change_steps[dependency_review_index]

    assert plan_index < dependency_review_index
    assert dependency_review_step["if"] == (
        "${{ github.event.pull_request.draft == false && "
        "steps.plan.outputs.dependency_review == 'true' }}"
    )
    assert dependency_review_step["uses"] == (
        "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294"
    )
    assert dependency_review_step["with"] == {
        "fail-on-severity": "moderate",
        "fail-on-scopes": "runtime, development, unknown",
        "vulnerability-check": "true",
        "license-check": "false",
        "comment-summary-in-pr": "never",
        "show-openssf-scorecard": "false",
        "show-patched-versions": "true",
    }
    assert workflow_definition["permissions"] == {"contents": "read"}
    pr_gate = workflow_definition["jobs"]["pr-gate"]
    assert "changes" in pr_gate["needs"]
    selected_path_step = next(
        step
        for step in pr_gate["steps"]
        if step.get("name") == "Require the selected acceptance path"
    )
    assert "needs.changes.result != 'success'" in selected_path_step["if"]


def test_full_workflow_parallelizes_quality_and_uses_eight_measured_shards() -> None:
    workflow = _workflow(FULL_WORKFLOW)
    jobs = yaml.safe_load(workflow)["jobs"]

    assert "workflow_call:" in workflow
    for job in ("preflight", "static", "documentation", "contracts", "security"):
        assert re.search(rf"^  {job}:$", workflow, re.MULTILINE)
    assert "name: Locked inputs and Actions policy" in workflow
    assert "python -m pip install uv==0.11.29 PyYAML==6.0.3" in workflow
    assert "uv lock --check" in workflow
    assert "python scripts/validate_actions_allowlist.py" in workflow
    assert workflow.count("needs: preflight") == 4
    assert jobs["unit"]["needs"] == ["static", "security"]
    assert jobs["integration"]["needs"] == ["static", "security"]
    license_step = next(
        step
        for step in jobs["static"]["steps"]
        if step.get("name") == "Distribution license contracts"
    )
    assert "if" not in license_step
    assert "tests/unit/test_package_licensing.py" in license_step["run"]
    assert "tests/unit/test_release_metadata.py" in license_step["run"]
    package_step = next(
        step
        for step in jobs["static"]["steps"]
        if step.get("name") == "Build and inspect Python distributions"
    )
    assert "uv build --out-dir .ci-distributions" in package_step["run"]
    assert "scripts/verify_package_artifacts.py" in package_step["run"]
    assert "if" not in package_step
    assert "shard: [1, 2, 3, 4, 5, 6, 7, 8]" in workflow
    assert "--shard-count 8" in workflow
    assert "scripts/run_ci_test_shard.py" in workflow
    assert "coverage combine .ci-artifacts/coverage-parts" in workflow
    assert "coverage report --fail-under=90" in workflow
    assert "name: Full CI gate" in workflow
    assert workflow.count("image: postgres:17.11-alpine@sha256:") == 1
    assert "self-hosted" not in workflow
    assert (
        "git ls-files --others --exclude-standard -- "
        "../../src/maru/core/static/staff-console"
    ) in workflow


def test_manual_full_acceptance_does_not_claim_merge_queue_support() -> None:
    workflow = _workflow(MANUAL_FULL_WORKFLOW)

    assert "workflow_dispatch:" in workflow
    assert "merge_group:" not in workflow
    assert "uses: ./.github/workflows/_full-ci.yml" in workflow


def test_destructive_review_is_cleared_without_executing_pull_request_code() -> None:
    workflow = _workflow(DESTRUCTIVE_REVIEW_WORKFLOW)
    jobs = yaml.safe_load(workflow)["jobs"]
    job = jobs["clear-destructive-review"]

    assert "pull_request_target:" in workflow
    assert (
        "types: [synchronize, reopened, ready_for_review, converted_to_draft]"
        in workflow
    )
    assert "actions/checkout@" not in workflow
    assert job["if"] == (
        "${{ contains(github.event.pull_request.labels.*.name, "
        "'destructive-change-reviewed') }}"
    )
    assert job["steps"][0]["env"]["PR_NUMBER"] == (
        "${{ github.event.pull_request.number }}"
    )
    assert job["steps"][0]["run"].startswith("gh api --method DELETE")
    assert yaml.safe_load(workflow)["permissions"] == {"issues": "write"}


def test_checkout_credentials_are_not_persisted() -> None:
    for path in sorted(WORKFLOW_DIRECTORY.glob("*.yml")):
        jobs = yaml.safe_load(_workflow(path))["jobs"]
        for job in jobs.values():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    assert step.get("with", {}).get("persist-credentials") is False, (
                        path
                    )


def test_staff_console_build_rejects_untracked_generated_assets() -> None:
    generated_path = "../../src/maru/core/static/staff-console"
    untracked_command = "git ls-files --others --exclude-standard -- " + generated_path
    for path in (PR_WORKFLOW, FULL_WORKFLOW):
        workflow = _workflow(path)
        assert untracked_command in workflow
        assert "if ! UNTRACKED_GENERATED_FILES=$(git ls-files" in workflow
        assert "Unable to inspect generated Staff Console output." in workflow
        assert 'if test -n "$UNTRACKED_GENERATED_FILES"' in workflow

    local_check = LOCAL_CHECK_PATH.read_text(encoding="utf-8")
    assert '"ls-files", "--others", "--exclude-standard"' in local_check
    assert "Generated Staff Console output is not completely committed." in (
        local_check
    )


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
            "uv run sphinx-build -W --keep-going --fresh-env -j auto "
            "-d docs/_build/doctrees -b html docs docs/_build/html",
            '"run", "sphinx-build", "-W", "--keep-going", "--fresh-env"',
        ),
    ):
        assert workflow_command in workflow
        assert local_fragment in local_check

    assert "name: contributor-documentation" in workflow
    assert "retention-days: 7" in workflow
    assert '"build", "--out-dir", $PackageDistributionDirectory' in local_check
    assert '"scripts/verify_package_artifacts.py"' in local_check


def test_pages_workflow_is_main_only_locked_and_least_privilege() -> None:
    workflow = _workflow(PAGES_WORKFLOW)
    jobs = yaml.safe_load(workflow)["jobs"]
    build = jobs["build"]
    deploy = jobs["deploy"]

    assert "push:\n    branches: [main]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "pull_request_target:" not in workflow
    assert "merge_group:" not in workflow
    assert "self-hosted" not in workflow
    assert "postgres:" not in workflow
    assert "secrets:" not in workflow
    assert "group: pages" in workflow
    assert "cancel-in-progress: false" in workflow
    assert yaml.safe_load(workflow)["permissions"] == {"contents": "read"}

    assert build["permissions"] == {"contents": "read", "pages": "read"}
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert deploy["needs"] == "build"
    assert deploy["environment"] == {
        "name": "github-pages",
        "url": "${{ steps.deployment.outputs.page_url }}",
    }
    assert '"$GITHUB_REF" != "refs/heads/main"' in workflow
    assert "github.ref_protected" in workflow
    for job in (build, deploy):
        assert any(
            step.get("name") == "Require exact current main commit"
            for step in job["steps"]
        )
    assert "uv==0.11.29 PyYAML==6.0.3" in workflow
    assert "uv lock --check" in workflow
    assert "python scripts/validate_actions_allowlist.py" in workflow
    assert "uv sync --all-groups --locked" in workflow
    for command in (
        "uv run pydoclint src scripts",
        "uv run python scripts/validate_python_docstrings.py src scripts",
        "uv run python scripts/validate_docs.py",
        "uv run sphinx-build -W --keep-going --fresh-env -j auto",
    ):
        assert command in workflow
    assert '"$PAGES_BASE_URL" =~ ^https://[^/]+(/.*)?$' in workflow
    assert 'NORMALIZED_BASE_URL="${PAGES_BASE_URL%/}/"' in workflow
    assert '-D "html_baseurl=$NORMALIZED_BASE_URL"' in workflow
    assert '-d "$RUNNER_TEMP/maru-pages-doctrees"' in workflow
    assert '-b html docs "$RUNNER_TEMP/maru-pages-html"' in workflow
    assert "docs/_build/html" not in workflow
    assert "maru-pages-html/index.html" in workflow
    assert "maru-pages-html/autoapi/maru/index.html" in workflow
    assert "SITE_BYTES >= 1000000000" in workflow
    assert "retention-days: 1" in workflow
    assert "include-hidden-files: false" in workflow
    assert workflow.count("pages: write") == 1
    assert workflow.count("id-token: write") == 1

    configure_step = next(
        step for step in build["steps"] if step.get("name") == "Configure GitHub Pages"
    )
    assert configure_step["with"] == {"enablement": False}
    upload_step = next(
        step
        for step in build["steps"]
        if step.get("name") == "Upload generated Pages artifact"
    )
    assert upload_step["with"] == {
        "path": "${{ runner.temp }}/maru-pages-html",
        "retention-days": 1,
        "include-hidden-files": False,
    }
    deployment_step = next(
        step
        for step in deploy["steps"]
        if step.get("name") == "Deploy generated documentation"
    )
    assert deployment_step == {
        "name": "Deploy generated documentation",
        "id": "deployment",
        "uses": ("actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128"),
    }

    expected_actions = {
        "actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d",
        "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9",
        "actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128",
    }
    assert expected_actions <= external_action_references(WORKFLOW_DIRECTORY)
    transitive_references = json.loads(
        ACTIONS_TRANSITIVE_REFERENCES_PATH.read_text(encoding="utf-8")
    )
    assert transitive_references == {
        "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9": [
            "actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f"
        ]
    }


def test_sphinx_metadata_comes_from_project_version() -> None:
    project_metadata = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    sphinx_metadata = runpy.run_path(str(REPOSITORY_ROOT / "docs" / "conf.py"))
    expected_version = project_metadata["project"]["version"]

    assert sphinx_metadata["release"] == expected_version
    assert sphinx_metadata["version"] == expected_version
    assert sphinx_metadata["html_title"] == (
        f"Maru {expected_version} contributor documentation"
    )
    assert sphinx_metadata["html_theme_options"]["announcement"].startswith(
        f"Maru {expected_version} is under active development"
    )
    assert sphinx_metadata["mermaid_version"] == "11.16.1"
    assert sphinx_metadata["mermaid_include_elk"] == ""
    assert sphinx_metadata["d3_version"] == "7.9.0"


def test_pages_external_settings_have_exact_checked_in_desired_state() -> None:
    pages_settings = json.loads(PAGES_SETTINGS_PATH.read_text(encoding="utf-8"))
    environment = json.loads(PAGES_ENVIRONMENT_PATH.read_text(encoding="utf-8"))
    branch_policy = json.loads(PAGES_BRANCH_POLICY_PATH.read_text(encoding="utf-8"))

    assert pages_settings == {"build_type": "workflow"}
    assert environment == {
        "wait_timer": 0,
        "prevent_self_review": False,
        "reviewers": [],
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        },
        "can_admins_bypass": False,
    }
    assert branch_policy == {"name": "main", "type": "branch"}


def test_local_certification_preserves_database_isolation_and_total_coverage() -> None:
    certification = LOCAL_CERTIFICATION_PATH.read_text(encoding="utf-8")

    for required in (
        "[int] $IntegrationShards = 8",
        "postgres:17.11-alpine@sha256:",
        '"maru-cert-integration-$Shard-$RunToken"',
        "maru_unit_no_database",
        '"scripts/run_ci_test_shard.py"',
        '"coverage", "combine"',
        '"coverage", "report", "--fail-under=90"',
        "Certification requires a clean working tree",
        'Join-Path (Join-Path $ArtifactRoot "tmp") $Name',
        "TEMP = $TemporaryDirectory",
        "TMP = $TemporaryDirectory",
        "TMPDIR = $TemporaryDirectory",
        'result = "success"',
    ):
        assert required in certification

    assert '"--shard-count", "$IntegrationShards"' in certification
    assert '"maru-cert-unit-$RunToken"' not in certification
    assert "isolated_postgres_instances = $IntegrationShards" in certification
    assert (
        certification.count(
            '& $Git "status" "--porcelain"\n    ) -join [Environment]::NewLine).Trim()'
        )
        == 2
    )
    assert "    ) | Out-Null\n\n    $Healthy = $false" in certification


def test_repository_push_guard_blocks_main_deletion_and_non_fast_forward() -> None:
    hook = PRE_PUSH_HOOK_PATH.read_text(encoding="utf-8")

    assert 'remote_ref" = "refs/heads/main' in hook
    assert "blocks branch deletion" in hook
    assert "git merge-base --is-ancestor" in hook


def test_release_requires_exact_source_unique_calver_and_evidence() -> None:
    workflow = _workflow(RELEASE_WORKFLOW)
    jobs = yaml.safe_load(workflow)["jobs"]

    for required in (
        "name: Validate release request",
        "Reject invalid release inputs before certification",
        "needs: validate-request",
        "needs: [validate-request, certify]",
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

    assert jobs["validate-request"]["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert jobs["certify"]["needs"] == "validate-request"
    assert jobs["publish"]["needs"] == ["validate-request", "certify"]
    assert "org.opencontainers.image.licenses" not in workflow
    assert "rm -rf release-assets/docs/.doctrees" in workflow
    assert "cp LICENSE THIRD_PARTY_NOTICES.md release-assets/docs/" in workflow
    assert (
        "cp openapi.yaml uv.lock LICENSE THIRD_PARTY_NOTICES.md release-assets/"
        in workflow
    )
    assert workflow.count("release-assets/THIRD_PARTY_NOTICES.md") == 3
    validation_run = jobs["validate-request"]["steps"][0]["run"]
    assert 'gh pr view "$RELEASE_PR" --repo "$GITHUB_REPOSITORY"' in validation_run
    assert "must be merged into main at the exact workflow commit" in validation_run


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

    assert main_rules["name"] == "Protect main"
    assert set(main_rules) == {
        "name",
        "target",
        "conditions",
        "enforcement",
        "bypass_actors",
        "rules",
    }
    assert main_rules["target"] == "branch"
    assert main_rules["conditions"] == {
        "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}
    }
    assert main_rules["enforcement"] == "active"
    assert main_rules["bypass_actors"] == []
    rules_by_type = {rule["type"]: rule for rule in main_rules["rules"]}
    assert len(rules_by_type) == len(main_rules["rules"])
    assert set(rules_by_type) == {
        "deletion",
        "non_fast_forward",
        "required_linear_history",
        "pull_request",
        "required_status_checks",
        "code_scanning",
    }
    for simple_rule in ("deletion", "non_fast_forward", "required_linear_history"):
        assert rules_by_type[simple_rule] == {"type": simple_rule}
    assert rules_by_type["pull_request"]["parameters"] == {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": False,
        "required_review_thread_resolution": True,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "allowed_merge_methods": ["squash"],
    }
    status_rule = rules_by_type["required_status_checks"]
    assert status_rule["parameters"] == {
        "strict_required_status_checks_policy": True,
        "do_not_enforce_on_create": False,
        "required_status_checks": [{"context": "PR gate", "integration_id": 15368}],
    }
    code_scanning_rule = rules_by_type["code_scanning"]
    assert code_scanning_rule["parameters"] == {
        "code_scanning_tools": [
            {
                "tool": "CodeQL",
                "alerts_threshold": "errors",
                "security_alerts_threshold": "medium_or_higher",
            }
        ]
    }
    assert tag_rules["name"] == "Protect release tags"
    assert set(tag_rules) == {
        "name",
        "target",
        "conditions",
        "enforcement",
        "bypass_actors",
        "rules",
    }
    assert tag_rules["target"] == "tag"
    assert tag_rules["enforcement"] == "active"
    assert tag_rules["bypass_actors"] == []
    assert tag_rules["conditions"] == {
        "ref_name": {"include": ["refs/tags/v*"], "exclude": []}
    }
    tag_rules_by_type = {rule["type"]: rule for rule in tag_rules["rules"]}
    assert len(tag_rules_by_type) == len(tag_rules["rules"])
    assert set(tag_rules_by_type) == {
        "deletion",
        "update",
        "non_fast_forward",
    }
    assert tag_rules_by_type["deletion"] == {"type": "deletion"}
    assert tag_rules_by_type["non_fast_forward"] == {"type": "non_fast_forward"}
    assert tag_rules_by_type["update"] == {
        "type": "update",
        "parameters": {"update_allows_fetch_and_merge": False},
    }

    for relative_path in (
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
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
