"""Static contract checks for the shared every-page Access component."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from django.template import Context
from django.template.loader import render_to_string
from django.test import RequestFactory

from maru.authorization.page_access import (
    build_page_access_summary,
    fixed_page_access,
    scoped_page_access,
)
from maru.core.templatetags import page_access

ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_shared_shells_mount_one_stable_page_access_template_tag() -> None:
    mount = _source("src/maru/core/templates/core/_page_access_mount.html")
    assert " page_access %}" in mount
    assert "{% maru_page_access as maru_page_access_summary %}" in mount
    assert "core/_page_access_summary.html" in mount

    admin_shell = _source("src/maru/templates/admin/base_site.html")
    baseline_compatibility = _source(
        "src/maru/core/templates/core/_baseline_access_summary.html"
    )
    public_shell = _source(
        "src/maru/registration/templates/registration/base_public.html"
    )
    assert "core/_page_access_mount.html" in admin_shell
    assert "not maru_shell_access_rendered_by_page" in admin_shell
    assert "core/_page_access_mount.html" in baseline_compatibility
    assert "{% maru_page_access as maru_page_access_summary %}" in public_shell


def test_access_summary_is_compact_until_the_reader_requests_details() -> None:
    source = _source("src/maru/core/templates/core/_page_access_summary.html")

    assert '<details class="maru-access-summary">' in source
    assert '<summary id="maru-access-heading">' in source
    assert "<strong>Access</strong>" in source
    assert '<h2 id="maru-access-heading">' not in source


@pytest.mark.parametrize(
    ("policy", "expected_label"),
    [
        ("scoped", "Access for this area"),
        ("self", "Your own records"),
        ("fixed", "Rules for this page"),
    ],
)
def test_plain_access_labels_keep_exact_scope_and_details_without_management(
    policy: str, expected_label: str
) -> None:
    scope = "Synthetic Foxglove / Evening & late-night team"
    explanation = "Your current event access controls what you can read or change."
    spec = (
        fixed_page_access(policy=policy, scope_label=scope, explanation=explanation)
        if policy != "scoped"
        else scoped_page_access(
            target=None, scope_label=scope, intents=(), explanation=explanation
        )
    )
    summary = build_page_access_summary(principal=object(), spec=spec)
    rendered = render_to_string(
        "core/_page_access_summary.html", {"maru_page_access": summary}
    )

    assert summary.policy == policy
    assert summary.scope_label == scope
    assert summary.explanation == explanation
    assert f'class="maru-access-summary__policy">{expected_label}</span>' in rendered
    assert "Synthetic Foxglove / Evening &amp; late-night team" in rendered
    assert explanation in rendered
    assert "Manage access</a>" not in rendered
    assert "Preview access</a>" not in rendered
    assert not summary.can_manage


def test_unresolved_access_scope_does_not_reveal_an_unverified_context(monkeypatch):
    monkeypatch.setattr(page_access, "selected_admin_edition", lambda _request: None)
    request = RequestFactory().get("/admin/unresolved/")
    request.user = object()
    context = Context(
        {
            "request": request,
            "organization": SimpleNamespace(name="PRIVATE <organizer> & details"),
        }
    )

    summary = page_access.maru_page_access(context)
    rendered = render_to_string(
        "core/_page_access_summary.html", {"maru_page_access": summary}
    )

    assert summary.policy == "fixed"
    assert summary.scope_label == "This page"
    assert summary.explanation == (
        "This page has its own access rules. You cannot change who "
        "has access from this page."
    )
    assert "Rules for this page" in rendered
    assert "PRIVATE" not in rendered
    assert not summary.can_manage
    assert not summary.manage_url
    assert not summary.preview_url
    assert "Manage access</a>" not in rendered
    assert "Preview access</a>" not in rendered


def test_direct_page_mounts_follow_the_page_heading() -> None:
    template_root = ROOT / "src/maru"
    for path in template_root.rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        if "core/_page_access_mount.html" not in source:
            continue
        if path.name in {
            "_baseline_access_summary.html",
            "admin_workspace.html",
            "base_site.html",
        }:
            continue
        assert "<h1" in source, path
        assert source.index("<h1") < source.index("core/_page_access_mount.html"), path


def test_embedded_staff_console_owns_its_rendered_access_summary() -> None:
    source = _source("src/maru/core/templates/core/admin_workspace.html")

    assert "{% block content_subtitle %}{% endblock %}" in source
    assert "maru-embedded-page-access-template" not in source
    assert "core/_page_access_mount.html" not in source
    assert source.index("{% block content_subtitle %}") < source.index(
        "{% block content %}"
    )


def test_access_workspace_preview_is_read_only_and_contains_no_mojibake() -> None:
    source = _source(
        "src/maru/authorization/templates/authorization/page_access_workspace.html"
    )
    assert "Preview only" in source
    assert 'value="preview_person"' in source
    assert 'value="preview_role"' in source
    assert "{% if preview %}" in source
    assert "{% else %}" in source
    assert "&middot;" in source
    assert "·" not in source
    for marker in ("Â", "â", "�"):
        assert marker not in source
