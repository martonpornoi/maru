from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
LOCAL_CHECK_PATH = REPOSITORY_ROOT / "scripts" / "check.ps1"


def _workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_ci_has_stable_parallel_acceptance_jobs() -> None:
    workflow = _workflow()

    for job in (
        "static",
        "django-contracts",
        "frontend",
        "unit",
        "integration",
        "coverage",
        "security",
        "ci-gate",
    ):
        assert re.search(rf"^  {re.escape(job)}:$", workflow, re.MULTILINE)

    assert "merge_group:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "cancel-in-progress:" in workflow
    assert "needs:\n      - static" in workflow
    assert "name: CI gate" in workflow
    assert "fetch-depth: 0" in workflow
    assert 'git diff --check "$BASE_SHA" "$GITHUB_SHA"' in workflow


def test_ci_uses_canonical_production_settings_verifier() -> None:
    workflow = _workflow()
    local_check = LOCAL_CHECK_PATH.read_text(encoding="utf-8")

    assert "uv run python scripts/verify_production_settings.py" in workflow
    assert "uv run python scripts/verify_production_settings.py" in local_check
    assert "MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID" not in workflow
    assert "MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON" not in workflow


def test_ci_shards_integration_files_and_combines_coverage_once() -> None:
    workflow = _workflow()

    assert "fail-fast: false" in workflow
    assert "shard: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]" in workflow
    assert "--shard-count 12" in workflow
    assert "scripts/run_ci_test_shard.py" in workflow
    assert workflow.count("--cov-fail-under=0") == 2
    assert "coverage combine .ci-artifacts/coverage-parts" in workflow
    assert "coverage report --fail-under=90" in workflow
    assert workflow.count("include-hidden-files: true") == 2
    assert "--junitxml=reports/unit.xml" in workflow
    assert "--junitxml=reports/integration-${{ matrix.shard }}.xml" in workflow


def test_ci_pins_external_actions_and_postgresql_image() -> None:
    workflow = _workflow()
    action_references = re.findall(
        r"^\s*- uses: ([^\s#]+)",
        workflow,
        re.MULTILINE,
    )

    assert action_references
    for reference in action_references:
        _, separator, revision = reference.rpartition("@")
        assert separator == "@"
        assert re.fullmatch(r"[0-9a-f]{40}", revision)

    image_references = re.findall(
        r"^\s+image: (postgres:[^\s]+)",
        workflow,
        re.MULTILINE,
    )
    assert len(image_references) == 3
    assert len(set(image_references)) == 1
    assert re.fullmatch(
        r"postgres:17\.11-alpine@sha256:[0-9a-f]{64}",
        image_references[0],
    )
