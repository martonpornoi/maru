from pathlib import Path

from django.contrib.staticfiles import finders
from django.template.loader import get_template


def _static_text(relative_path: str) -> str:
    found = finders.find(relative_path)
    assert isinstance(found, str)
    return Path(found).read_text(encoding="utf-8")


def _template_text(template_name: str) -> str:
    template = get_template(template_name)
    assert template.origin is not None
    return Path(template.origin.name).read_text(encoding="utf-8")


def test_navigation_filter_covers_every_projected_menu_item() -> None:
    script = _static_text("core/navigation.js")

    assert "[data-navigation-item]" in script
    assert "dataset.navigationSearch" in script
    assert "event.key !== 'Escape'" in script
    assert "technical record" in script
    assert "sessionStorage.removeItem" in script
    assert "sessionStorage.setItem" not in script
    assert "sessionStorage.getItem" not in script
    assert "dataset.navigationGroupKind === 'advanced'" in script


def test_server_rendered_action_errors_receive_keyboard_focus() -> None:
    script = _static_text("core/navigation.js")

    assert "[data-maru-focus-on-load]" in script
    assert "requestAnimationFrame(() => focusTarget.focus())" in script

    for template_name in (
        "registration/setup_action_base.html",
        "workforce/organization_structure_action_base.html",
        "workforce/position_action_base.html",
    ):
        template = _template_text(template_name)
        assert 'role="alert"' in template
        assert 'tabindex="-1"' in template
        assert "data-maru-focus-on-load" in template


def test_navigation_template_has_stable_accessible_text_and_glyphs() -> None:
    sidebar = _template_text("admin/nav_sidebar.html")
    base_site = _template_text("admin/base_site.html")

    assert chr(0xC2) not in base_site

    assert 'placeholder="Search tasks and records..."' in sidebar
    assert "Find a task or record" in sidebar
    assert "Customize navigation" in sidebar
    assert 'class="maru-navigation-pin"' in sidebar
    assert "available pages" not in sidebar
    assert "&#9733;" in sidebar
    assert "&#9734;" in sidebar
    assert chr(0xE2) not in sidebar
    assert "â" not in sidebar
    assert "{{ edition.name }} · {{ edition.organization.name }}" in base_site
