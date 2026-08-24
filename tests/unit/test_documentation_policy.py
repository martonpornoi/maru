"""Tests for curated documentation and synthetic-example policy."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from scripts.validate_docs import (
    PROHIBITED_CONVENTION_NAME_FINGERPRINTS,
    ROOT,
    ROOT_HUB_DOCNAMES,
    ethical_content_failures,
    markdown_files,
    navigation_failures,
    purpose_name_failures,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, content: str = "# Document\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _root_toctree(entries: tuple[str, ...] = ROOT_HUB_DOCNAMES) -> str:
    lines = ("# Documentation", "", "```{toctree}", ":hidden:", "", *entries, "```")
    return "\n".join(lines) + "\n"


def _minimal_documentation_tree(tmp_path: Path) -> Path:
    docs_root = tmp_path / "docs"
    _write(docs_root / "index.md", _root_toctree())
    for docname in ROOT_HUB_DOCNAMES:
        _write(docs_root / f"{docname}.md")
    return docs_root


def test_navigation_accepts_six_explicit_ordered_hubs(tmp_path: Path) -> None:
    docs_root = _minimal_documentation_tree(tmp_path)

    assert navigation_failures(docs_root) == []


def test_homepage_routes_remain_semantic_and_responsive() -> None:
    index = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    stylesheet = (ROOT / "docs" / "_static" / "maru.css").read_text(encoding="utf-8")

    assert all(
        heading in index
        for heading in (
            "### Understand Maru",
            "### Run Maru locally",
            "### Contribute safely",
        )
    )
    assert "display: grid;" in stylesheet
    assert "repeat(auto-fit, minmax(13rem, 1fr))" in stylesheet


def test_navigation_accepts_a_relative_docs_root(tmp_path: Path, monkeypatch) -> None:
    docs_root = _minimal_documentation_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert navigation_failures(docs_root.relative_to(tmp_path)) == []


def test_navigation_rejects_root_glob_and_wrong_hub_order(tmp_path: Path) -> None:
    docs_root = _minimal_documentation_tree(tmp_path)
    reversed_hubs = tuple(reversed(ROOT_HUB_DOCNAMES))
    _write(
        docs_root / "index.md",
        _root_toctree(reversed_hubs).replace(":hidden:", ":glob:"),
    )

    failures = navigation_failures(docs_root)

    assert any("must not use :glob:" in failure for failure in failures)
    assert any("exactly, in order" in failure for failure in failures)


def test_navigation_rejects_direct_archive_entries(tmp_path: Path) -> None:
    docs_root = _minimal_documentation_tree(tmp_path)
    _write(docs_root / "checkpoints" / "index.md")
    _write(
        docs_root / "index.md",
        _root_toctree((*ROOT_HUB_DOCNAMES, "checkpoints/index")),
    )

    failures = navigation_failures(docs_root)

    assert any("behind reference catalogs" in failure for failure in failures)


def test_navigation_accepts_hidden_catalogs_and_rejects_orphans(tmp_path: Path) -> None:
    docs_root = _minimal_documentation_tree(tmp_path)
    _write(
        docs_root / "reference" / "index.md",
        "# Reference\n\n"
        "```{toctree}\n"
        ":hidden:\n"
        ":glob:\n\n"
        "../architecture/decisions/*\n"
        "```\n",
    )
    _write(docs_root / "architecture" / "decisions" / "0001-example.md")
    _write(docs_root / "unlisted.md")

    failures = navigation_failures(docs_root)

    assert len(failures) == 1
    assert "unlisted.md" in failures[0]
    assert "0001-example.md" not in failures[0]


def test_purpose_naming_rejects_numbered_surface_labels(tmp_path: Path) -> None:
    _write(
        tmp_path / "docs" / "project" / "CURRENT.md",
        "# Current\n\nOpen Page 9a.1 to continue.\n",
    )

    failures = purpose_name_failures(tmp_path)

    assert len(failures) == 1
    assert "docs/project/CURRENT.md:3" in failures[0]
    assert "purpose name" in failures[0]


def test_purpose_naming_preserves_explicit_historical_records(tmp_path: Path) -> None:
    _write(
        tmp_path / "docs" / "project" / "CURRENT.md",
        "# Current\n\nOpen Organization structure to continue.\n",
    )
    _write(
        tmp_path / "docs" / "architecture" / "decisions" / "0001-history.md",
        "# Historical decision\n\nPage 9 was the accepted delivery label.\n",
    )
    _write(
        tmp_path / "docs" / "checkpoints" / "history.md",
        "# Checkpoint\n\nPage 9 passed.\n",
    )
    _write(
        tmp_path / "docs" / "project" / "PRODUCTION_CONSOLIDATION.md",
        "# Frozen ledger\n\nPage 9 remains historical evidence.\n",
    )

    assert purpose_name_failures(tmp_path) == []


def test_current_guidance_uses_purpose_names() -> None:
    assert purpose_name_failures(ROOT) == []


def test_ethical_policy_rejects_real_names_and_live_people_urls(
    tmp_path: Path,
) -> None:
    real_name = "Awoo" + "stria"
    real_roster_url = "https://real-con.example/" + "our-volunteers"
    _write(tmp_path / "README.md", f"Try {real_name}.\n")
    _write(
        tmp_path / "src" / "maru" / "demo" / "fixture.py",
        f'ROSTER = "{real_roster_url}"\n',
    )

    failures = ethical_content_failures(tmp_path)

    assert len(failures) == 2
    assert any("real convention name" in failure for failure in failures)
    assert any("external live-person directory URL" in failure for failure in failures)


def test_ethical_policy_keeps_fingerprints_for_retired_real_names() -> None:
    retired_names = {
        "Awoo" + "stria",
        "Con" + "Fuzzled",
        "Euro" + "furence",
        "Nordic" + "FuzzCon",
    }
    expected = {
        hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()
        for name in retired_names
    }

    assert expected <= PROHIBITED_CONVENTION_NAME_FINGERPRINTS


def test_ethical_policy_covers_historical_and_research_documents(
    tmp_path: Path,
) -> None:
    real_name = "Euro" + "furence"
    real_roster_url = "https://real-con.example/" + "staff"
    _write(tmp_path / "README.md", "Use MaruCon or MaruDance.\n")
    _write(
        tmp_path / "tests" / "fixture.py",
        'URL = "https://marucon.example.invalid/our-volunteers"\n',
    )
    _write(
        tmp_path / "docs" / "research" / "sources.md",
        f"# Research\n\n{real_name}: <{real_roster_url}>\n",
    )
    _write(
        tmp_path / "docs" / "architecture" / "decisions" / "0001-history.md",
        f"# Historical decision\n\nThe former {real_name} input was retired.\n",
    )
    _write(
        tmp_path / "docs" / "checkpoints" / "retirement.md",
        f"# Checkpoint\n\nRemoved {real_roster_url}.\n",
    )

    failures = ethical_content_failures(tmp_path)

    assert len(failures) == 4
    assert any("docs/research/sources.md" in failure for failure in failures)
    assert any("decisions/0001-history.md" in failure for failure in failures)
    assert any("checkpoints/retirement.md" in failure for failure in failures)


def test_ethical_policy_allows_fictional_data_and_software_attribution(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "README.md", "Use MaruCon or MaruDance.\n")
    _write(
        tmp_path / "tests" / "fixture.py",
        'URL = "https://marucon.example.invalid/our-volunteers"\n',
    )
    _write(
        tmp_path / "THIRD_PARTY_NOTICES.md",
        "# Notices\n\nDjango, PostgreSQL, NumPy, Sphinx, and Furo retain their "
        "respective licenses.\n",
    )

    assert ethical_content_failures(tmp_path) == []


def test_documentation_policy_excludes_local_certification_artifacts(
    tmp_path: Path,
) -> None:
    real_name = "Awoo" + "stria"
    real_roster_url = "https://real-con.example/" + "our-volunteers"
    generated = tmp_path / ".local-ci" / "tmp" / "unit" / "README.md"
    _write(generated, f"{real_name}: <{real_roster_url}>\n")

    assert generated not in markdown_files(tmp_path)
    assert ethical_content_failures(tmp_path) == []
