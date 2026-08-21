from __future__ import annotations

import re
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ISSUE_TEMPLATE_DIRECTORY = REPOSITORY_ROOT / ".github" / "ISSUE_TEMPLATE"
PRIVATE_REPORT_URL = "https://github.com/martonpornoi/maru/security/advisories/new"
CONDUCT_POLICY_URL = "https://github.com/martonpornoi/maru/blob/main/CODE_OF_CONDUCT.md"
SUPPORT_POLICY_URL = "https://github.com/martonpornoi/maru/blob/main/SUPPORT.md"
DISCUSSIONS_URL = "https://github.com/martonpornoi/maru/discussions"
GITHUB_ABUSE_URL = (
    "https://docs.github.com/en/communities/maintaining-your-safety-on-github/"
    "reporting-abuse-or-spam"
)
COMMUNITY_FILES = (
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "SUPPORT.md",
    "GOVERNANCE.md",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
)
ISSUE_FORM_LABELS = {"bug", "proposal", "triage"}
ISSUE_TEMPLATE_FILES = {"bug.yml", "config.yml", "feature.yml"}
ISSUE_FIELD_ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def _text(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def _assert_nonempty_text(value: object) -> None:
    assert isinstance(value, str)
    assert value.strip()


def _assert_issue_form_schema(form: object) -> None:
    assert isinstance(form, dict)
    assert set(form) == {"name", "description", "title", "labels", "body"}
    for key in ("name", "description", "title"):
        _assert_nonempty_text(form[key])

    labels = form["labels"]
    assert isinstance(labels, list)
    assert labels
    assert len(labels) == len(set(labels))
    for label in labels:
        _assert_nonempty_text(label)

    body = form["body"]
    assert isinstance(body, list)
    assert body
    field_ids: set[str] = set()
    rendered_labels: set[str] = set()
    for item in body:
        assert isinstance(item, dict)
        item_type = item.get("type")
        assert item_type in {"checkboxes", "input", "markdown", "textarea"}
        attributes = item.get("attributes")
        assert isinstance(attributes, dict)

        if item_type == "markdown":
            assert set(item) == {"type", "attributes"}
            assert set(attributes) == {"value"}
            _assert_nonempty_text(attributes["value"])
            continue

        assert set(item) <= {"type", "id", "attributes", "validations"}
        field_id = item.get("id")
        assert isinstance(field_id, str)
        assert ISSUE_FIELD_ID_PATTERN.fullmatch(field_id)
        assert field_id not in field_ids
        field_ids.add(field_id)

        rendered_label = attributes.get("label")
        _assert_nonempty_text(rendered_label)
        assert rendered_label not in rendered_labels
        rendered_labels.add(rendered_label)

        validations = item.get("validations", {})
        assert isinstance(validations, dict)
        assert set(validations) <= {"required"}
        if "required" in validations:
            assert isinstance(validations["required"], bool)

        if item_type == "checkboxes":
            assert set(attributes) <= {"label", "description", "options"}
            options = attributes.get("options")
            assert isinstance(options, list)
            assert options
            for option in options:
                assert isinstance(option, dict)
                assert set(option) == {"label", "required"}
                _assert_nonempty_text(option["label"])
                assert isinstance(option["required"], bool)
        else:
            assert set(attributes) <= {
                "label",
                "description",
                "placeholder",
                "render",
                "value",
            }


def test_public_community_materials_are_actionable_and_current() -> None:
    for relative_path in COMMUNITY_FILES:
        assert (REPOSITORY_ROOT / relative_path).is_file(), relative_path

    readme = _text("README.md")
    assert "[SUPPORT.md](SUPPORT.md)" in readme
    assert "[GOVERNANCE.md](GOVERNANCE.md)" in readme
    assert "[SECURITY.md](SECURITY.md)" in readme
    assert "[Code of Conduct](CODE_OF_CONDUCT.md)" in readme
    assert not re.search(r"\b\d[\d,]*\s+(?:of\s+\d[\d,]*\s+)?tests?\b", readme)
    assert not re.search(
        r"\b\d+(?:\.\d+)?(?:\s*%|\s+percent)\s+"
        r"(?:branch(?:-aware)?\s+)?coverage\b",
        readme,
        flags=re.IGNORECASE,
    )

    security = _text("SECURITY.md")
    assert PRIVATE_REPORT_URL in security

    conduct = _text("CODE_OF_CONDUCT.md")
    enforcement = conduct.split("## Enforcement\n", maxsplit=1)[1].split(
        "## Enforcement guidelines", maxsplit=1
    )[0]
    collapsed_enforcement = " ".join(enforcement.split())
    assert "before public launch" not in enforcement.casefold()
    assert "does not provide a private project-specific conduct-reporting" in (
        collapsed_enforcement
    )
    assert "mailto:" not in enforcement.casefold()
    assert PRIVATE_REPORT_URL not in enforcement
    assert GITHUB_ABUSE_URL in enforcement

    support = _text("SUPPORT.md")
    assert "no response or resolution time" in " ".join(support.split())

    governance = _text("GOVERNANCE.md")
    assert "## Adding or removing a maintainer" in governance
    assert "## Continuity and inactivity" in governance

    contributing = _text("CONTRIBUTING.md")
    assert "## Issue triage and newcomer work" in contributing
    assert "`good first issue`" in contributing
    assert "`help wanted`" in contributing


def test_issue_intake_preserves_reviewed_routes_fields_and_labels() -> None:
    template_files = {
        path.name for path in ISSUE_TEMPLATE_DIRECTORY.iterdir() if path.is_file()
    }
    assert template_files == ISSUE_TEMPLATE_FILES

    config = yaml.safe_load(
        (ISSUE_TEMPLATE_DIRECTORY / "config.yml").read_text(encoding="utf-8")
    )
    assert set(config) == {"blank_issues_enabled", "contact_links"}
    assert config["blank_issues_enabled"] is False
    assert isinstance(config["contact_links"], list)
    assert config["contact_links"]
    contact_names: set[str] = set()
    for link in config["contact_links"]:
        assert set(link) == {"name", "url", "about"}
        for key in ("name", "url", "about"):
            _assert_nonempty_text(link[key])
        assert link["name"] not in contact_names
        contact_names.add(link["name"])

    contact_urls = [link["url"] for link in config["contact_links"]]
    assert len(contact_urls) == len(set(contact_urls))
    assert set(contact_urls) == {
        PRIVATE_REPORT_URL,
        CONDUCT_POLICY_URL,
        SUPPORT_POLICY_URL,
        DISCUSSIONS_URL,
    }
    links_by_url = {link["url"]: link for link in config["contact_links"]}
    assert (
        "lack of a private conduct channel"
        in (links_by_url[CONDUCT_POLICY_URL]["about"])
    )

    expected_labels_by_form = {
        "bug.yml": {"bug", "triage"},
        "feature.yml": {"proposal", "triage"},
    }
    expected_fields_by_form = {
        "bug.yml": {
            "outcome": ("textarea", True),
            "evidence": ("textarea", True),
            "version": ("input", True),
            "environment": ("textarea", False),
            "safety": ("checkboxes", False),
        },
        "feature.yml": {
            "problem": ("textarea", True),
            "acceptance": ("textarea", True),
            "safety": ("textarea", True),
            "alternatives": ("textarea", False),
            "safety_confirmation": ("checkboxes", False),
        },
    }
    referenced_labels: set[str] = set()
    for form_name, expected_labels in expected_labels_by_form.items():
        form = yaml.safe_load(
            (ISSUE_TEMPLATE_DIRECTORY / form_name).read_text(encoding="utf-8")
        )
        _assert_issue_form_schema(form)
        form_labels = set(form["labels"])
        assert form_labels == expected_labels
        referenced_labels.update(form_labels)
        assert PRIVATE_REPORT_URL in _text(f".github/ISSUE_TEMPLATE/{form_name}")

        fields = {item["id"]: item for item in form["body"] if "id" in item}
        assert len(fields) == len([item for item in form["body"] if "id" in item])
        assert set(fields) == set(expected_fields_by_form[form_name])
        for field_id, (expected_type, required) in expected_fields_by_form[
            form_name
        ].items():
            field = fields[field_id]
            assert field["type"] == expected_type
            assert field.get("validations", {}).get("required", False) is required

        checkbox_fields = [
            field for field in fields.values() if field["type"] == "checkboxes"
        ]
        assert checkbox_fields
        for checkbox_field in checkbox_fields:
            assert all(
                option.get("required") is True
                for option in checkbox_field["attributes"]["options"]
            )

    assert referenced_labels == ISSUE_FORM_LABELS
