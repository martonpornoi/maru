import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from maru.identity.models import Account
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


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
