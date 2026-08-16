"""Static contract checks for the shared every-page Access component."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_shared_shells_mount_one_stable_page_access_template_tag() -> None:
    for relative in (
        "src/maru/templates/admin/base_site.html",
        "src/maru/core/templates/core/baseline_admin_base.html",
        "src/maru/registration/templates/registration/base_public.html",
    ):
        source = _source(relative)
        assert " page_access %}" in source
        assert "{% maru_page_access as maru_page_access_summary %}" in source
        assert "core/_page_access_summary.html" in source


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
