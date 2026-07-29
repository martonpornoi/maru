from maru.core.templatetags.admin_help import admin_page_help


def test_admin_page_help_covers_utility_and_fallback_pages() -> None:
    assert "replace your bootstrap administration password" in admin_page_help(
        "/admin/password_change/"
    )
    assert "search and filters" in admin_page_help("/admin/unknown/")


def test_account_help_explains_selected_workspace_visibility() -> None:
    help_text = admin_page_help(
        "/admin/identity/account/",
        "identity",
        "account",
    )

    assert "newly created account is still saved" in help_text
    assert "All foundation data" in help_text
