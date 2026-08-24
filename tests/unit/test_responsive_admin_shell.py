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


def test_sidebar_drawer_has_accessible_controls_and_interaction_contract() -> None:
    sidebar = _template_text("admin/nav_sidebar.html")
    shell = _template_text("admin/base_site.html")

    assert 'aria-controls="nav-sidebar"' in sidebar
    assert "data-navigation-backdrop" in sidebar
    assert "data-navigation-close" in sidebar
    assert "data-navigation-collapsible" in sidebar
    assert "data-navigation-search-only=" in sidebar
    assert "data-navigation-current=" in sidebar
    assert "data-navigation-kind=" in sidebar
    assert 'event.key === "Escape"' in shell
    assert 'event.key !== "Tab"' in shell
    assert "returnFocus.focus()" in shell
    assert "maru-navigation-drawer-open" in shell
    assert "sidebar.inert = !expanded" in shell
    assert 'document.getElementById("content-start")' in shell
    assert "setDrawerBackgroundHidden(expanded)" in shell
    assert 'element.setAttribute("aria-hidden", "true")' in shell
    assert "element.inert = hidden" in shell
    assert "window.setTimeout(() => closeButton.focus(), 0)" in shell


def test_shell_collapses_before_phone_width_without_forcing_content_overflow() -> None:
    responsive = _static_text("core/admin-responsive.css")
    shell = _static_text("core/admin-help.css")

    assert "@media (max-width: 1100px)" in responsive
    drawer_rules = responsive.split("@media (max-width: 1100px)", maxsplit=1)[1]
    assert "position: fixed;" in drawer_rules
    assert "width: min(20rem, calc(100vw - 3rem));" in drawer_rules
    assert "max-width: 100%;" in drawer_rules
    assert "overflow: hidden;" in drawer_rules
    assert "@media (max-width: 1100px)" in shell
    context = shell.split(".maru-edition-context {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "display: flex;" in context
    assert "justify-content: space-between;" in context
    assert "flex: 1 0 100%;" not in context
    switcher = shell.split(".maru-edition-context-switcher > form {", maxsplit=1)[
        1
    ].split("}", maxsplit=1)[0]
    assert "position: absolute;" in switcher
    assert "width: min(28rem, calc(100vw - 2rem));" in switcher


def test_management_page_fragments_do_not_nest_main_landmarks() -> None:
    template_root = Path(__file__).resolve().parents[2] / "src/maru"
    management_parents = (
        '{% extends "admin/base_site.html" %}',
        '{% extends "core/baseline_admin_base.html" %}',
        "{% extends baseline_admin_parent_template %}",
    )

    for path in template_root.rglob("*.html"):
        if path.name == "baseline_admin_base.html":
            continue
        source = path.read_text(encoding="utf-8")
        if any(parent in source for parent in management_parents):
            assert "<main" not in source, path
