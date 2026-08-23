"""Static contract checks for the shared every-page Access component."""

from pathlib import Path

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
