"""Tests for curated documentation and synthetic-example policy."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from scripts.validate_docs import (
    EXPECTED_AGENT_SKILLS,
    PROHIBITED_CONVENTION_NAME_FINGERPRINTS,
    ROOT,
    ROOT_HUB_DOCNAMES,
    agent_skill_failures,
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


def _write_agent_skill(root: Path, name: str) -> None:
    skill_root = root / ".agents" / "skills" / name
    _write(
        skill_root / "SKILL.md",
        "---\n"
        f"name: {name}\n"
        f'description: "Use {name} for one focused Maru workflow."\n'
        "---\n\n"
        f"# {name}\n\n"
        "Read [the focused reference](references/focused.md).\n",
    )
    _write(
        skill_root / "references" / "focused.md",
        "# Focused reference\n\nFollow the maintained contract.\n",
    )
    metadata = (
        "interface:\n"
        f'  display_name: "{name}"\n'
        '  short_description: "Run one focused Maru workflow safely"\n'
        f'  default_prompt: "Use ${name} for this Maru task."\n'
    )
    _write(skill_root / "agents" / "openai.yaml", metadata)


def _minimal_agent_skill_tree(root: Path) -> None:
    for name in EXPECTED_AGENT_SKILLS:
        _write_agent_skill(root, name)


def test_navigation_accepts_six_explicit_ordered_hubs(tmp_path: Path) -> None:
    docs_root = _minimal_documentation_tree(tmp_path)

    assert navigation_failures(docs_root) == []


def test_repository_agent_skills_satisfy_the_curated_policy() -> None:
    assert agent_skill_failures(ROOT) == []


def test_agent_skill_policy_accepts_focused_discoverable_skills(
    tmp_path: Path,
) -> None:
    _minimal_agent_skill_tree(tmp_path)

    assert agent_skill_failures(tmp_path) == []


def test_agent_skill_policy_rejects_drift_and_unreachable_detail(
    tmp_path: Path,
) -> None:
    _minimal_agent_skill_tree(tmp_path)
    skill_name = EXPECTED_AGENT_SKILLS[0]
    skill_root = tmp_path / ".agents" / "skills" / skill_name
    skill_path = skill_root / "SKILL.md"
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8").replace(
            f"name: {skill_name}", "name: wrong-skill"
        ),
        encoding="utf-8",
    )
    _write(skill_root / "references" / "orphan.md", "# Unreachable detail\n")
    metadata_path = skill_root / "agents" / "openai.yaml"
    metadata_path.write_text(
        metadata_path.read_text(encoding="utf-8").replace(
            f"Use ${skill_name}", "Use this workflow"
        ),
        encoding="utf-8",
    )

    failures = agent_skill_failures(tmp_path)

    assert any("frontmatter name" in failure for failure in failures)
    assert any("orphan.md" in failure for failure in failures)
    assert any("default_prompt" in failure for failure in failures)


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


def test_assignment_evidence_contract_remains_profile_aware() -> None:
    requirements = (ROOT / "docs" / "product" / "requirements.md").read_text(
        encoding="utf-8"
    )
    roadmap = (ROOT / "docs" / "project" / "ROADMAP.md").read_text(encoding="utf-8")
    page_contract = (
        ROOT / "docs" / "product" / "page-contracts" / "assignment-management.md"
    ).read_text(encoding="utf-8")
    runbook = (
        ROOT / "docs" / "operations" / "workforce-only-adoption-and-recovery.md"
    ).read_text(encoding="utf-8")
    workforce_module = (ROOT / "docs" / "modules" / "workforce.md").read_text(
        encoding="utf-8"
    )
    experience = (
        ROOT / "docs" / "product" / "experience-and-information-architecture.md"
    ).read_text(encoding="utf-8")
    domain_model = (ROOT / "docs" / "domain" / "domain-model.md").read_text(
        encoding="utf-8"
    )
    key_workflows = (ROOT / "docs" / "product" / "key-workflows.md").read_text(
        encoding="utf-8"
    )
    adr_0076 = (
        ROOT
        / "docs"
        / "architecture"
        / "decisions"
        / "0076-owner-safe-position-assignment-lifecycle.md"
    ).read_text(encoding="utf-8")
    adr_0080 = (
        ROOT
        / "docs"
        / "architecture"
        / "decisions"
        / "0080-progressive-workforce-only-adoption.md"
    ).read_text(encoding="utf-8")
    adr_index = (ROOT / "docs" / "architecture" / "decisions" / "index.md").read_text(
        encoding="utf-8"
    )
    adr_status_index = (
        ROOT / "docs" / "architecture" / "decisions" / "README.md"
    ).read_text(encoding="utf-8")

    for document in (
        requirements,
        roadmap,
        page_contract,
        runbook,
        workforce_module,
        adr_0080,
    ):
        assert "`full_convention@1`" in document
        assert "`workforce_only@1`" in document
        assert "integrity conflict" in document
    assert "independent assignment approval" in runbook
    assert "retained ending revokes the RoleAssignment" in runbook
    assert "`participation_capacity_id` null" in runbook
    assert "Participation counts stay zero" in runbook
    assert "`workforce.0014_workforce_only_assignment_evidence`" in runbook
    assert "`workforce.0015_exact_assignment_adoption_profile`" in runbook
    assert (
        runbook.index("Confirm that approval")
        < runbook.index("complete the bounded Availability")
        < runbook.index("Then end the assignment")
    )
    assert "Status: Partially superseded by ADR 0080" in adr_0076
    assert "The same transaction activates edition" in adr_0076
    assert "ADR 0076 only where Position" in adr_0080
    assert "HR-013" in adr_0080
    assert (
        "[0076](0076-owner-safe-position-assignment-lifecycle.md) | "
        "Partially superseded"
    ) in adr_index
    assert (
        "[0076](0076-owner-safe-position-assignment-lifecycle.md) | "
        "Partially superseded"
    ) in adr_status_index
    assert "`workforce_only@1` keeps a null assignment pointer" in adr_index
    assert "only the evidence" in experience
    assert "required by the immutable edition profile" in experience
    assert "An assignment joins a person to a position" in domain_model
    assert "accepted application records its typed transition evidence" in key_workflows
    assert (
        key_workflows.index("accepted application")
        < key_workflows.index("separately proposes the Position assignment")
        < key_workflows.index("that approval activates")
    )
    assert "Workforce-only creates no attendee Participation" in key_workflows

    collapsed = {
        name: " ".join(document.split())
        for name, document in {
            "requirements": requirements,
            "roadmap": roadmap,
            "page_contract": page_contract,
            "runbook": runbook,
            "workforce_module": workforce_module,
            "experience": experience,
            "domain_model": domain_model,
            "key_workflows": key_workflows,
        }.items()
    }
    assert (
        "activate the linked role and adopted-profile capacities"
        not in collapsed["requirements"]
    )
    assert "linked role and participation capacities" not in collapsed["roadmap"]
    assert "dual-controlled role/capacity activation" not in collapsed["roadmap"]
    assert (
        "which role and participation evidence approval activates"
        not in collapsed["page_contract"]
    )
    assert "all three migrations" not in collapsed["runbook"]
    assert "Then continue through Availability and Shifts" not in collapsed["runbook"]
    assert (
        "marks the assignment ended, completes only Position-specific"
        not in collapsed["workforce_module"]
    )
    assert (
        "approval atomically activates role and participation evidence"
        not in collapsed["experience"]
    )
    assert (
        "An assignment joins a participation to a position"
        not in collapsed["domain_model"]
    )
    assert (
        "An accepted offer creates an edition participation and role assignment"
        not in collapsed["key_workflows"]
    )


def test_programme_operations_contract_remains_purpose_bounded() -> None:
    requirements = (ROOT / "docs" / "product" / "requirements.md").read_text(
        encoding="utf-8"
    )
    adr = (
        ROOT
        / "docs"
        / "architecture"
        / "decisions"
        / "0081-composite-programme-operations-adoption.md"
    ).read_text(encoding="utf-8")
    adr_index = (ROOT / "docs" / "architecture" / "decisions" / "index.md").read_text(
        encoding="utf-8"
    )
    adr_status_index = (
        ROOT / "docs" / "architecture" / "decisions" / "README.md"
    ).read_text(encoding="utf-8")
    page_contract = (
        ROOT
        / "docs"
        / "product"
        / "page-contracts"
        / "programme-operations-adoption-setup.md"
    ).read_text(encoding="utf-8")

    collapsed_requirements = " ".join(requirements.split())
    collapsed_adr = " ".join(adr.split())
    collapsed_page_contract = " ".join(page_contract.split())

    for requirement_code in (
        "EVT-007",
        "HR-015",
        "PRG-008",
        "SCH-011",
        "SCH-012",
        "OPS-009",
    ):
        assert f"**{requirement_code} —" in requirements

    assert "`programme_operations@1`" in requirements
    assert "`programme_operations@1`" in adr
    assert "exact `(profile code, profile version)` manifest" in collapsed_adr
    assert (
        "every participating capability, destination, effect, and adapter"
        in collapsed_requirements
    )
    assert "complete current Workforce journey" in collapsed_adr
    assert "not a hidden partial Workforce module" in collapsed_adr

    def manifest_namespaces(kind: str) -> set[str]:
        row = next(
            line
            for line in page_contract.splitlines()
            if line.startswith(f"| {kind} |")
        )
        return {value.strip("`") for value in row.split("|")[2].strip().split(", ")}

    expected_manifest = {
        "Shared foundations": {
            "audit",
            "authorization",
            "effects",
            "events",
            "identity",
            "organizations",
            "privacy",
        },
        "Adopted products": {
            "applications",
            "programme",
            "scheduling",
            "venues",
            "workforce",
        },
        "Excluded products": {
            "accreditation",
            "catalog",
            "charities",
            "communications",
            "logistics",
            "participation",
            "registration",
        },
    }
    actual_manifest = {kind: manifest_namespaces(kind) for kind in expected_manifest}
    assert actual_manifest == expected_manifest
    assert actual_manifest["Shared foundations"].isdisjoint(
        actual_manifest["Adopted products"]
    )
    assert actual_manifest["Shared foundations"].isdisjoint(
        actual_manifest["Excluded products"]
    )
    assert actual_manifest["Adopted products"].isdisjoint(
        actual_manifest["Excluded products"]
    )
    assert "operations" not in set().union(*actual_manifest.values())

    assert "Status: Accepted contract, runtime absent" in page_contract
    assert (
        "non-routable until the complete integrated profile is implemented and accepted"
        in collapsed_page_contract
    )
    assert (
        "reserved route must return the ordinary safe not-found response"
        in collapsed_page_contract
    )
    assert "purpose-specific Effects delivery remains permitted" in page_contract
    assert "Programme collaboration invitation" in collapsed_adr

    for owner in (
        "**Events** owns",
        "**Applications** owns",
        "**Programme** owns",
        "**Scheduling** owns",
        "**Venues** owns",
        "**Workforce** owns",
    ):
        assert owner in adr

    assert "Partially supersedes: ADR 0053" in adr
    assert "sole public Programme timing source" in adr_index
    assert (
        "[0053](0053-reusable-venue-catalog-and-physical-space-occupancy.md) | "
        "Partially superseded"
    ) in adr_status_index
    assert "[0081](0081-composite-programme-operations-adoption.md)" in adr_index
    assert "[0081](0081-composite-programme-operations-adoption.md)" in adr_status_index

    assert "exclude Participation" in collapsed_adr
    assert "assignment Participation-capacity pointer to remain null" in collapsed_adr
    assert "without a Participation row" in collapsed_adr
    assert "may never silently rewrite" in collapsed_adr
    assert "immediately removes the unsafe room assignment" in collapsed_adr
    assert "revokes the ordinary last-published degraded snapshot" in collapsed_adr
    assert "issue #24" in collapsed_adr
    for deferred_boundary in (
        "check-in",
        "lateness",
        "absence",
        "actual time",
        "correction and dispute",
        "Shift handover",
    ):
        assert deferred_boundary in collapsed_adr
