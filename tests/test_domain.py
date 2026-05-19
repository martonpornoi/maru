import pytest

from maru.domain import (
    AccessAccount,
    Role,
    TimetableRound,
    TimetableVisibility,
    seeded_accounts,
)


def test_seeded_account_has_full_control() -> None:
    account = seeded_accounts()[0]

    assert account.email == "marton.pornoi@gmail.com"
    assert account.can_start_project
    assert Role.ADMIN in account.roles


def test_accounts_require_google_email() -> None:
    with pytest.raises(ValueError, match="Google email"):
        AccessAccount(email="person@example.org")


def test_private_round_only_shows_own_panel_to_regular_users() -> None:
    visibility = TimetableVisibility(TimetableRound.PRIVATE_PLACEMENT)

    assert visibility.can_view_panel(
        viewer_email="host@gmail.com",
        owner_email="host@gmail.com",
        viewer_roles=frozenset({Role.HOST}),
    )
    assert not visibility.can_view_panel(
        viewer_email="host@gmail.com",
        owner_email="other@gmail.com",
        viewer_roles=frozenset({Role.HOST}),
    )


def test_admin_can_view_any_panel_in_private_round() -> None:
    visibility = TimetableVisibility(TimetableRound.PRIVATE_PLACEMENT)

    assert visibility.can_view_panel(
        viewer_email="admin@gmail.com",
        owner_email="host@gmail.com",
        viewer_roles=frozenset({Role.ADMIN}),
    )


def test_public_round_exposes_full_timetable() -> None:
    visibility = TimetableVisibility(TimetableRound.PUBLIC)

    assert visibility.exposes_full_timetable_to_registered_users()

