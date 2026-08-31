from pathlib import Path

from maru.core.templatetags.admin_help import admin_page_help


def test_admin_page_help_covers_utility_and_fallback_pages() -> None:
    assert "replace your bootstrap administration password" in admin_page_help(
        "/admin/password_change/"
    )
    assert "search and filters" in admin_page_help("/admin/unknown/")
    home_help = admin_page_help("/admin/")
    assert "Registration desk to help an attendee" in home_help
    assert "Registration configurations" not in home_help
    workforce_help = admin_page_help("/admin/", "", "", "workforce")
    assert "Departments, Positions, assignments" in workforce_help


def test_account_help_explains_inspection_and_invitation_boundaries() -> None:
    help_text = admin_page_help(
        "/admin/identity/account/",
        "identity",
        "account",
    )

    assert "read-only specialist page" in help_text
    assert "Platform administration > Accounts" in help_text
    assert "createsuperuser" in help_text
    assert "without changing its credentials" in help_text


def test_edition_context_trail_uses_a_compact_disclosed_switcher() -> None:
    css_path = (
        Path(__file__).parents[2]
        / "src"
        / "maru"
        / "core"
        / "static"
        / "core"
        / "admin-help.css"
    )
    source = css_path.read_text(encoding="utf-8")
    base = source.split("@media (max-width: 1100px)", maxsplit=1)[0]
    base_trail_rule = base.split(".maru-edition-context-trail {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    base_context_rule = base.split(".maru-edition-context {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    switcher_rule = base.split(".maru-edition-context-switcher > form {", maxsplit=1)[
        1
    ].split("}", maxsplit=1)[0]

    assert "display: flex;" in base_context_rule
    assert "justify-content: space-between;" in base_context_rule
    assert "width: 100%;" in base_context_rule
    assert "min-width: 0;" in base_trail_rule
    assert "position: absolute;" in switcher_rule
    assert "width: min(28rem, calc(100vw - 2rem));" in switcher_rule
