import pytest
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from maru.identity.models import Account
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def test_account_can_sign_in_by_email_or_case_insensitive_human_username() -> None:
    account = Account.objects.create_user(
        email="roster-person@example.invalid",
        login_handle="Helpful Wolf",
        password="Shared rehearsal password 42!",
    )

    assert (
        authenticate(
            username="ROSTER-PERSON@EXAMPLE.INVALID",
            password="Shared rehearsal password 42!",
        )
        == account
    )
    assert (
        authenticate(
            username="helpful wolf",
            password="Shared rehearsal password 42!",
        )
        == account
    )
    assert (
        authenticate(
            username="Helpful Wolf",
            password="wrong password",
        )
        is None
    )


def test_account_login_username_is_optional_unique_and_printable() -> None:
    Account.objects.create_user(
        email="first@example.invalid",
        login_handle="RosterName",
    )
    duplicate = Account(
        email="second@example.invalid",
        login_handle="rostername",
    )
    with pytest.raises(ValidationError):
        duplicate.full_clean()

    invalid = Account(
        email="third@example.invalid",
        login_handle="line\nbreak",
    )
    with pytest.raises(ValidationError):
        invalid.full_clean()

    email_shaped = Account(
        email="fourth@example.invalid",
        login_handle="someone@example.invalid",
    )
    with pytest.raises(ValidationError):
        email_shaped.full_clean()


def test_account_uses_uuid_and_normalized_email() -> None:
    account = Account.objects.create_user(
        email=" Example@FUR.EXAMPLE ",
        password="not-a-real-secret",
        display_name="Example Fox",
    )

    assert account.email == "example@fur.example"
    assert account.id.version == 4
    assert str(account) == "Example Fox"


def test_account_factory_uses_synthetic_reserved_domain() -> None:
    account = AccountFactory()

    assert account.email.endswith("@example.invalid")
    assert account.has_usable_password()


def test_duplicate_normalized_email_is_rejected() -> None:
    Account.objects.create_user(
        email="example@fur.example",
        password="not-a-real-secret",
    )

    with pytest.raises((IntegrityError, ValidationError)):
        Account.objects.create_user(
            email="EXAMPLE@FUR.EXAMPLE",
            password="another-not-real-secret",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("is_staff", False, "is_staff"),
        ("is_superuser", False, "is_superuser"),
    ],
)
def test_superuser_flags_are_invariants(
    field: str,
    value: bool,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Account.objects.create_superuser(
            email="admin@fur.example",
            password="not-a-real-secret",
            **{field: value},
        )
