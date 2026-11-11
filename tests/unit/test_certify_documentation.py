"""Keep the local prose-only route out of ordinary and high-risk changes."""

import json
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest
from scripts import certify_documentation as certification
from scripts.ci_changes import ChangedFile, classify_changes


def _change(path: str, status: str = "M") -> ChangedFile:
    return ChangedFile(PurePosixPath(path), status)


@pytest.mark.parametrize(
    "path",
    [
        "docs/project/CURRENT.md",
        "docs/development/guide.rst",
        ".agents/skills/maru-browser-rehearsal/SKILL.md",
        "README.md",
    ],
)
def test_added_or_modified_prose_keeps_the_hosted_plan(path):
    changes = (_change(path, "A"),)
    plan = certification.classify_documentation_changes(changes)
    assert plan is not None
    assert plan == classify_changes(changes)
    assert plan.integration == "none"


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("docs/operations/retired.md", "D"),
        ("docs/operations/renamed.md", "R100"),
        ("docs/conf.py", "M"),
        ("docs/example.md", "T"),
        ("docs/_static/client.js", "M"),
        ("scripts/certify.ps1", "M"),
        ("scripts/ci_changes.py", "M"),
        ("src/maru/workforce/README.md", "M"),
        ("src/maru/workforce/forms.py", "M"),
        ("frontends/staff-console/package.json", "M"),
        ("tests/unit/test_ci_changes.py", "A"),
        (".github/workflows/ci.yml", "M"),
        (".githooks/pre-push", "M"),
        ("uv.lock", "M"),
        ("unexpected.conf", "A"),
    ],
)
def test_a_document_cannot_hide_another_change(path, status):
    changes = (_change("docs/guide.md"), _change(path, status))
    assert certification.classify_documentation_changes(changes) is None


def test_empty_diff_is_not_documentation_certification():
    assert certification.classify_documentation_changes(()) is None


@pytest.fixture
def repository(tmp_path, monkeypatch):
    git = shutil.which("git")
    assert git is not None
    monkeypatch.chdir(tmp_path)
    for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        monkeypatch.delenv(variable, raising=False)

    def run(*args: str) -> str:
        return subprocess.check_output(  # noqa: S603 -- fixed Git and test repository
            [
                git,
                "-c",
                "user.name=Fictional Tester",
                "-c",
                "user.email=tester@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=.git/no-hooks",
                *args,
            ],
            text=True,
        ).strip()

    run("init", "--quiet", "--initial-branch=main")
    (tmp_path / ".gitignore").write_text(".tools/\n.local-ci/\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Baseline\n", encoding="utf-8")
    run("add", ".")
    run("commit", "--quiet", "-m", "Base")
    base = run("rev-parse", "HEAD")
    (tmp_path / "README.md").write_text("# Revised explanation\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "--quiet", "-m", "Change prose")
    return run, base, run("rev-parse", "HEAD")


def test_exact_documentation_candidate_and_dirty_checkout(repository):
    _, base, head = repository
    certification._require_exact_checkout(head)
    plan = certification._candidate_plan(base, head)
    assert plan is not None
    assert plan[0].packaging
    Path("uncommitted.txt").write_text(
        "Do not certify this checkout.", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="clean checkout"):
        certification._require_exact_checkout(head)


def test_non_ancestor_and_executable_documentation_stay_on_ordinary_path(repository):
    git, base, head = repository
    assert certification._candidate_plan(head, base) is None
    git("update-index", "--chmod=+x", "README.md")
    git("commit", "--quiet", "-m", "Change file mode")
    executable = git("rev-parse", "HEAD")
    assert certification._candidate_plan(base, executable) is None
    git("update-index", "--chmod=-x", "README.md")
    git("commit", "--quiet", "-m", "Restore regular mode")
    assert certification._candidate_plan(executable, git("rev-parse", "HEAD")) is None


def test_complete_tree_comparison_rejects_an_incomplete_path_inventory(
    repository, monkeypatch
):
    git, base, _ = repository
    Path("runtime.toml").write_text("enabled = true\n", encoding="utf-8")
    git("add", "runtime.toml")
    git("commit", "--quiet", "-m", "Mixed change")
    monkeypatch.setattr(
        certification, "git_changes", lambda *_args: (_change("README.md"),)
    )
    assert certification._candidate_plan(base, git("rev-parse", "HEAD")) is None


@pytest.mark.parametrize("returncode", [0, 7])
def test_documentation_receipts_preserve_prior_evidence_and_only_record_success(
    repository, tmp_path, monkeypatch, returncode
):
    _, base, head = repository
    previous = tmp_path / ".local-ci" / "certification.json"
    previous.parent.mkdir()
    previous.write_text("Original native receipt", encoding="utf-8")
    plan = certification._candidate_plan(base, head)
    assert plan is not None
    monkeypatch.setattr(
        certification,
        "_checks",
        lambda *_args: [
            ("fixture_gate", [sys.executable, "-c", f"raise SystemExit({returncode})"])
        ],
    )

    if returncode:
        with pytest.raises(RuntimeError, match=r"fixture_gate failed \(7\)"):
            certification._certify(tmp_path.resolve(), base, head, *plan, Path("uv"))
    else:
        receipt = certification._certify(
            tmp_path.resolve(), base, head, *plan, Path("uv")
        )
        result = json.loads(receipt.read_text(encoding="utf-8"))
        assert result["commit"] == head
        assert result["base_commit"] == base
        assert result["result"] == "documentation_success"
        assert result["gates"] == ["fixture_gate"]
        assert (
            result["postgresql"] == result["combined_branch_coverage"] == "not_selected"
        )
    outputs = list((tmp_path / ".tools" / "documentation-certification").iterdir())
    assert len(outputs) == 1
    assert (outputs[0] / "fixture_gate.log").is_file()
    assert (outputs[0] / "certification.json").exists() is (returncode == 0)
    assert previous.read_text(encoding="utf-8") == "Original native receipt"
